"""Read only an explicitly authorized chat's time-bounded text history."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, AsyncIterator, Awaitable, Callable, Protocol
from zoneinfo import ZoneInfo
from chatpulse.privacy import RawMessage, SafeMessage, sanitize_messages

DEFAULT_TIMEZONE = "Asia/Yekaterinburg"

@dataclass(frozen=True, slots=True)
class DigestWindow:
    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise ValueError("Timezone-aware boundaries required")
        if not self.start < self.end <= self.start + timedelta(days=1):
            raise ValueError("Window must be positive and at most one day")

    def contains(self, when: datetime) -> bool:
        if when.tzinfo is None:
            raise ValueError("Naive message timestamp")
        return self.start <= when < self.end

def daily_window(day: date, *, timezone_name: str = DEFAULT_TIMEZONE,
                 from_time: time = time(7), to_time: time = time(18)) -> DigestWindow:
    if from_time.tzinfo or to_time.tzinfo:
        raise ValueError("Use timezone_name for local times")
    zone = ZoneInfo(timezone_name)
    return DigestWindow(datetime.combine(day, from_time, zone),
                        datetime.combine(day, to_time, zone))

class HistoryClient(Protocol):
    def iter_messages(self, entity: int, *, offset_date: datetime) -> AsyncIterator[Any]: ...

async def collect_history(client: HistoryClient, *, chat_id: int,
                          allowed_chat_ids: frozenset[int], window: DigestWindow,
                          max_messages: int = 5000,
                          media_describer: Callable[[Any], Awaitable[str | None]] | None = None,
                          media_sample_limit: int | None = None,
                          ) -> list[RawMessage]:
    """A selected-group-only read; media is opt-in and RAM-only via caller."""
    if type(chat_id) is not int or chat_id not in allowed_chat_ids:
        raise PermissionError("Chat is not allowlisted")
    if not 1 <= max_messages <= 10000:
        raise ValueError("Invalid max_messages")
    if media_sample_limit is not None and not 20 <= media_sample_limit <= 250:
        raise ValueError("Invalid media sample limit")
    output: list[RawMessage] = []
    # Telegram iterates newest-first. Visual work is only needed for
    # messages that can appear in the eventual last-N preview.
    newest_eligible = 0
    # Also cap non-text/service/media entries, not just collected text.
    scanned = 0
    scan_limit = min(20000, max_messages * 3)
    async for item in client.iter_messages(chat_id, offset_date=window.end.astimezone(timezone.utc)):
        scanned += 1
        if scanned > scan_limit:
            raise ValueError("Scan limit exceeded; refusing partial digest")
        when = getattr(item, "date", None)
        if not isinstance(when, datetime) or when.tzinfo is None:
            raise ValueError("Invalid Telegram timestamp")
        if when < window.start:
            break  # Telethon defaults to newest-first iteration.
        if not window.contains(when):
            continue
        text = getattr(item, "message", None)
        caption = text.strip() if isinstance(text, str) else ""
        # Don't recursively summarize earlier ChatPulse posts.
        if caption.startswith("⚡ CHATPULSE · ДАЙДЖЕСТ ⚡"):
            continue
        # Caller opts in to reading only supported image attachments.
        # Never download media from a non-approved Telegram group.
        if media_describer is not None and (
            media_sample_limit is None or newest_eligible < media_sample_limit
        ):
            note = await media_describer(item)
            if note:
                caption = f"{caption}\n{note}".strip() if caption else note
        if not caption:
            continue
        newest_eligible += 1
        if len(output) >= max_messages:
            raise ValueError("Message limit exceeded; refusing partial digest")
        message_id = getattr(item, "id", None)
        reply_id = getattr(item, "reply_to_msg_id", None)
        # Telethon may have a sender entity already cached with each message.
        # Read it in memory only: do NOT request contacts or fetch senders.
        sender = getattr(item, "sender", None)
        first = getattr(sender, "first_name", None)
        last = getattr(sender, "last_name", None)
        handle = getattr(sender, "username", None)
        name_candidates = [first, last, handle]
        if isinstance(first, str) and isinstance(last, str):
            name_candidates.append(f"{first} {last}")
        aliases = tuple(
            name.strip() for name in name_candidates
            if isinstance(name, str) and 2 <= len(name.strip()) <= 80
        )
        output.append(RawMessage(
            sender_id=getattr(item, "sender_id", None),
            sender_name=None, sent_at=when, text=caption,
            message_id=message_id if type(message_id) is int else None,
            reply_to_id=reply_id if type(reply_id) is int else None,
            sender_aliases=aliases,
        ))
    output.reverse()
    return output

async def collect_safe_history(client: HistoryClient, *, chat_id: int,
                               allowed_chat_ids: frozenset[int], window: DigestWindow,
                               timezone_name: str = DEFAULT_TIMEZONE,
                               max_messages: int = 5000,
                               media_describer: Callable[[Any], Awaitable[str | None]] | None = None,
                               media_sample_limit: int | None = None,
                               ) -> list[SafeMessage]:
    raw = await collect_history(
        client, chat_id=chat_id, allowed_chat_ids=allowed_chat_ids,
        window=window, max_messages=max_messages, media_describer=media_describer,
        media_sample_limit=media_sample_limit,
    )
    return sanitize_messages(raw, timezone=timezone_name)
