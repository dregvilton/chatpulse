"""Interactive Telegram *user* authentication; no persisted session file.

The only real network connections in this module are to Telegram via Telethon.
This module does not read dialogs/messages, and does not contact any LLM.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from chatpulse.credentials import CredentialVault, TelegramCredentials


class TelegramAuthError(RuntimeError):
    pass


def _make_client(api_id: int, api_hash: str, session: str) -> Any:
    from telethon import TelegramClient
    from telethon.sessions import StringSession

    client = TelegramClient(
        StringSession(session), api_id, api_hash,
        receive_updates=False, catch_up=False, auto_reconnect=False,
    )
    client.session.save_entities = False
    return client


async def login(
    vault: CredentialVault,
    *,
    api_id: int,
    api_hash: str,
    phone: str,
    prompt_code: Callable[[], Awaitable[str]],
    prompt_password: Callable[[], Awaitable[str]],
    client_factory: Callable[[int, str, str], Any] = _make_client,
    on_progress: Callable[[str], None] | None = None,
) -> None:
    """Only persist the session *after* Telegram confirms authorization."""
    import re

    if vault.load() is not None:
        raise TelegramAuthError("A Telegram session already exists")
    if not re.fullmatch(r"\+[1-9][0-9]{7,14}", phone):
        raise TelegramAuthError("Expected a phone number in +countrycode format")
    if type(api_id) is not int or api_id <= 0 or not re.fullmatch(r"[0-9a-fA-F]{32}", api_hash):
        raise TelegramAuthError("Invalid Telegram API credentials format")

    # No .session SQLite file: all mutable Telethon session state lives in memory.
    client = client_factory(api_id, api_hash, "")
    try:
        await client.connect()
        if on_progress is not None:
            on_progress("connected")
        sent = await client.send_code_request(phone)
        if on_progress is not None:
            on_progress("code_sent")
        code = await prompt_code()
        if on_progress is not None:
            on_progress("verifying")
        try:
            await client.sign_in(
                phone=phone, code=code, phone_code_hash=sent.phone_code_hash
            )
        except Exception as exc:
            from telethon.errors import SessionPasswordNeededError

            if not isinstance(exc, SessionPasswordNeededError):
                raise
            await client.sign_in(password=await prompt_password())
        if not await client.is_user_authorized():
            raise TelegramAuthError("Telegram did not authorize this session")
        if on_progress is not None:
            on_progress("storing")
        session = client.session.save()
        if not session:
            raise TelegramAuthError("No session was returned")
        try:
            vault.save_new(TelegramCredentials(api_id, api_hash, session))
        except Exception:
            # A successful Telegram login without durable secret storage
            # would strand an active, untracked authorization. Revoke it.
            try:
                await client.log_out()
            except Exception:
                # Remote revocation may fail; CLI instructs user to use
                # Telegram Settings > Devices instead of claiming success.
                pass
            raise
    finally:
        await client.disconnect()


async def revoke(
    vault: CredentialVault,
    *,
    client_factory: Callable[[int, str, str], Any] = _make_client,
) -> bool:
    """Revoke remotely first, erase vault only after successful Telegram response.

    On a network failure, retain the credential and explain in the CLI that
    device revocation is still required. Never claim that local deletion alone
    revokes a Telegram authorization.
    """
    creds = vault.load()
    if creds is None:
        return False
    client = client_factory(creds.api_id, creds.api_hash, creds.session)
    try:
        await client.connect()
        if not await client.log_out():
            raise TelegramAuthError("Telegram did not confirm revocation")
        vault.forget()
        return True
    finally:
        await client.disconnect()
