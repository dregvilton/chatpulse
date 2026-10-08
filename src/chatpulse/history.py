"""Read only an explicitly authorized chat's time-bounded text history."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, AsyncIterator, Protocol
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
                          max_messages: int = 5000) -> list[RawMessage]:
    """Caller supplies an authenticated client. No chat discovery or media downloads."""
    if type(chat_id) is not int or chat_id not in allowed_chat_ids:
        raise PermissionError("Chat is not allowlisted")
    if not 1 <= max_messages <= 10000:
        raise ValueError("Invalid max_messages")
    output: list[RawMessage] = []
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
        if not isinstance(text, str) or not text.strip():
            continue
        if len(output) >= max_messages:
            raise ValueError("Message limit exceeded; refusing partial digest")
        output.append(RawMessage(sender_id=getattr(item, "sender_id", None),
                                 sender_name=None, sent_at=when, text=text))
    output.reverse()
    return output

async def collect_safe_history(client: HistoryClient, *, chat_id: int,
                               allowed_chat_ids: frozenset[int], window: DigestWindow,
                               timezone_name: str = DEFAULT_TIMEZONE,
                               max_messages: int = 5000) -> list[SafeMessage]:
    raw = await collect_history(client, chat_id=chat_id, allowed_chat_ids=allowed_chat_ids,
                                window=window, max_messages=max_messages)
    return sanitize_messages(raw, timezone=timezone_name)
