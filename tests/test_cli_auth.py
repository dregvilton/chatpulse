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

    def test_remote_doctor_rejected_without_printing_endpoint(self):
        err = StringIO()
        with redirect_stderr(err):
            self.assertEqual(main(["doctor", "--ollama-url", "http://192.168.1.2:11434"]), 1)
        self.assertNotIn("192.168.1.2", err.getvalue())

    def test_errors_do_not_leak_exception_text(self):
        err = StringIO()
        with patch("chatpulse.credentials.open_system_vault",
                   side_effect=RuntimeError("mock secret +79991234567")), redirect_stderr(err):
            self.assertEqual(main(["status"]), 1)
        self.assertNotIn("+79991234567", err.getvalue())


if __name__ == "__main__":
    unittest.main()
