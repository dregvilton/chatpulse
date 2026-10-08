"""Offline data minimization. Never forward raw Telegram objects to an LLM.

Pseudonymization is not guaranteed anonymization of free text.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import ipaddress
import re
from typing import Iterable
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

_EMAIL = re.compile(r"(?<![\w.])[^\s@<>]+@[^\s@<>]+\.[A-Za-z]{2,}")
_URL = re.compile(r"(?i)\b(?:https?://|www\.)[^\s<>]+")
_USERNAME = re.compile(r"(?<![\w])@[A-Za-z0-9_]{5,32}\b")
_PHONE = re.compile(r"(?<![\w])(?:\+?\d[\d\s().-]{7,}\d)(?![\w])")


@dataclass(frozen=True, slots=True)
class RawMessage:
    """Ephemeral local data; never serialize or log."""
    sender_id: int | None
    sender_name: str | None
    sent_at: datetime
    text: str


@dataclass(frozen=True, slots=True)
class SafeMessage:
    """Allowlisted model-facing fields."""
    author: str
    time: str
    text: str

    def as_payload(self) -> dict[str, str]:
        return {"author": self.author, "time": self.time, "text": self.text}


def redact_text(text: str, aliases: Iterable[str] = ()) -> str:
    result = _EMAIL.sub("[email]", text)
    result = _URL.sub("[link]", result)
    result = _USERNAME.sub("[username]", result)
    result = _PHONE.sub("[phone]", result)
    for alias in sorted(set(aliases), key=len, reverse=True):
        if len(alias.strip()) < 2:
            continue
        result = re.sub(
            rf"(?<!\w){re.escape(alias.strip())}(?!\w)",
            "[person]", result, flags=re.IGNORECASE,
        )
    return result


def sanitize_messages(
    messages: Iterable[RawMessage], *, timezone: str, aliases: Iterable[str] = ()
) -> list[SafeMessage]:
    zone = ZoneInfo(timezone)
    records = list(messages)
    alias_set = set(aliases)
    alias_set.update(m.sender_name for m in records if m.sender_name)
    participants: dict[int | None, str] = {}
    safe = []
    for message in records:
        if message.sent_at.tzinfo is None:
            raise ValueError("Messages must have timezone-aware timestamps")
        if message.sender_id not in participants:
            participants[message.sender_id] = f"Participant {len(participants) + 1}"
        safe.append(SafeMessage(
            author=participants[message.sender_id],
            time=message.sent_at.astimezone(zone).strftime("%H:%M"),
            text=redact_text(message.text, alias_set),
        ))
    return safe


def validate_ollama_url(url: str) -> str:
    """Only numeric loopback origins; revalidate at the HTTP adapter boundary."""
    parsed = urlsplit(url)
    if parsed.scheme != "http" or parsed.username or parsed.password:
        raise ValueError("Ollama requires unauthenticated HTTP on numeric loopback")
    if not parsed.hostname or parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise ValueError("Ollama URL must be a loopback origin with no path")
    try:
        address = ipaddress.ip_address(parsed.hostname)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Ollama requires a numeric loopback IP") from exc
    if not address.is_loopback or port is None or not 1 <= port <= 65535:
        raise ValueError("Ollama requires loopback IP and explicit valid port")
    return url
