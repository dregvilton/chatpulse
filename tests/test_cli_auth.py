"""The CLI must never echo mock secrets or unexpectedly require a TTY."""
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
from unittest.mock import patch
import unittest

from chatpulse.cli import main


class CliTests(unittest.TestCase):
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

    def test_select_chat_refuses_non_tty_before_discovery(self):
        errors = StringIO()
        with patch("chatpulse.cli._interactive_only",
                   side_effect=RuntimeError("not a tty")), redirect_stderr(errors):
            self.assertEqual(main(["select-chat"]), 1)
        self.assertIn("Operation failed", errors.getvalue())

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
            return date(2026, 10, 8), True, [
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
        self.assertNotIn("PRIVATE CHAT DATA", output.getvalue())

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
