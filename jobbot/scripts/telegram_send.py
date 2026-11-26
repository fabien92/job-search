#!/usr/bin/env python3
"""Telegram Bot API sender (stdlib only; used by scripts — the bot process has its own client).

    jobbot/.venv/bin/python jobbot/scripts/telegram_send.py "texte HTML"

HTML parse mode: every untrusted value goes through esc(); links via link().
JOBBOT_DRY_RUN=1 prefixes "[TEST] ". JOBBOT_TELEGRAM_API overrides the API base
(tests point it at a local server). A Telegram outage must never fail a scan.

Outbox (jobbot/state/telegram_queue.jsonl): a message that cannot be delivered
(network error, 5xx, 429 after retries, 401/403, missing credentials) is queued
and re-sent, oldest first, right after the next successful send. A 400 (the
message itself is invalid) is never queued: it would fail forever; it goes to
telegram_dropped.log. The queue holds at most QUEUE_MAX entries; overflow drops
the oldest and the next flush says how many were lost. Own lock (.telegram.lock),
never nested with the state lock.
"""

from __future__ import annotations

import html
import http.client
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request

import common
from i18n import t

MAX_LEN = 4000
QUEUE_MAX = 200
OK, RETRYABLE, PERMANENT = "ok", "retryable", "permanent"
SENT, QUEUED, DROPPED = "sent", "queued", "dropped"  # send_status(): what became of the message


def redact(text, token: str | None) -> str:
    """Error texts end up in logs and in the outbox file: the bot token never does."""
    text = str(text)
    return text.replace(token, "<token>") if token else text


def esc(value) -> str:
    return html.escape(str(value if value is not None else ""), quote=False)


def link(url: str, label: str | None = None) -> str:
    """A clickable link (SPEC §0.6). Only http(s) URLs become links."""
    if not isinstance(url, str) or not url.lower().startswith(("http://", "https://")):
        return esc(label or url)
    return f'<a href="{html.escape(url, quote=True)}">{esc(label or url)}</a>'


def api_base() -> str:
    return os.environ.get("JOBBOT_TELEGRAM_API", "https://api.telegram.org").rstrip("/")


def _retry_delay(seconds: float) -> None:
    factor = float(os.environ.get("JOBBOT_TELEGRAM_RETRY_DELAY", "1"))
    if factor > 0:
        time.sleep(seconds * factor)


def _ssl_context() -> ssl.SSLContext:
    """certifi's CA bundle when present: a python.org Python ships no system CA store
    until "Install Certificates.command" is run, and every HTTPS call then fails."""
    try:
        import certifi  # in jobbot/.venv (dependency of python-telegram-bot)

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


FILE_SCHEME = "file://"


def _file_transport(directory: str, method: str, payload: dict, files: dict | None = None):
    """TEST-ONLY transport, active only when JOBBOT_TELEGRAM_API starts with file:// (never by
    default): no socket, so the tests run inside the Claude Code sandbox, which forbids binding a
    local port. Each request is appended to <dir>/requests.jsonl; the reply status is popped from
    <dir>/statuses.json (default 200; 0 = unreachable). A missing <dir> means "unreachable"."""
    from pathlib import Path

    root = Path(directory)
    if not root.is_dir():
        return RETRYABLE, None, f"file transport: {root} unreachable"
    with common.file_lock(root / ".lock", timeout=10):
        statuses_path = root / "statuses.json"
        statuses = json.loads(statuses_path.read_text(encoding="utf-8")) if statuses_path.exists() else []
        status = statuses.pop(0) if statuses else 200
        statuses_path.write_text(json.dumps(statuses), encoding="utf-8")
        if status == 0:
            return RETRYABLE, None, "file transport: simulated network error"
        if status != 200:
            body = {"ok": False, "error_code": status, "description": f"fake error {status}"}
            return (PERMANENT if status == 400 else RETRYABLE), body, f"HTTP {status} fake error {status}"
        record = {"method": method, "payload": payload}
        if files:
            record["files"] = {field: {"filename": name, "size": len(data)} for field, (name, data) in files.items()}
        with open(root / "requests.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        with open(root / "requests.jsonl", encoding="utf-8") as fh:
            count = sum(1 for _ in fh)
    if method == "getMe":
        result = {"username": "jobbot_test_bot"}
    elif method == "deleteMessage":
        result = True
    else:
        result = {"message_id": 1000 + count}
    return OK, {"ok": True, "result": result}, None


def _multipart(payload: dict, files: dict) -> tuple[bytes, str]:
    """multipart/form-data body (stdlib only). files: {field: (filename, bytes)}."""
    import uuid

    boundary = "jobbot" + uuid.uuid4().hex
    out = bytearray()
    for key, value in payload.items():
        value = value if isinstance(value, str) else json.dumps(value)
        out += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"\r\n\r\n").encode()
        out += value.encode("utf-8") + b"\r\n"
    for field, (filename, data) in files.items():
        safe = filename.replace('"', "").replace("\r", "").replace("\n", "")
        out += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{field}\"; filename=\"{safe}\"\r\n"
                f"Content-Type: application/pdf\r\n\r\n").encode("utf-8")
        out += data + b"\r\n"
    out += f"--{boundary}--\r\n".encode()
    return bytes(out), f"multipart/form-data; boundary={boundary}"


def api_request(method: str, payload: dict, token: str, *, retries: bool = True, timeout: float = 20,
                files: dict | None = None):
    """-> (outcome, response_json | None, error_text). outcome: ok | retryable | permanent.
    files: {field: (filename, bytes)} sends multipart/form-data (sendDocument)."""
    base = api_base()
    if base.startswith(FILE_SCHEME):
        return _file_transport(base[len(FILE_SCHEME):], method, payload, files)
    url = f"{base}/bot{token}/{method}"
    if files:
        data, ctype = _multipart(payload, files)
        timeout = max(timeout, 60)
    else:
        data, ctype = json.dumps(payload).encode("utf-8"), "application/json"
    attempts = 4 if retries else 1
    error = "unknown error"
    for attempt in range(attempts):
        try:
            req = urllib.request.Request(url, data=data, headers={"Content-Type": ctype})
        except ValueError as exc:  # malformed JOBBOT_TELEGRAM_API: queue, never crash a scan
            return RETRYABLE, None, redact(f"invalid Telegram API URL: {exc}", token)
        try:
            ctx = _ssl_context() if url.startswith("https") else None
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                if not isinstance(body, dict):
                    raise ValueError("unexpected reply")
                return (OK if body.get("ok") else PERMANENT), body, None
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", "replace")
            try:
                info = json.loads(raw)
            except json.JSONDecodeError:
                info = {}
            if not isinstance(info, dict):
                info = {}
            error = redact(f"HTTP {exc.code} {info.get('description', raw[:200])}", token)
            retry_after = (info.get("parameters") or {}).get("retry_after")
            if exc.code == 429 and retry_after and attempt < attempts - 1:
                _retry_delay(min(int(retry_after), 30))
                continue
            if exc.code >= 500 and attempt < attempts - 1:
                _retry_delay(2 * (attempt + 1))
                continue
            return (PERMANENT if exc.code == 400 else RETRYABLE), info or None, error
        except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException, ValueError) as exc:
            # ValueError: a reply that is not JSON (proxy page); HTTPException: InvalidURL, IncompleteRead…
            error = redact(f"{type(exc).__name__}: {exc}", token)
            if attempt < min(attempts, 3) - 1:
                _retry_delay(2 * (attempt + 1))
                continue
            return RETRYABLE, None, error
    return RETRYABLE, None, error


def _chunks(text: str) -> list[str]:
    if len(text) <= MAX_LEN:
        return [text]
    parts, current = [], ""
    for line in text.split("\n"):
        if len(current) + len(line) + 1 > MAX_LEN and current:
            parts.append(current)
            current = ""
        current += (("\n" if current else "") + line)[:MAX_LEN]
    if current:
        parts.append(current)
    return parts


# ------------------------------------------------------------------ outbox

def queue_path():
    return common.state_dir() / "telegram_queue.jsonl"


def _meta_path():
    return common.state_dir() / "telegram_queue_meta.json"


def _lock():
    return common.file_lock(common.state_dir() / ".telegram.lock", timeout=60)


def _read_queue() -> list[dict]:
    path = queue_path()
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _write_queue(entries: list[dict]) -> None:
    common.atomic_write_text(queue_path(), "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries))


def queue_length() -> int:
    return len(_read_queue())


def _enqueue(chunks: list[str], reason: str) -> bool:
    """-> False when the outbox could not be written (lock held too long, disk): the chunks then go to
    telegram_dropped.log. Never raises: a Telegram problem must not fail the caller."""
    try:
        _enqueue_locked(chunks, reason)
        return True
    except (common.LockBusy, OSError, ValueError) as exc:
        for chunk in chunks:
            _drop(chunk, f"outbox unavailable ({type(exc).__name__}); {reason[:200]}")
        return False


def _enqueue_locked(chunks: list[str], reason: str) -> None:
    with _lock():
        entries = _read_queue()
        for chunk in chunks:
            entries.append({"text": chunk, "queued": common.iso(), "reason": reason[:200]})
        overflow = max(0, len(entries) - QUEUE_MAX)
        if overflow:
            entries = entries[overflow:]
            meta = _read_meta()
            meta["dropped"] = int(meta.get("dropped") or 0) + overflow
            common.atomic_write_json(_meta_path(), meta)
        _write_queue(entries)
    common.log(f"telegram: {len(chunks)} message(s) queued ({reason[:120]})")


def _read_meta() -> dict:
    try:
        meta = common.read_json(_meta_path(), {}) or {}
    except ValueError:
        return {}
    return meta if isinstance(meta, dict) else {}


def _drop(chunk: str, reason: str) -> None:
    try:
        with open(common.state_dir() / "telegram_dropped.log", "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"at": common.iso(), "reason": reason, "text": chunk[:500]}, ensure_ascii=False) + "\n")
    except OSError:
        pass
    common.log(f"telegram: message dropped ({reason})")


def _deferred_prefix(queued: str | None) -> str:
    when = common.parse_iso(queued)
    stamp = when.astimezone(common.tz()).strftime("%d/%m %H:%M") if when else "?"
    return t("telegram.deferred", when=stamp) + "\n"


def flush_queue(token: str, chat: str) -> int:
    """Send queued messages, oldest first, stopping at the first failure. Returns the number sent."""
    sent = 0
    with _lock():
        entries = _read_queue()
        meta = _read_meta()
        if not entries and not meta.get("dropped"):
            return 0
        if meta.get("dropped"):
            note = t("telegram.queue_full", n=meta['dropped'])
            outcome, _, _ = api_request("sendMessage", {"chat_id": chat, "text": note}, token, retries=False)
            if outcome == OK:
                meta["dropped"] = 0
                common.atomic_write_json(_meta_path(), meta)
        remaining = []
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict) or not isinstance(entry.get("text"), str):
                continue  # not a queue entry: skipped, and gone with the rewrite below
            text = _deferred_prefix(entry.get("queued")) + entry["text"]
            payload = {"chat_id": chat, "text": text[:MAX_LEN + 200], "parse_mode": "HTML", "disable_web_page_preview": True}
            outcome, _, error = api_request("sendMessage", payload, token, retries=False)
            if outcome == OK:
                sent += 1
            elif outcome == PERMANENT:
                _drop(entry["text"], f"deferred: {error}")
            else:
                remaining = entries[index:]
                break
        _write_queue(remaining)
    if sent:
        common.log(f"telegram: {sent} deferred message(s) delivered")
    return sent


def send(text: str, *, reply_to: int | None = None, secrets: dict | None = None,
         buttons: list[list[tuple[str, str]]] | None = None) -> int | None:
    """Send an HTML message to TELEGRAM_CHAT_ID. Returns the (first) message_id, or None if it was
    queued/dropped. On success, delivers the outbox afterwards. Never raises.
    buttons (V5): rows of (label, callback data) under the last chunk, handled by the bot; a queued
    message is delivered later without them (its text must name the equivalent commands)."""
    return send_status(text, reply_to=reply_to, secrets=secrets, buttons=buttons)[0]


def send_status(text: str, *, reply_to: int | None = None, secrets: dict | None = None,
                buttons: list[list[tuple[str, str]]] | None = None) -> tuple[int | None, str]:
    """send(), plus what became of the message: -> (message_id | None, SENT | QUEUED | DROPPED).
    DROPPED = neither delivered nor in the outbox (Telegram refused it, or the outbox is unavailable):
    the caller may retry later. Never raises: a Telegram problem must not fail a scan or a command."""
    token = None
    try:
        secrets = secrets if secrets is not None else common.load_secrets()
        token = secrets.get("TELEGRAM_TOKEN")
        return _send(text, reply_to, secrets, buttons)
    except Exception as exc:  # noqa: BLE001 — last resort, see the docstring
        common.log("telegram: send failed: " + redact(f"{type(exc).__name__}: {exc}", token))
        return None, DROPPED


def _send(text: str, reply_to, secrets: dict, buttons) -> tuple[int | None, str]:
    token, chat = secrets.get("TELEGRAM_TOKEN"), secrets.get("TELEGRAM_CHAT_ID")
    if common.dry_run():
        text = "[TEST] " + text
    chunks = _chunks(text)
    if not token or not chat:
        return None, (QUEUED if _enqueue(chunks, "TELEGRAM_TOKEN / TELEGRAM_CHAT_ID missing") else DROPPED)
    first = None
    for index, chunk in enumerate(chunks):
        payload = {"chat_id": chat, "text": chunk, "parse_mode": "HTML", "disable_web_page_preview": True}
        if reply_to and index == 0:
            payload["reply_parameters"] = {"message_id": reply_to, "allow_sending_without_reply": True}
        if buttons and index == len(chunks) - 1:
            payload["reply_markup"] = {"inline_keyboard": [[{"text": label, "callback_data": data} for label, data in row]
                                                           for row in buttons]}
        outcome, result, error = api_request("sendMessage", payload, token)
        if outcome == OK:
            if first is None:
                first = result["result"]["message_id"]
        elif outcome == PERMANENT:
            _drop(chunk, error or "rejected")
        else:
            queued = _enqueue(chunks[index:], error or "unreachable")
            return first, (SENT if first is not None else QUEUED if queued else DROPPED)
    if first is None:
        return None, DROPPED
    try:
        flush_queue(token, chat)
    except Exception as exc:  # noqa: BLE001 — LockBusy: another process is flushing; never lose the result
        if not isinstance(exc, common.LockBusy):
            common.log("telegram: outbox flush failed: " + redact(f"{type(exc).__name__}: {exc}", token))
    return first, SENT


# ------------------------------------------------------------------ files (V2: /go, /pending, /sent)

DELETE_WINDOW_HOURS = 48  # Bot API deleteMessage: "a message can only be deleted if it was sent less than 48 hours ago"


def send_document(path, filename: str, *, caption: str | None = None, reply_to: int | None = None,
                  secrets: dict | None = None) -> tuple[int | None, str | None]:
    """Send one file. -> (message_id, error). Files are never queued: the caller reports the failure
    and the user can use the /pending button to resend."""
    from pathlib import Path

    secrets = secrets if secrets is not None else common.load_secrets()
    token, chat = secrets.get("TELEGRAM_TOKEN"), secrets.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        return None, "TELEGRAM_TOKEN / TELEGRAM_CHAT_ID missing"
    try:
        data = Path(path).read_bytes()
    except OSError as exc:
        return None, t("telegram.unreadable", error=exc)
    payload = {"chat_id": str(chat)}
    if caption:
        payload["caption"] = (("[TEST] " if common.dry_run() else "") + caption)[:1000]
        payload["parse_mode"] = "HTML"
    if reply_to:
        payload["reply_parameters"] = {"message_id": int(reply_to), "allow_sending_without_reply": True}
    outcome, result, error = api_request("sendDocument", payload, token, files={"document": (filename, data)})
    if outcome == OK:
        return result["result"]["message_id"], None
    return None, error or t("telegram.send_refused")


def delete_message(message_id: int, sent_iso: str | None, *, secrets: dict | None = None) -> tuple[bool, str | None]:
    """-> (deleted, reason_if_not). Past the 48 h Bot API window nothing is attempted: the reason says
    so, and the caller tells the user to delete the message by hand."""
    sent = common.parse_iso(sent_iso)
    if sent is not None and (common.now() - sent).total_seconds() >= DELETE_WINDOW_HOURS * 3600:
        return False, t("telegram.too_old", hours=DELETE_WINDOW_HOURS)
    secrets = secrets if secrets is not None else common.load_secrets()
    token, chat = secrets.get("TELEGRAM_TOKEN"), secrets.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        return False, "TELEGRAM_TOKEN / TELEGRAM_CHAT_ID missing"
    outcome, result, error = api_request("deleteMessage", {"chat_id": str(chat), "message_id": int(message_id)},
                                         token, retries=False)
    if outcome == OK and result and result.get("result") is True:
        return True, None
    return False, error or t("telegram.delete_refused")


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print("usage: telegram_send.py <html text>", file=sys.stderr)
        return 2
    return 0 if send(" ".join(argv)) else 1


if __name__ == "__main__":
    sys.exit(main())
