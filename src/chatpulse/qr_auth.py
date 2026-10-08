"""QR authentication uses Telegram login tokens without SMS or phone prompts.

Tokens are short-lived login credentials. They are only rendered locally by the
CLI and must never be logged, uploaded, or written to disk.
"""
from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from typing import Any

from chatpulse.credentials import CredentialVault, TelegramCredentials
from chatpulse.telegram_auth import TelegramAuthError


def _make_qr_client(api_id: int, api_hash: str, session: str) -> Any:
    """Enable updates from construction for the QR approval event only."""
    from telethon import TelegramClient
    from telethon.sessions import StringSession

    client = TelegramClient(
        StringSession(session), api_id, api_hash,
        receive_updates=True, catch_up=False, auto_reconnect=False,
        connection_retries=1, request_retries=2, timeout=15,
    )
    client.session.save_entities = False
    return client


async def login_with_qr(
    vault: CredentialVault,
    *,
    api_id: int,
    api_hash: str,
    display_qr: Callable[[str], None],
    prompt_password: Callable[[], Awaitable[str]],
    client_factory: Callable[[int, str, str], Any] = _make_qr_client,
    on_progress: Callable[[str], None] | None = None,
    max_qr_attempts: int = 3,
) -> None:
    """Log in through Telegram's official in-app QR scan and OS keyring.

    Receiving updates is temporarily required for the QR acceptance event.
    No chat updates are recorded or persisted; catch-up remains disabled.
    """
    from telethon.errors import SessionPasswordNeededError

    if vault.load() is not None:
        raise TelegramAuthError("An authorization is already stored")
    if type(api_id) is not int or api_id <= 0 or not isinstance(api_hash, str):
        raise TelegramAuthError("Invalid API credentials")
    if re.fullmatch(r"[a-fA-F0-9]{32}", api_hash) is None:
        raise TelegramAuthError("Invalid API credentials")
    if not 1 <= max_qr_attempts <= 5:
        raise ValueError("Invalid QR attempt limit")

    client = client_factory(api_id, api_hash, "")
    try:
        if on_progress:
            on_progress("connecting")
        await asyncio.wait_for(client.connect(), timeout=45)
        # QRLogin.wait listens for Telegram's UpdateLoginToken.
        # Do not request missed message history or attach chat event handlers.
        # Updates are enabled at construction so QR acceptance is received.
        qr = await asyncio.wait_for(client.qr_login(), timeout=30)
        for attempt in range(max_qr_attempts):
            display_qr(qr.url)
            if on_progress:
                on_progress("qr_ready")
            try:
                await qr.wait()  # Telethon uses the token's short expiry.
            except asyncio.TimeoutError:
                if attempt == max_qr_attempts - 1:
                    raise TelegramAuthError("QR scan expired; please restart login") from None
                if on_progress:
                    on_progress("qr_expired")
                await qr.recreate()
                continue
            except SessionPasswordNeededError:
                if on_progress:
                    on_progress("password_required")
                await client.sign_in(password=await prompt_password())

            if not await client.is_user_authorized():
                raise TelegramAuthError("Telegram did not authorize this QR login")
            if on_progress:
                on_progress("storing")
            session = client.session.save()
            if not session:
                raise TelegramAuthError("No authorized session returned")
            try:
                vault.save_new(TelegramCredentials(api_id, api_hash, session))
            except Exception:
                try:
                    await client.log_out()
                except Exception:
                    # Caller must be told to revoke via Telegram Devices.
                    pass
                raise
            return
    finally:
        await client.disconnect()
