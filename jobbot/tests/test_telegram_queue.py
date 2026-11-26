import json
import os

from _env import FakeTelegram, JobbotTestCase
import telegram_send as tg


class Outbox(JobbotTestCase):
    def setUp(self):
        super().setUp()
        self.fake = FakeTelegram()
        self.addCleanup(self.fake.close)
        os.environ.update({"TELEGRAM_TOKEN": "t", "TELEGRAM_CHAT_ID": "42", "JOBBOT_NOW": "2026-11-24T08:00:00Z"})

    def down(self):
        os.environ["JOBBOT_TELEGRAM_API"] = self.fake.down_url

    def up(self):
        os.environ["JOBBOT_TELEGRAM_API"] = self.fake.url

    def queue(self):
        return [json.loads(l) for l in tg.queue_path().read_text().splitlines()] if tg.queue_path().exists() else []

    def test_unreachable_then_delivered_in_order_after_next_success(self):
        self.down()
        self.assertIsNone(tg.send("first"))
        self.assertIsNone(tg.send("second"))
        self.assertEqual([e["text"] for e in self.queue()], ["first", "second"])
        self.up()
        self.assertIsNotNone(tg.send("third"))
        texts = self.fake.texts()
        self.assertEqual(texts[0], "third")
        self.assertTrue(texts[1].startswith("<i>(différé — prévu le 24/11 09:00)</i>\nfirst"))
        self.assertTrue(texts[2].endswith("second"))
        self.assertEqual(self.queue(), [])

    def test_retryable_http_errors_are_queued(self):
        self.up()
        for status in (401, 403, 500):
            self.fake.statuses = [status]
            self.assertIsNone(tg.send(f"m{status}"))
        self.assertEqual([e["text"] for e in self.queue()], ["m401", "m403", "m500"])

    def test_invalid_message_is_dropped_not_queued(self):
        self.up()
        self.fake.statuses = [400]
        self.assertIsNone(tg.send("<b>broken"))
        self.assertEqual(self.queue(), [])
        self.assertIn("broken", (self.tmp / "state" / "telegram_dropped.log").read_text())

    def test_missing_credentials_are_queued(self):
        os.environ.pop("TELEGRAM_TOKEN")
        self.assertIsNone(tg.send("later"))
        self.assertEqual(len(self.queue()), 1)

    def test_flush_stops_at_first_failure_and_keeps_the_rest(self):
        self.down()
        for i in range(3):
            tg.send(f"q{i}")
        self.up()
        self.fake.statuses = [200, 200, 503]  # current message, q0, then q1 fails
        tg.send("now")
        self.assertEqual([e["text"] for e in self.queue()], ["q1", "q2"])

    def test_overflow_drops_oldest_and_reports_it(self):
        old = tg.QUEUE_MAX
        tg.QUEUE_MAX = 2
        self.addCleanup(setattr, tg, "QUEUE_MAX", old)
        self.down()
        for i in range(4):
            tg.send(f"q{i}")
        self.assertEqual([e["text"] for e in self.queue()], ["q2", "q3"])
        self.up()
        tg.send("back")
        texts = self.fake.texts()
        self.assertIn("2 message(s) ancien(s) perdu(s)", texts[1])
        self.assertTrue(texts[2].endswith("q2"))

    def test_dry_run_prefix_is_kept_in_queue(self):
        os.environ["JOBBOT_DRY_RUN"] = "1"
        self.down()
        tg.send("x")
        self.assertEqual(self.queue()[0]["text"], "[TEST] x")


class TransportSelection(JobbotTestCase):
    """The file:// transport is test-only: it must activate only on an explicit file:// URL."""

    def setUp(self):
        super().setUp()
        import urllib.error
        import urllib.request

        self.http_calls, self.file_calls = [], []
        real_urlopen, real_file = urllib.request.urlopen, tg._file_transport

        def fake_urlopen(req, *a, **kw):
            self.http_calls.append(req.full_url)
            raise urllib.error.URLError("network disabled in tests")

        def spy_file(*args, **kwargs):
            self.file_calls.append(args[0])
            return real_file(*args, **kwargs)

        urllib.request.urlopen = fake_urlopen
        tg._file_transport = spy_file
        self.addCleanup(setattr, urllib.request, "urlopen", real_urlopen)
        self.addCleanup(setattr, tg, "_file_transport", real_file)

    def test_default_is_the_real_telegram_api_never_the_file_transport(self):
        os.environ.pop("JOBBOT_TELEGRAM_API", None)
        self.assertEqual(tg.api_base(), "https://api.telegram.org")
        outcome, _, _ = tg.api_request("getMe", {}, "123:abc", retries=False)
        self.assertEqual(outcome, tg.RETRYABLE)
        self.assertEqual(self.http_calls, ["https://api.telegram.org/bot123:abc/getMe"])
        self.assertEqual(self.file_calls, [])

    def test_only_a_file_url_prefix_activates_it(self):
        for url in ("http://localhost/x", "https://example.invalid", "FILE:///tmp/x", " file:///tmp/x", "/tmp/file://x"):
            with self.subTest(url=url):
                os.environ["JOBBOT_TELEGRAM_API"] = url
                self.http_calls.clear()
                self.file_calls.clear()
                tg.api_request("getMe", {}, "t", retries=False)
                self.assertEqual(self.file_calls, [], url)
        fake = FakeTelegram()
        self.addCleanup(fake.close)
        os.environ["JOBBOT_TELEGRAM_API"] = fake.url
        self.http_calls.clear()
        outcome, body, _ = tg.api_request("getMe", {}, "t", retries=False)
        self.assertEqual((outcome, self.http_calls), (tg.OK, []))
        self.assertEqual(self.file_calls, [str(fake.dir)])
        self.assertEqual(body["result"]["username"], "jobbot_test_bot")
