#!/usr/bin/env python3
"""JobBot Telegram bot (launchd com.jobbot.telegram, KeepAlive).

    jobbot/.venv/bin/python jobbot/bot/bot.py

Long polling. Only messages from TELEGRAM_CHAT_ID are handled (and, when the optional
TELEGRAM_USER_ID is set, only from that user); everything else is ignored (and logged
without content). Edited messages never run a command. All logic lives in logic.py.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import logic  # noqa: E402
from logic import common, i18n, t  # noqa: E402
import telegram_send as tg  # noqa: E402

from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update  # noqa: E402
from telegram.constants import ParseMode  # noqa: E402
from telegram.ext import (  # noqa: E402
    Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters)

log = logging.getLogger("jobbot.bot")


class Allowed(filters.Chat):
    """Who may talk to the bot: the configured chat and, when TELEGRAM_USER_ID is set, only that user
    (in a group, every member writes in the allowed chat). With edited=False an edited message is
    refused: correcting a typo in "/no 12 …" must not run the command a second time."""

    __slots__ = ("only_user", "edited")

    def __init__(self, chat_id: int, user_id: int | None = None, edited: bool = True):
        super().__init__(chat_id=chat_id)
        self.only_user = user_id
        self.edited = edited

    def check_update(self, update: Update):
        if not self.edited and (update.edited_message or update.edited_channel_post
                                or getattr(update, "edited_business_message", None)):
            return False
        return super().check_update(update)

    def filter(self, message) -> bool:
        if not super().filter(message):
            return False
        if self.only_user is None:
            return True
        return message.from_user is not None and message.from_user.id == self.only_user


def chat_filter(chat_id: str, user_id: str | None = None, edited: bool = True):
    return Allowed(int(chat_id), int(user_id) if user_id else None, edited)


async def reply(update: Update, text: str) -> None:
    # Split on line boundaries: a cut inside <a …> or <b> makes Telegram reject the HTML.
    for chunk in tg._chunks(text):
        await update.effective_message.reply_text(chunk, parse_mode=ParseMode.HTML, disable_web_page_preview=True)


async def advance(update: Update | None = None) -> None:
    """V5: after the reply, show the next offer if the command closed the shown one (offer_queue.advance)."""
    try:
        await asyncio.to_thread(logic.oq.advance)
    except Exception as exc:  # noqa: BLE001 — never lose the reply over the queue; the next command retries
        log.exception("offer queue advance failed")
        if update is not None and isinstance(exc, common.CorruptState):
            try:  # a broken queue file must be visible: no offer would ever be shown again
                await reply(update, logic.error_text(exc))
            except Exception:  # noqa: BLE001
                log.exception("could not report the corrupt state file")


def handler(fn, takes_args: bool = True):
    async def run(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        args = " ".join(context.args or [])
        try:
            text = await asyncio.to_thread(fn, args) if takes_args else await asyncio.to_thread(fn)
        except common.LockBusy as exc:
            text = logic.error_text(exc)
        except Exception as exc:  # noqa: BLE001
            log.exception("command failed")
            text = logic.error_text(exc)
        await reply(update, text)
        await advance(update)
    return run


def with_buttons(fn, takes_args: bool = False):
    """Commands returning (text, [(label, callback data)]): buttons go under the last chunk."""
    async def run(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        args = " ".join(context.args or [])
        try:
            text, buttons = await asyncio.to_thread(fn, args) if takes_args else await asyncio.to_thread(fn)
        except common.LockBusy as exc:
            text, buttons = logic.error_text(exc), []
        except Exception as exc:  # noqa: BLE001
            log.exception("command failed")
            text, buttons = logic.error_text(exc), []
        chunks = tg._chunks(text)
        markup = InlineKeyboardMarkup([[InlineKeyboardButton(label, callback_data=data)] for label, data in buttons]) \
            if buttons else None
        for i, chunk in enumerate(chunks):
            await update.effective_message.reply_text(chunk, parse_mode=ParseMode.HTML, disable_web_page_preview=True,
                                                      reply_markup=markup if i == len(chunks) - 1 else None)
        await advance(update)
    return run


# /pending: the list plus one inline button per application ("resend the files").
pending = with_buttons(logic.cmd_pending_view)

BUTTONS = {"resend": "resend_files", "ruledel": "rule_confirm", "ruleno": "rule_cancel",  # logic.<name>, looked up per call
           "fu": "followup_done", "reply": "reply_button", "keep": "contact_keep", "purge": "contact_purge"}  # V5
ONE_SHOT = ("ruledel", "ruleno", "fu", "reply", "keep", "purge")  # buttons removed once pressed
BUTTON_PATTERN = r"^(" + "|".join(BUTTONS) + r"):"


def button_handler(chat_id: str, user_id: str | None = None):
    """Callback buttons carry no chat filter in python-telegram-bot: check the chat (and the user) here."""
    async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        chat = update.effective_chat
        if chat is None or str(chat.id) != str(chat_id):
            log.warning("ignored button from chat %s", chat.id if chat else "?")
            return
        user = update.effective_user if user_id else None
        if user_id and (user is None or str(user.id) != str(user_id)):
            log.warning("ignored button from another user in chat %s", chat.id)
            return
        await query.answer()
        data = query.data or ""
        kind, _, arg = data.partition(":")
        fn = getattr(logic, BUTTONS[kind]) if kind in BUTTONS else None
        if fn is None or not arg:
            return
        if kind in ONE_SHOT:
            try:  # one-shot confirmation: remove the buttons so they cannot be pressed twice
                await query.edit_message_reply_markup(reply_markup=None)
            except Exception:  # noqa: BLE001
                log.warning("could not remove buttons")
        buttons = []
        try:
            text = await asyncio.to_thread(fn, arg)
            if isinstance(text, tuple):  # (text, [(label, data)]): e.g. a /reply S… asks "keep this contact?"
                text, buttons = text
        except common.LockBusy as exc:
            text = logic.error_text(exc)
        except Exception as exc:  # noqa: BLE001
            log.exception("button %s failed", kind)
            text = logic.error_text(exc)
        chunks = tg._chunks(text)
        markup = InlineKeyboardMarkup([[InlineKeyboardButton(label, callback_data=data) for label, data in buttons]]) \
            if buttons else None
        for i, chunk in enumerate(chunks):
            await query.message.reply_text(chunk, parse_mode=ParseMode.HTML, disable_web_page_preview=True,
                                           reply_markup=markup if i == len(chunks) - 1 else None)
    return on_button


async def publish_commands(bot) -> None:
    """The Telegram command menu, in the current language (replaces /setcommands at @BotFather)."""
    try:
        await bot.set_my_commands([BotCommand(name, desc) for name, desc in logic.menu_commands()])
    except Exception:  # noqa: BLE001 — the menu is a convenience; the commands work without it
        log.exception("set_my_commands failed")


async def lang_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/lang [code]: like handler(), then the command menu follows the new language."""
    args = " ".join(context.args or [])
    before = i18n.lang()
    try:
        text = await asyncio.to_thread(logic.cmd_lang, args)
    except common.LockBusy as exc:
        text = logic.error_text(exc)
    except Exception as exc:  # noqa: BLE001
        log.exception("command failed")
        text = logic.error_text(exc)
    await reply(update, text)
    if i18n.lang() != before:
        await publish_commands(context.bot)


async def post_init(app: Application) -> None:
    await publish_commands(app.bot)


async def ignore_stranger(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    log.warning("ignored update from chat %s", chat.id if chat else "?")


def build(token: str, chat_id: str, user_id: str | None = None) -> Application:
    app = Application.builder().token(token).post_init(post_init).build()
    allowed = chat_filter(chat_id, user_id)            # strangers = everything outside this
    mine = chat_filter(chat_id, user_id, edited=False)  # commands: an edited message is not a new command
    commands = {
        "help": (logic.cmd_help, False), "start": (logic.cmd_help, False),
        "search": (logic.cmd_search, True), "no": (logic.cmd_no, True),
        "rules": (logic.cmd_rules, False),
        "block": (logic.cmd_block, True), "blocked": (logic.cmd_blocked, False),
        "unblock": (logic.cmd_unblock, True),
        "spont": (logic.cmd_spont, True),
        "discover": (logic.cmd_discover, True), "companies": (logic.cmd_companies, False),
        "accept": (logic.cmd_accept, True), "reject": (logic.cmd_reject, True),
        "allow": (logic.cmd_allow, True), "deny": (logic.cmd_deny, True),
        "sites": (lambda: logic.pending_list_text(refresh=True), False),
        "region": (logic.cmd_region, True), "regions": (logic.cmd_regions, False),
        "status": (logic.cmd_status, False),
        "rejets": (logic.cmd_rejets, False),
        "go": (logic.cmd_go, True), "sent": (logic.cmd_sent, True), "cancel": (logic.cmd_cancel, True),
        "firma": (logic.cmd_firma, True),
        "file": (logic.cmd_file, False), "voir": (logic.cmd_voir, True),
        "health": (logic.cmd_health, False),
    }
    for alias, name in logic.ALIASES.items():  # /queue = /file, /show = /voir, /rejects = /rejets, /company = /firma
        commands[alias] = commands[name]
    for name, (fn, takes) in commands.items():
        app.add_handler(CommandHandler(name, handler(fn, takes), filters=mine))
    app.add_handler(CommandHandler("pending", pending, filters=mine))
    app.add_handler(CommandHandler("rule", with_buttons(logic.cmd_rule_view, True), filters=mine))
    app.add_handler(CommandHandler("reply", with_buttons(logic.cmd_reply_view, True), filters=mine))  # V5
    app.add_handler(CommandHandler("lang", lang_command, filters=mine))
    app.add_handler(CallbackQueryHandler(button_handler(chat_id, user_id), pattern=BUTTON_PATTERN))
    app.add_handler(MessageHandler(mine & filters.COMMAND, handler(lambda: t("bot.unknown_command"), False)))
    app.add_handler(MessageHandler(~allowed, ignore_stranger))
    return app


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # its INFO lines contain the bot token in URLs
    secrets = common.load_secrets()
    token, chat_id = secrets.get("TELEGRAM_TOKEN"), secrets.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id or not chat_id.lstrip("-").isdigit():
        log.error("TELEGRAM_TOKEN / TELEGRAM_CHAT_ID missing or invalid in %s", common.secrets_path())
        return 1
    user_id = (secrets.get("TELEGRAM_USER_ID") or "").strip() or None
    if user_id and not user_id.isdigit():  # never fall back to "everyone in the chat" on a typo
        log.error("TELEGRAM_USER_ID is not a numeric Telegram user id in %s", common.secrets_path())
        return 1
    if chat_id.startswith("-") and not user_id:
        log.warning("TELEGRAM_CHAT_ID is a group or channel and TELEGRAM_USER_ID is not set: "
                    "every member of that chat can command the bot")
    os.environ.pop("CLAUDE_CODE_OAUTH_TOKEN", None)  # the bot never calls Claude itself; run_scan.sh loads it
    app = build(token, chat_id, user_id)
    log.info("JobBot bot started for chat %s%s", chat_id, f", user {user_id}" if user_id else "")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
