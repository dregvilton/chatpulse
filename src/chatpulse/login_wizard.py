"""Terminal prompts with clear feedback and no input history."""
from __future__ import annotations

import re

from prompt_toolkit import PromptSession
from prompt_toolkit.history import DummyHistory
from prompt_toolkit.validation import Validator


def validator(pattern: str, message: str) -> Validator:
    regex = re.compile(pattern)
    return Validator.from_callable(
        lambda text: regex.fullmatch(text.strip()) is not None,
        error_message=message,
        move_cursor_to_end=True,
    )


class LoginWizard:
    def __init__(self) -> None:
        # DummyHistory disables up-arrow recovery, including secret inputs.
        self.session: PromptSession[str] = PromptSession(history=DummyHistory())

    def application(self, *, qr: bool = False) -> tuple[int, str, str | None]:
        print("\nChatPulse - Telegram authorization")
        print("Step 1 of 3: application credentials")
        print("Open https://my.telegram.org/apps for your own API credentials.")
        api_id = self.session.prompt(
            "  API ID: ", validator=validator(r"[1-9][0-9]*", "Positive number required"),
            validate_while_typing=False,
        ).strip()
        api_hash = self.session.prompt(
            "  API hash (shown as *): ", is_password=True,
            validator=validator(r"[a-fA-F0-9]{32}", "Expected 32 hexadecimal characters"),
            validate_while_typing=False,
        ).strip()
        print("  Application credential format accepted.")
        if qr:
            return int(api_id), api_hash, None
        print("\nStep 2 of 3: account")
        print("Your input will appear as * characters. Press Enter once.")
        phone = self.session.prompt(
            "  Phone (international format, shown as *): ", is_password=True,
            validator=validator(r"\+[1-9][0-9]{7,14}", "Expected +countrycode and digits"),
            validate_while_typing=False,
        ).strip()
        print("  Account format accepted.")
        return int(api_id), api_hash, phone

    async def code(self) -> str:
        return (await self.session.prompt_async(
            "  One-time login code (shown as *): ", is_password=True,
            validator=validator(r"[0-9]{4,8}", "Expected 4-8 digits"),
            validate_while_typing=False,
        )).strip()

    async def password(self) -> str:
        return await self.session.prompt_async(
            "  Two-step password (shown as *): ", is_password=True,
            validator=Validator.from_callable(bool, error_message="Cannot be empty"),
            validate_while_typing=False,
        )
