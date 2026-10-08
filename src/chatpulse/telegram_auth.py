"""Interactive Telegram *user* authentication; no persisted session file.

The only real network connections in this module are to Telegram via Telethon.
This module does not read dialogs/messages, and does not contact any LLM.
"""
from __future__ import annotations

from collections.abc import Callable
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
    prompt_code: Callable[[], str],
    prompt_password: Callable[[], str],
    client_factory: Callable[[int, str, str], Any] = _make_client,
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
        sent = await client.send_code_request(phone)
        try:
            await client.sign_in(
                phone=phone, code=prompt_code(), phone_code_hash=sent.phone_code_hash
            )
        except Exception as exc:
            from telethon.errors import SessionPasswordNeededError

            if not isinstance(exc, SessionPasswordNeededError):
                raise
            await client.sign_in(password=prompt_password())
        if not await client.is_user_authorized():
            raise TelegramAuthError("Telegram did not authorize this session")
        session = client.session.save()
        if not session:
            raise TelegramAuthError("No session was returned")
        vault.save_new(TelegramCredentials(api_id, api_hash, session))
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
