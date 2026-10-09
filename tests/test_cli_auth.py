"""The CLI must never echo mock secrets or unexpectedly require a TTY."""
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
from unittest.mock import patch
import unittest

from chatpulse.cli import main


class CliTests(unittest.TestCase):
    def setUp(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory

        self.tempdir = TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        path = Path(self.tempdir.name) / "ratings.json"
        override = patch("chatpulse.ratings.rating_file_path", return_value=path)
        override.start()
        self.addCleanup(override.stop)

    def test_demo_and_doctor_without_network(self):
        output = StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(["doctor"]), 0)
            self.assertEqual(main(["demo"]), 0)
        self.assertIn("OK: loopback-only", output.getvalue())

    def test_preview_shows_counts_but_no_chat_text(self):
        from chatpulse.group_workflow import PreviewStats
        from datetime import date

        stats = PreviewStats(
            day=date(2026, 10, 8), messages=3, participants=2,
            first_time="07:15", last_time="16:00", window_finished=True,
        )
        output = StringIO()
        with patch("chatpulse.credentials.open_system_vault", return_value=object()):
            with patch("chatpulse.group_workflow.preview_selected_group",
                       return_value=stats), redirect_stdout(output):
                self.assertEqual(main(["preview", "--date", "2026-10-08"]), 0)
        shown = output.getvalue()
        self.assertIn("Text messages: 3", shown)
        self.assertIn("Participants (pseudonymized): 2", shown)
        self.assertNotIn("password", shown)
        self.assertNotIn("telegram secret", shown)

    def test_preview_accepts_local_start_end_flags(self):
        from datetime import date
        from chatpulse.group_workflow import PreviewStats

        result = PreviewStats(
            day=date(2026, 10, 8), messages=4, participants=2,
            first_time="18:00", last_time="19:00", window_finished=False,
            window_start="17:00", window_end="19:30",
        )
        with patch("chatpulse.credentials.open_system_vault", return_value=object()):
            with patch("chatpulse.group_workflow.preview_selected_group",
                       return_value=result) as fn:
                with redirect_stdout(StringIO()):
                    self.assertEqual(
                        main(["preview", "--date", "2026-10-08",
                              "--from-time", "17:00", "--to-time", "19:30"]), 0
                    )
        self.assertEqual(fn.call_args.kwargs["from_time"].hour, 17)
        self.assertEqual(fn.call_args.kwargs["to_time"].minute, 30)

    def test_select_chat_refuses_non_tty_before_discovery(self):
        errors = StringIO()
        with patch("chatpulse.cli._interactive_only",
                   side_effect=RuntimeError("not a tty")), redirect_stderr(errors):
            self.assertEqual(main(["select-chat"]), 1)
        self.assertIn("Operation failed", errors.getvalue())

    def test_vision_extra_must_be_installed_before_telegram_read(self):
        import sys
        err = StringIO()
        with patch.dict(sys.modules, {"PIL": None}):
            with patch("chatpulse.group_workflow.read_selected_safe_history",
                       side_effect=AssertionError("Telegram should not be read")):
                with redirect_stderr(err):
                    rc = main([
                        "digest", "--model", "synthetic:8b",
                        "--vision-model", "qwen3-vl:4b",
                    ])
        self.assertEqual(rc, 1)
        self.assertIn("'.[vision]'", err.getvalue())
        self.assertIn("No Telegram history was read", err.getvalue())

    def test_ollama_http_error_displays_safe_diagnostic(self):
        from chatpulse.ollama_local import OllamaHTTPError

        stderr = StringIO()
        with patch("chatpulse.cli._digest_history",
                   side_effect=OllamaHTTPError(status=500, route="/api/chat")):
            with redirect_stderr(stderr):
                self.assertEqual(main(["digest", "--model", "synthetic:8b"]), 1)
        displayed = stderr.getvalue()
        self.assertIn("HTTP 500", displayed)
        self.assertIn("/api/chat", displayed)
        self.assertIn("server.log", displayed)
        self.assertNotIn("response body:", displayed)

    def test_digest_model_guard_happens_before_telegram(self):
        from chatpulse.ollama_local import LocalModelError

        stderr = StringIO()
        with patch("chatpulse.ollama_local.OllamaLocal.ensure_local",
                   side_effect=LocalModelError("secret test error")):
            with patch("chatpulse.group_workflow.read_selected_safe_history",
                       side_effect=AssertionError("Telegram must not be contacted")):
                with redirect_stderr(stderr):
                    self.assertEqual(main(["digest", "--model", "qwen3:4b"]), 1)
        self.assertNotIn("secret test error", stderr.getvalue())

    def test_digest_only_prints_local_summary_not_source_chat(self):
        from datetime import date
        from chatpulse.digest import DigestResult
        from chatpulse.privacy import SafeMessage

        async def fake_history(*args, **kwargs):
            from chatpulse.history import DigestWindow
            from datetime import datetime
            from zoneinfo import ZoneInfo
            local = ZoneInfo("Asia/Yekaterinburg")
            window = DigestWindow(
                datetime(2026, 10, 8, 7, tzinfo=local),
                datetime(2026, 10, 8, 19, tzinfo=local),
            )
            return window, False, [
                SafeMessage("Participant 1", "10:00", "PRIVATE CHAT DATA"),
            ]

        output = StringIO()
        with patch("chatpulse.ollama_local.OllamaLocal.ensure_local"):
            with patch("chatpulse.group_workflow.read_selected_safe_history",
                       side_effect=fake_history):
                with patch("chatpulse.credentials.open_system_vault",
                           return_value=object()):
                    with patch("chatpulse.digest.summarize_safe_messages",
                               return_value=DigestResult("Synthetic summary", 1, 1)):
                        with redirect_stdout(output):
                            self.assertEqual(
                                main(["digest", "--model", "qwen3:4b",
                                      "--date", "2026-10-08"]), 0
                            )
        self.assertIn("Synthetic summary", output.getvalue())
        self.assertIn("(07:00–19:00", output.getvalue())
        self.assertIn("Snapshot", output.getvalue())
        self.assertIn("Local preview only.", output.getvalue())
        self.assertNotIn("PRIVATE CHAT DATA", output.getvalue())

    def test_sample_digest_uses_last_messages_and_labels_partial_result(self):
        from datetime import date, datetime, time
        from zoneinfo import ZoneInfo
        from chatpulse.history import DigestWindow
        from chatpulse.digest import DigestResult
        from chatpulse.privacy import SafeMessage

        async def fake_history(*args, **kwargs):
            tz = ZoneInfo("Asia/Yekaterinburg")
            return (
                DigestWindow(
                    datetime(2026, 10, 8, 0, tzinfo=tz),
                    datetime(2026, 10, 9, 0, tzinfo=tz),
                ), True, [
                    SafeMessage("Participant 1", "08:00", f"SAFE {i}")
                    for i in range(30)
                ],
            )

        seen = []
        def fake_digest(messages, **kwargs):
            seen.extend(messages)
            return DigestResult("Synthetic sample", len(messages), 1)

        output = StringIO()
        with patch("chatpulse.ollama_local.OllamaLocal.ensure_local"):
            with patch("chatpulse.group_workflow.read_selected_safe_history",
                       side_effect=fake_history):
                with patch("chatpulse.credentials.open_system_vault",
                           return_value=object()):
                    with patch("chatpulse.digest.summarize_safe_messages",
                               side_effect=fake_digest):
                        with redirect_stdout(output):
                            self.assertEqual(main([
                                "digest", "--model", "qwen3:8b",
                                "--date", "2026-10-08",
                                "--sample-messages", "20",
                            ]), 0)
        self.assertEqual(len(seen), 20)
        self.assertEqual(seen[0].text, "SAFE 10")
        self.assertEqual(seen[-1].text, "SAFE 29")
        self.assertIn("TEST SAMPLE", output.getvalue())
        self.assertIn("NOT a full-day digest", output.getvalue())
        self.assertNotIn("SAFE 29", output.getvalue())

    def test_invalid_sample_refused_before_any_network_request(self):
        error = StringIO()
        with patch("chatpulse.ollama_local.OllamaLocal.ensure_local",
                   side_effect=AssertionError("must not contact Ollama")):
            with patch("chatpulse.group_workflow.read_selected_safe_history",
                       side_effect=AssertionError("must not contact Telegram")):
                with redirect_stderr(error):
                    self.assertEqual(main([
                        "digest", "--model", "qwen3:8b",
                        "--sample-messages", "1000",
                    ]), 1)
        self.assertIn("Operation failed", error.getvalue())

    def test_format_group_post_has_visible_header_and_escapes_html(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        from chatpulse.history import DigestWindow
        from chatpulse.cli import _format_group_post
        local = ZoneInfo("Asia/Yekaterinburg")
        window = DigestWindow(
            datetime(2026, 10, 9, 0, tzinfo=local),
            datetime(2026, 10, 9, 18, 15, tzinfo=local),
        )
        post = _format_group_post(
            digest="• **Пацаны:** хуй <script> & foo@example.com",
            window=window, message_count=142,
        )
        self.assertIn("⚡ <b>CHATPULSE · ДАЙДЖЕСТ</b> ⚡\n", post)
        self.assertIn("09.10.2026", post)
        self.assertIn("00:00–18:15", post)
        self.assertIn("• <b>Пацаны:</b> хуй &lt;script&gt; &amp; [email]", post)
        self.assertNotIn("foo@example.com", post)
        self.assertIn("142 сообщений", post)

    def test_publish_to_selected_peer_once_without_chat_discovery(self):
        import asyncio
        from chatpulse.cli import _send_group_post
        from chatpulse.selection import SelectedChat
        from telethon.tl.types import InputPeerChannel
        from unittest.mock import AsyncMock, Mock

        class StubVault:
            def load_selected_chat(self):
                return SelectedChat("megagroup", 123, 456)

            def load(self):
                from chatpulse.credentials import TelegramCredentials
                return TelegramCredentials(7, "a" * 32, "1" + "Q" * 100)

        client = Mock()
        client.connect = AsyncMock()
        client.disconnect = AsyncMock()
        client.is_user_authorized = AsyncMock(return_value=True)
        client.send_message = AsyncMock(return_value=object())
        with patch("chatpulse.telegram_auth._make_client", return_value=client):
            asyncio.run(_send_group_post(StubVault(), "<b>Fixture</b>"))
        client.send_message.assert_awaited_once()
        args, kwargs = client.send_message.await_args
        self.assertIsInstance(args[0], InputPeerChannel)
        self.assertEqual(args[0].channel_id, 123)
        self.assertEqual(args[1], "<b>Fixture</b>")
        self.assertEqual(kwargs["parse_mode"], "html")
        self.assertIs(kwargs["link_preview"], False)
        client.disconnect.assert_awaited_once()

    def test_send_sample_rejected_before_network_or_model_check(self):
        err = StringIO()
        with patch("chatpulse.ollama_local.OllamaLocal.ensure_local",
                   side_effect=AssertionError("unexpected model call")):
            with redirect_stderr(err):
                self.assertEqual(main([
                    "digest", "--model", "test:8b", "--sample-messages", "100",
                    "--send",
                ]), 1)
        self.assertIn("Operation failed", err.getvalue())

    def test_digest_send_posts_formatted_summary_once(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        from chatpulse.history import DigestWindow
        from chatpulse.digest import DigestResult
        from chatpulse.privacy import SafeMessage
        from unittest.mock import AsyncMock

        zone = ZoneInfo("Asia/Yekaterinburg")
        async def fake_history(*args, **kwargs):
            return DigestWindow(
                datetime(2026, 10, 9, 0, tzinfo=zone),
                datetime(2026, 10, 9, 12, tzinfo=zone),
            ), False, [SafeMessage("Participant 1", "10:00", "PRIVATE SOURCE")]

        delivery = AsyncMock()
        out = StringIO()
        with patch("chatpulse.ollama_local.OllamaLocal.ensure_local"):
            with patch("chatpulse.group_workflow.read_selected_safe_history",
                       side_effect=fake_history):
                with patch("chatpulse.credentials.open_system_vault",
                           return_value=object()):
                    with patch("chatpulse.digest.summarize_safe_messages",
                               return_value=DigestResult("• Реальная шутка", 1, 1)):
                        with patch("chatpulse.cli._send_group_post", delivery):
                            with redirect_stdout(out):
                                self.assertEqual(main([
                                    "digest", "--model", "test:8b", "--send",
                                ]), 0)
        delivery.assert_awaited_once()
        post = delivery.await_args.args[1]
        self.assertIn("Реальная шутка", post)
        self.assertNotIn("PRIVATE SOURCE", post)
        self.assertIn("Digest was published", out.getvalue())
        self.assertIn("Telegram publication was requested", out.getvalue())
        self.assertNotIn("No Telegram messages sent", out.getvalue())
        self.assertIn("chatpulse rate 1..5", out.getvalue())
        rated = StringIO()
        with redirect_stdout(rated):
            self.assertEqual(main(["rate", "4"]), 0)
        self.assertIn("saved locally", rated.getvalue())

    def test_review_send_publishes_once_only_after_explicit_send(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        from chatpulse.history import DigestWindow
        from chatpulse.digest import DigestResult
        from chatpulse.privacy import SafeMessage
        from unittest.mock import AsyncMock

        tz = ZoneInfo("Asia/Yekaterinburg")
        async def fake_history(*args, **kwargs):
            return (
                DigestWindow(datetime(2026, 10, 9, 0, tzinfo=tz),
                             datetime(2026, 10, 9, 18, tzinfo=tz)),
                False, [SafeMessage("Participant 1", "12:00", "PRIVATE SOURCE")],
            )

        for confirmation, expected_sends in (("", 0), ("yes", 0), ("SEND", 1)):
            with self.subTest(confirmation=confirmation):
                delivery = AsyncMock()
                output = StringIO()
                with (
                    patch("chatpulse.cli._interactive_only"),
                    patch("builtins.input", return_value=confirmation) as prompt,
                    patch("chatpulse.ollama_local.OllamaLocal.ensure_local"),
                    patch("chatpulse.group_workflow.read_selected_safe_history",
                          side_effect=fake_history) as history,
                    patch("chatpulse.credentials.open_system_vault",
                          return_value=object()),
                    patch("chatpulse.digest.summarize_safe_messages",
                          return_value=DigestResult("• Synthetic joke", 1, 1)) as digest,
                    patch("chatpulse.cli._send_group_post", delivery),
                    redirect_stdout(output),
                ):
                    self.assertEqual(main([
                        "digest", "--model", "test:8b", "--review-send",
                    ]), 0)
                prompt.assert_called_once()
                history.assert_awaited_once() if hasattr(history, "assert_awaited_once") else self.assertEqual(history.call_count, 1)
                digest.assert_called_once()
                self.assertEqual(delivery.await_count, expected_sends)
                if expected_sends:
                    self.assertIn("Synthetic joke", delivery.await_args.args[1])
                    self.assertIn("Digest was published", output.getvalue())
                else:
                    self.assertIn("Not published", output.getvalue())

    def test_vision_check_uses_synthetic_image_without_telegram(self):
        out = StringIO()
        with (
            patch("chatpulse.ollama_local.OllamaLocal.describe_image",
                  return_value="Синий квадрат и жёлтый круг") as vision,
            patch("chatpulse.group_workflow.read_selected_safe_history",
                  side_effect=AssertionError("Must not read Telegram")),
            redirect_stdout(out),
        ):
            self.assertEqual(main([
                "vision-check", "--model", "qwen3-vl:4b-instruct"
            ]), 0)
        vision.assert_called_once()
        kwargs = vision.call_args.kwargs
        self.assertEqual(kwargs["model"], "qwen3-vl:4b-instruct")
        self.assertEqual(kwargs["jpeg"][:2], bytes((255, 216)))
        self.assertIn("no Telegram access", out.getvalue())
        self.assertIn("preflight passed", out.getvalue())

    def test_vision_check_displays_only_fixed_reason_for_empty_response(self):
        from chatpulse.ollama_local import VisionDescriptionError
        err = StringIO()
        with (
            patch("chatpulse.ollama_local.OllamaLocal.describe_image",
                  side_effect=VisionDescriptionError("empty-description")),
            redirect_stderr(err),
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(main([
                "vision-check", "--model", "qwen3-vl:4b-instruct"
            ]), 1)
        self.assertIn("empty-description", err.getvalue())
        self.assertNotIn("raw image", err.getvalue())

    def test_review_send_rejects_partial_samples_before_any_network(self):
        err = StringIO()
        with patch("chatpulse.ollama_local.OllamaLocal.ensure_local",
                   side_effect=AssertionError("unexpected Ollama")), \
             patch("chatpulse.group_workflow.read_selected_safe_history",
                   side_effect=AssertionError("unexpected Telegram")), \
             redirect_stderr(err):
            self.assertEqual(main([
                "digest", "--model", "test:8b",
                "--sample-messages", "100", "--review-send",
            ]), 1)
        self.assertIn("Operation failed", err.getvalue())

    def test_rating_without_digest_is_non_network_operation(self):
        output = StringIO()
        with patch("chatpulse.ollama_local.OllamaLocal.ensure_local",
                   side_effect=AssertionError("no Ollama")):
            with redirect_stderr(output):
                self.assertEqual(main(["rate", "5"]), 1)
        self.assertIn("Rating failed", output.getvalue())

    def test_remote_doctor_rejected_without_printing_endpoint(self):
        err = StringIO()
        with redirect_stderr(err):
            self.assertEqual(main(["doctor", "--ollama-url", "http://192.168.1.2:11434"]), 1)
        self.assertNotIn("192.168.1.2", err.getvalue())

    def test_timeout_is_actionable_and_does_not_echo_secrets(self):
        err = StringIO()
        with patch("chatpulse.cli._login", side_effect=TimeoutError("private phone")):
            with redirect_stderr(err):
                self.assertEqual(main(["login"]), 1)
        self.assertIn("Telegram did not respond in time", err.getvalue())
        self.assertNotIn("private phone", err.getvalue())

    def test_errors_do_not_leak_exception_text(self):
        err = StringIO()
        with patch("chatpulse.credentials.open_system_vault",
                   side_effect=RuntimeError("mock secret +79991234567")), redirect_stderr(err):
            self.assertEqual(main(["status"]), 1)
        self.assertNotIn("+79991234567", err.getvalue())


if __name__ == "__main__":
    unittest.main()
