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
    DEFAULT_TIMEZONE, DigestWindow, collect_safe_history,
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
    window_start: str = "00:00"
    window_end: str = "00:00"


def resolve_window(
    *, day: date | None, now: datetime,
    from_time: time | None = None, to_time: time | None = None,
) -> DigestWindow:
    """Today is a snapshot until invocation; past days cover full calendar day.

    User-defined HH:MM boundaries are optional, not a fixed schedule.
    """
    if now.tzinfo is None:
        raise ValueError("Current time must include timezone")
    zone = ZoneInfo(DEFAULT_TIMEZONE)
    local_now = now.astimezone(zone)
    target = local_now.date() if day is None else day
    if type(target) is not date or target > local_now.date():
        raise ValueError("Cannot read a future date")
    if from_time is not None and from_time.tzinfo is not None:
        raise ValueError("Use local HH:MM start time without timezone offset")
    if to_time is not None and to_time.tzinfo is not None:
        raise ValueError("Use local HH:MM end time without timezone offset")
    start = datetime.combine(target, from_time or time.min, tzinfo=zone)
    if to_time is not None:
        end = datetime.combine(target, to_time, tzinfo=zone)
    elif target == local_now.date():
        end = local_now
    else:
        end = datetime.combine(target + timedelta(days=1), time.min, tzinfo=zone)
    if end > local_now:
        raise ValueError("Selected time window ends in the future")
    return DigestWindow(start, end)

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


async def read_selected_safe_history(
    vault: CredentialVault,
    *,
    day: date | None = None,
    from_time: time | None = None,
    to_time: time | None = None,
    max_messages: int = 5000,
    client_factory: Callable[[int, str, str], Any] = _make_client,
    now: datetime | None = None,
):
    """Only the approved group, only safe projections; no content printed."""
    selected = vault.load_selected_chat()
    if selected is None:
        raise TelegramAuthError("Select a group first")
    creds = vault.load()
    if creds is None:
        raise TelegramAuthError("Telegram account is not authorized")
    zone = ZoneInfo(DEFAULT_TIMEZONE)
    local_now = now.astimezone(zone) if now is not None else datetime.now(zone)
    window = resolve_window(
        day=day, now=local_now, from_time=from_time, to_time=to_time
    )
    client = client_factory(creds.api_id, creds.api_hash, creds.session)
    try:
        await asyncio.wait_for(client.connect(), timeout=45)
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
        return window, window.start.date() < local_now.date(), safe
    finally:
        await client.disconnect()


async def preview_selected_group(
    vault: CredentialVault,
    *,
    day: date | None = None,
    from_time: time | None = None,
    to_time: time | None = None,
    max_messages: int = 5000,
    client_factory: Callable[[int, str, str], Any] = _make_client,
    now: datetime | None = None,
) -> PreviewStats:
    """Count redacted messages for one group without emitting raw text."""
    window, finished, safe = await read_selected_safe_history(
        vault, day=day, from_time=from_time, to_time=to_time,
        max_messages=max_messages,
        client_factory=client_factory, now=now,
    )
    return PreviewStats(
        day=window.start.date(), messages=len(safe),
        participants=len({message.author for message in safe}),
        first_time=safe[0].time if safe else None,
        last_time=safe[-1].time if safe else None,
        window_finished=finished,
        window_start=window.start.strftime("%H:%M"),
        window_end=window.end.strftime("%H:%M") if window.end.date() == window.start.date() else "24:00",
    )
