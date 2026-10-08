"""No real Telegram connections: test bounded group discovery and safe peers."""
import asyncio
from types import SimpleNamespace
import unittest

from telethon.tl.types import InputPeerChannel, InputPeerChat, InputPeerUser

from chatpulse.selection import (
    SelectedChat, SelectedChatHistoryClient, discover_groups, safe_terminal_title,
)


class FakeClient:
    def __init__(self, dialogs=()):
        self.dialogs = dialogs
        self.dialog_limits = []
        self.history_calls = []

    async def iter_dialogs(self, *, limit):
        self.dialog_limits.append(limit)
        for item in self.dialogs:
            yield item

    async def iter_messages(self, peer, *, offset_date):
        self.history_calls.append((peer, offset_date))
        for value in ():
            yield value


def dialog(title, peer, *, group=True):
    return SimpleNamespace(title=title, input_entity=peer, is_group=group)


class SelectionTests(unittest.TestCase):
    def test_group_only_and_minimal_peer_data(self):
        client = FakeClient([
            dialog("Alice (private)", InputPeerUser(11, 44), group=False),
            dialog("Broadcast", InputPeerChannel(66, 333), group=False),
            dialog("Old group", InputPeerChat(101)),
            dialog("Supergroup", InputPeerChannel(202, -987654)),
            dialog("Other person", InputPeerUser(9, 1000), group=True),
        ])
        groups = asyncio.run(discover_groups(client))
        self.assertEqual([x.title for x in groups], ["Old group", "Supergroup"])
        self.assertEqual([x.selection.kind for x in groups], ["group", "megagroup"])
        self.assertEqual(groups[0].selection.peer_id, 101)
        self.assertEqual(groups[1].selection.access_hash, -987654)
        self.assertEqual(client.dialog_limits, [200])
        self.assertNotIn("-987654", repr(groups[1].selection))

    def test_untrusted_titles_are_safe_in_terminal(self):
        self.assertEqual(safe_terminal_title("Hi\x1b[2J\u202e\nThere"), "Hi [2J There")
        self.assertEqual(len(safe_terminal_title("X" * 100)), 63)
        self.assertEqual(safe_terminal_title(" \t\n"), "(untitled group)")

    def test_invalid_peers_refused(self):
        with self.assertRaises(ValueError):
            SelectedChat("user", 123)
        with self.assertRaises(ValueError):
            SelectedChat("megagroup", 123)
        with self.assertRaises(ValueError):
            SelectedChat("group", 123, 500)
        with self.assertRaises(ValueError):
            SelectedChat("group", True)

    def test_direct_input_peer_avoids_access_hash_cache(self):
        old = SelectedChat("group", 101)
        mega = SelectedChat("megagroup", 202, -987654)
        self.assertIsInstance(old.input_peer(), InputPeerChat)
        peer = mega.input_peer()
        self.assertIsInstance(peer, InputPeerChannel)
        self.assertEqual(peer.access_hash, -987654)

        fake = FakeClient()
        wrapper = SelectedChatHistoryClient(fake, mega)
        with self.assertRaises(PermissionError):
            wrapper.iter_messages(101, offset_date=None)
        self.assertEqual(fake.history_calls, [])

        async def fetch():
            async for _ in wrapper.iter_messages(202, offset_date=None):
                pass

        asyncio.run(fetch())
        self.assertEqual(fake.history_calls[0][0].channel_id, 202)

    def test_discovery_limit_bound(self):
        with self.assertRaises(ValueError):
            asyncio.run(discover_groups(FakeClient(), max_dialogs=100000))
        with self.assertRaises(ValueError):
            asyncio.run(discover_groups(FakeClient(), max_groups=10000))


if __name__ == "__main__":
    unittest.main()
