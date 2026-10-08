"""Fake Telethon flows prove consent, vault selection and data minimization."""
import asyncio
from datetime import date, datetime, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from telethon.tl.types import InputPeerChannel, InputPeerChat

from chatpulse.credentials import CredentialVault, SecureStorageError, TelegramCredentials
from chatpulse.group_workflow import (
    approve_group, most_recent_completed_day, preview_selected_group,
)
from chatpulse.selection import SelectedChat
from tests.fakes import FakeKeyring


class FakeClient:
    def __init__(self):
        self.events = []
        self.dialogs = [
            SimpleNamespace(is_group=True, title="Synthetic Group",
                            input_entity=InputPeerChannel(555, -777)),
            SimpleNamespace(is_group=False, title="Private user",
                            input_entity=InputPeerChat(999)),
        ]
        self.messages = []
        self.allowed_peer = None

    async def connect(self):
        self.events.append("connect")

    async def disconnect(self):
        self.events.append("disconnect")

    async def is_user_authorized(self):
        self.events.append("authorize")
        return True

    async def iter_dialogs(self, *, limit):
        self.events.append(("dialogs", limit))
        for dialog in self.dialogs:
            yield dialog

    async def iter_messages(self, peer, *, offset_date):
        self.events.append("history")
        self.allowed_peer = peer
        for message in self.messages:
            yield message


def fake_msg(hour, content, sender):
    return SimpleNamespace(
        date=datetime(2026, 10, 8, hour, tzinfo=timezone.utc),
        message=content, sender_id=sender,
    )


class GroupWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.backend = FakeKeyring()
        with patch("chatpulse.credentials._is_trusted_backend", return_value=True):
            self.vault = CredentialVault(self.backend)
        self.vault.save_new(TelegramCredentials(123, "a" * 32, "1" + "Q" * 100))
        self.client = FakeClient()

    def factory(self, api_id, api_hash, session):
        self.assertEqual((api_id, api_hash), (123, "a" * 32))
        self.assertEqual(session, "1" + "Q" * 100)
        return self.client

    def test_no_consent_performs_no_telegram_calls(self):
        async def fail_select(limit):
            raise AssertionError("choice should never be requested")

        result = asyncio.run(approve_group(
            self.vault, consent=False,
            present_choices=lambda _: self.fail("should not list"),
            choose_number=fail_select, client_factory=self.factory,
        ))
        self.assertFalse(result)
        self.assertEqual(self.client.events, [])
        self.assertIsNone(self.vault.load_selected_chat())

    def test_selection_persisted_in_os_keyring_without_title(self):
        shown = []

        async def select_one(limit):
            self.assertEqual(limit, 1)
            return 1

        result = asyncio.run(approve_group(
            self.vault, consent=True, present_choices=shown.extend,
            choose_number=select_one, client_factory=self.factory,
        ))
        self.assertTrue(result)
        self.assertEqual(len(shown), 1)
        self.assertEqual(shown[0].title, "Synthetic Group")
        selected = self.vault.load_selected_chat()
        self.assertEqual(selected, SelectedChat("megagroup", 555, -777))
        stored = str(self.backend.entries)
        self.assertNotIn("Synthetic Group", stored)
        self.assertNotIn("Private user", stored)
        self.assertEqual(self.client.events[-1], "disconnect")

    def test_invalid_choice_not_stored(self):
        async def invalid(limit):
            return 0

        with self.assertRaises(ValueError):
            asyncio.run(approve_group(
                self.vault, consent=True,
                present_choices=lambda _: None, choose_number=invalid,
                client_factory=self.factory,
            ))
        self.assertIsNone(self.vault.load_selected_chat())
        self.assertEqual(self.client.events[-1], "disconnect")

    def test_preview_only_approved_group_pseudonymized_stats(self):
        self.vault.save_selected_chat(SelectedChat("megagroup", 555, -777))
        self.client.messages = [
            fake_msg(14, "after window", 3),
            fake_msg(12, "Maria's private message +79991112233", 88),
            fake_msg(9, "Всё норм, бля", 99),
            fake_msg(1, "before window", 88),
        ]
        stats = asyncio.run(preview_selected_group(
            self.vault, day=date(2026, 10, 8), client_factory=self.factory,
            now=datetime(2026, 10, 8, 14, tzinfo=timezone.utc),
        ))
        self.assertEqual(stats.messages, 2)
        self.assertEqual(stats.participants, 2)
        self.assertEqual((stats.first_time, stats.last_time), ("14:00", "17:00"))
        self.assertTrue(stats.window_finished)
        self.assertEqual(self.client.allowed_peer.channel_id, 555)
        self.assertEqual(self.client.allowed_peer.access_hash, -777)
        self.assertEqual(self.client.events[-1], "disconnect")

    def test_group_selection_cleared_after_logout(self):
        self.vault.save_selected_chat(SelectedChat("group", 101))
        self.vault.forget()
        self.assertIsNone(self.vault.load_selected_chat())
        self.assertEqual(self.backend.entries, {})

    def test_reauth_does_not_retain_previous_group(self):
        self.vault.save_selected_chat(SelectedChat("megagroup", 555, -777))
        self.backend.delete_password("chatpulse.telegram", "default")
        self.vault.save_new(TelegramCredentials(999, "b" * 32, "1" + "B" * 90))
        self.assertIsNone(self.vault.load_selected_chat())

    def test_preview_no_selection_fails_before_network(self):
        with self.assertRaises(Exception):
            asyncio.run(preview_selected_group(self.vault, client_factory=self.factory))
        self.assertEqual(self.client.events, [])

    def test_corrupt_selection_fails_closed(self):
        self.backend.entries[("chatpulse.telegram", "selected-group")] = "bad-json"
        with self.assertRaises(SecureStorageError):
            self.vault.load_selected_chat()

    def test_previous_full_window_default(self):
        self.assertEqual(
            most_recent_completed_day(datetime(2026, 10, 8, 10, tzinfo=timezone.utc)),
            date(2026, 10, 7),
        )
        self.assertEqual(
            most_recent_completed_day(datetime(2026, 10, 8, 13, tzinfo=timezone.utc)),
            date(2026, 10, 8),
        )


if __name__ == "__main__":
    unittest.main()
