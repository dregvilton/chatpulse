"""Offline tests of wizard validation and secret-masking contracts."""
import asyncio
import io
from contextlib import redirect_stdout
from unittest.mock import patch
import unittest

from prompt_toolkit.document import Document
from prompt_toolkit.validation import ValidationError

from chatpulse.login_wizard import LoginWizard, validator


class MockPromptSession:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def prompt(self, message, **kwargs):
        self.calls.append((message, kwargs))
        return next(self.responses)

    async def prompt_async(self, message, **kwargs):
        self.calls.append((message, kwargs))
        return next(self.responses)


class WizardTests(unittest.TestCase):
    def test_validation_on_enter(self):
        check = validator(r"[a-fA-F0-9]{32}", "Expected hash")
        check.validate(Document("a" * 32))
        with self.assertRaises(ValidationError):
            check.validate(Document("invalid"))

    def test_masked_hash_phone_code_and_password(self):
        session = MockPromptSession(["123", "a" * 32, "+12345678901", "12345", "2fa-test"])
        with patch("chatpulse.login_wizard.PromptSession", return_value=session):
            wizard = LoginWizard()
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            api_id, api_hash, phone = wizard.application()
        self.assertEqual(api_id, 123)
        self.assertEqual(api_hash, "a" * 32)
        self.assertEqual(phone, "+12345678901")
        self.assertEqual(asyncio.run(wizard.code()), "12345")
        self.assertEqual(asyncio.run(wizard.password()), "2fa-test")
        for index in (1, 2, 3, 4):
            self.assertTrue(session.calls[index][1]["is_password"])
            self.assertFalse(session.calls[index][1]["validate_while_typing"])
        self.assertNotIn("a" * 32, stdout.getvalue())
        self.assertNotIn("+12345678901", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
