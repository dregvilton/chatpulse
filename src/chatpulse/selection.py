"""Explicit, bounded group selection for a Telegram user account.

Only display names during an opt-in selection flow. Do not store them: names
can contain personal details and unsafe terminal escape sequences.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import unicodedata
from typing import Any


@dataclass(frozen=True, slots=True, repr=False)
class SelectedChat:
    """A single group InputPeer address, retained in the OS keyring."""

    kind: str
    peer_id: int
    access_hash: int | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.kind not in ("group", "megagroup"):
            raise ValueError("Only groups and megagroups can be selected")
        if type(self.peer_id) is not int or not 0 < self.peer_id < 2**63:
            raise ValueError("Invalid Telegram group ID")
        if self.kind == "group" and self.access_hash is not None:
            raise ValueError("Basic groups must not have an access hash")
        if self.kind == "megagroup" and (
            type(self.access_hash) is not int or not -(2**63) <= self.access_hash < 2**63
        ):
            raise ValueError("Megagroup requires a signed 64-bit access hash")

    def input_peer(self) -> Any:
        from telethon.tl.types import InputPeerChannel, InputPeerChat

        if self.kind == "group":
            return InputPeerChat(self.peer_id)
        return InputPeerChannel(self.peer_id, self.access_hash)


@dataclass(frozen=True, slots=True)
class GroupChoice:
    title: str
    selection: SelectedChat


def safe_terminal_title(value: str) -> str:
    """Render one short line without ANSI, bidi, newlines or control chars."""
    chars = []
    for character in value:
        if unicodedata.category(character) in ("Cc", "Cf", "Cs", "Zl", "Zp"):
            chars.append(" ")
        else:
            chars.append(character)
    name = " ".join("".join(chars).split())
    return (name[:60] + "..." if len(name) > 60 else name) or "(untitled group)"


async def discover_groups(
    client: Any, *, max_dialogs: int = 200, max_groups: int = 50
) -> list[GroupChoice]:
    """Opt-in only; caller must obtain explicit TTY consent before invocation.

    Telegram's dialog API may internally carry last-message previews, but this
    function never reads, displays, logs or saves their content.
    """
    from telethon.tl.types import InputPeerChannel, InputPeerChat

    if not 1 <= max_dialogs <= 200 or not 1 <= max_groups <= 50:
        raise ValueError("Discovery limit out of bounds")
    groups: list[GroupChoice] = []
    async for dialog in client.iter_dialogs(limit=max_dialogs):
        if not getattr(dialog, "is_group", False):
            continue
        peer = getattr(dialog, "input_entity", None)
        if isinstance(peer, InputPeerChat):
            selected = SelectedChat("group", peer.chat_id)
        elif isinstance(peer, InputPeerChannel):
            selected = SelectedChat("megagroup", peer.channel_id, peer.access_hash)
        else:
            continue
        title = safe_terminal_title(getattr(dialog, "title", "") or "")
        groups.append(GroupChoice(title, selected))
        if len(groups) >= max_groups:
            break
    return groups


class SelectedChatHistoryClient:
    """Bind numeric library IDs to an already-approved InputPeer."""

    def __init__(self, client: Any, selected: SelectedChat):
        self._client = client
        self._selected = selected

    def iter_messages(self, entity: int, *, offset_date: Any) -> Any:
        if type(entity) is not int or entity != self._selected.peer_id:
            raise PermissionError("History request is not for the approved group")
        return self._client.iter_messages(
            self._selected.input_peer(), offset_date=offset_date
        )
