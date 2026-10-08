"""One-shot approved group selection and redacted, memory-only history preview.

No chat text or participant names are persisted or printed by these workflows.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from chatpulse.credentials import CredentialVault
from chatpulse.history import (
    DEFAULT_TIMEZONE, collect_safe_history, daily_window,
)
from chatpulse.selection import (
    GroupChoice, SelectedChatHistoryClient, discover_groups,
)
from chatpulse.telegram_auth import TelegramAuthError, _make_client


@dataclass(frozen=True, slots=True)
class PreviewStats:
    day: date
    messages: int
    participants: int
    first_time: str | None
    last_time: str | None
    window_finished: bool


def most_recent_completed_day(now: datetime | None = None) -> date:
    zone = ZoneInfo(DEFAULT_TIMEZONE)
    local = now.astimezone(zone) if now is not None else datetime.now(zone)
    if local.tzinfo is None:
        raise ValueError("Timezone-aware time is required")
    return local.date() if local.time().replace(tzinfo=None) >= time(18) else (
        local.date() - timedelta(days=1)
    )


async def approve_group(
    vault: CredentialVault,
    *,
    consent: bool,
    present_choices: Callable[[list[GroupChoice]], None],
    choose_number: Callable[[int], Awaitable[int]],
    client_factory: Callable[[int, str, str], Any] = _make_client,
) -> bool:
    """User opts into a bounded group list, then confirms one number.

    Dialog enumeration is prohibited until consent=True. No user/private
    chats or message text are included in the supplied group choices.
    """
    if not consent:
        return False
    creds = vault.load()
    if creds is None:
        raise TelegramAuthError("Authorize Telegram before choosing a group")
    client = client_factory(creds.api_id, creds.api_hash, creds.session)
    try:
        await asyncio.wait_for(client.connect(), timeout=45)
        if not await client.is_user_authorized():
            raise TelegramAuthError("Telegram session is no longer authorized")
        groups = await asyncio.wait_for(discover_groups(client), timeout=90)
        if not groups:
            return False
        present_choices(groups)
        choice = await choose_number(len(groups))
        if type(choice) is not int or not 1 <= choice <= len(groups):
            raise ValueError("Invalid group choice")
        vault.save_selected_chat(groups[choice - 1].selection)
        return True
    finally:
        await client.disconnect()


async def preview_selected_group(
    vault: CredentialVault,
    *,
    day: date | None = None,
    max_messages: int = 5000,
    client_factory: Callable[[int, str, str], Any] = _make_client,
    now: datetime | None = None,
) -> PreviewStats:
    """Count redacted messages for one group without emitting raw text."""
    selected = vault.load_selected_chat()
    if selected is None:
        raise TelegramAuthError("Select a group first")
    creds = vault.load()
    if creds is None:
        raise TelegramAuthError("Telegram account is not authorized")
    zone = ZoneInfo(DEFAULT_TIMEZONE)
    local_now = now.astimezone(zone) if now is not None else datetime.now(zone)
    target_day = day if day is not None else most_recent_completed_day(local_now)
    if type(target_day) is not date or target_day > local_now.date():
        raise ValueError("Date must be today or earlier")
    window = daily_window(target_day)
    client = client_factory(creds.api_id, creds.api_hash, creds.session)
    try:
        await client.connect()
        if not await client.is_user_authorized():
            raise TelegramAuthError("Telegram session is no longer authorized")
        safe = await asyncio.wait_for(
            collect_safe_history(
                SelectedChatHistoryClient(client, selected),
                chat_id=selected.peer_id, allowed_chat_ids=frozenset({selected.peer_id}),
                window=window, max_messages=max_messages,
            ),
            timeout=180,
        )
        return PreviewStats(
            day=target_day, messages=len(safe),
            participants=len({message.author for message in safe}),
            first_time=safe[0].time if safe else None,
            last_time=safe[-1].time if safe else None,
            window_finished=local_now >= window.end,
        )
    finally:
        await client.disconnect()
