"""Fake Telethon flows prove consent, vault selection and data minimization."""
import asyncio
from datetime import date, datetime, time, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from telethon.tl.types import InputPeerChannel, InputPeerChat

from chatpulse.credentials import CredentialVault, SecureStorageError, TelegramCredentials
from chatpulse.group_workflow import (
    approve_group, resolve_window, preview_selected_group,
    read_selected_safe_history, image_kind,
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

    async def download_media(self, message, file=None, **kwargs):
        self.events.append("download")
        if file is not bytes:
            raise AssertionError("Media must download into memory")
        return b"synthetic image, no personal information"


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

    def test_real_pillow_conversion_stays_bounded_in_memory(self):
        from io import BytesIO
        from PIL import Image
        from chatpulse.group_workflow import prepare_image_jpeg

        original = Image.new("RGB", (1200, 800), (14, 40, 155))
        raw = BytesIO()
        original.save(raw, format="PNG")
        jpeg = prepare_image_jpeg(raw.getvalue())
        self.assertTrue(jpeg.startswith(bytes((255, 216))))
        self.assertLess(len(jpeg), 900_000)
        with Image.open(BytesIO(jpeg)) as check:
            self.assertLessEqual(check.width, 768)
            self.assertLessEqual(check.height, 768)
        with self.assertRaises(ValueError):
            prepare_image_jpeg(b"x" * 3_000_001)

    def test_media_classification_is_strict(self):
        jpeg = SimpleNamespace(photo=object(), sticker=None, gif=None, file=None)
        sticker = SimpleNamespace(photo=None, sticker=object(), gif=None,
                                  file=SimpleNamespace(mime_type="image/webp"))
        animated = SimpleNamespace(photo=None, sticker=object(), gif=None,
                                   file=SimpleNamespace(mime_type="application/x-tgsticker"))
        self.assertEqual(image_kind(jpeg), "фото")
        self.assertEqual(image_kind(sticker), "стикер")
        self.assertEqual(image_kind(animated), "анимированный стикер")
        self.assertIsNone(image_kind(SimpleNamespace()))

    def test_opt_in_photo_is_described_locally_and_links_replies(self):
        from unittest.mock import Mock
        self.vault.save_selected_chat(SelectedChat("megagroup", 555, -777))
        photo = fake_msg(12, "", 3)
        photo.id = 5501
        photo.reply_to_msg_id = None
        photo.photo = object()
        photo.file = SimpleNamespace(size=300, mime_type="image/jpeg")
        response = fake_msg(12, "Ахаха, норм картинка", 4)
        response.id = 5502
        response.reply_to_msg_id = 5501
        self.client.messages = [response, photo]  # newest first
        vision = Mock()
        vision.describe_image.return_value = "Мем про рыжего кота и компьютер"
        with patch("chatpulse.group_workflow.prepare_image_jpeg",
                   return_value=b"jpegbytes"):
            _, _, result = asyncio.run(read_selected_safe_history(
                self.vault, client_factory=self.factory,
                now=datetime(2026, 10, 8, 14, tzinfo=timezone.utc),
                vision_client=vision, vision_model="qwen3-vl:4b",
            ))
        self.assertEqual(len(result), 2)
        self.assertIn("[фото: Мем про рыжего кота", result[0].text)
        self.assertEqual(result[1].reply_to_turn, "m1")
        self.assertEqual(vision.ensure_local.call_count, 1)
        self.assertEqual(vision.describe_image.call_count, 1)
        self.assertIn("download", self.client.events)

    def test_visual_empty_completion_degrades_to_text_only(self):
        from chatpulse.ollama_local import VisionDescriptionError
        from unittest.mock import Mock

        self.vault.save_selected_chat(SelectedChat("megagroup", 555, -777))
        photos = []
        for i in range(3):
            pic = fake_msg(12, f"Текст про картинку {i}", i + 1)
            pic.photo = object()
            pic.file = SimpleNamespace(size=100, mime_type="image/jpeg")
            photos.append(pic)
        self.client.messages = photos
        vision = Mock()
        vision.describe_image.side_effect = VisionDescriptionError(
            "empty-description"
        )
        reasons = []
        with patch("chatpulse.group_workflow.prepare_image_jpeg",
                   return_value=b"jpegbytes"):
            _, _, safe = asyncio.run(read_selected_safe_history(
                self.vault, client_factory=self.factory,
                now=datetime(2026, 10, 8, 14, tzinfo=timezone.utc),
                vision_client=vision, vision_model="qwen3-vl:4b-instruct",
                on_vision_warning=reasons.append,
            ))
        self.assertEqual(len(safe), 3)
        self.assertEqual(self.client.events.count("download"), 1)
        self.assertEqual(vision.describe_image.call_count, 1)
        self.assertEqual(reasons, ["empty-description"])
        self.assertTrue(all("Текст про картинку" in msg.text for msg in safe))
        self.assertEqual(
            sum("описание недоступно" in msg.text for msg in safe), 1
        )
        self.assertEqual(
            sum("локальное описание временно недоступно" in msg.text
                for msg in safe), 2
        )
        self.assertNotIn("PRIVATE", str([m.text for m in safe]))

    def test_media_is_never_downloaded_without_opt_in(self):
        self.vault.save_selected_chat(SelectedChat("megagroup", 555, -777))
        pic = fake_msg(12, "", 3)
        pic.photo = object()
        pic.file = SimpleNamespace(size=100, mime_type="image/jpeg")
        self.client.messages = [pic, fake_msg(11, "Текст", 4)]
        _, _, safe = asyncio.run(read_selected_safe_history(
            self.vault, client_factory=self.factory,
            now=datetime(2026, 10, 8, 14, tzinfo=timezone.utc),
        ))
        self.assertEqual([x.text for x in safe], ["Текст"])
        self.assertNotIn("download", self.client.events)

    def test_visual_budget_does_not_download_excess_images(self):
        from unittest.mock import Mock
        self.vault.save_selected_chat(SelectedChat("megagroup", 555, -777))
        photos = []
        for i in range(3):
            pic = fake_msg(12, "", i + 1)
            pic.photo = object()
            pic.file = SimpleNamespace(size=100, mime_type="image/jpeg")
            photos.append(pic)
        self.client.messages = photos
        vision = Mock()
        vision.describe_image.return_value = "На фото кот"
        with patch("chatpulse.group_workflow.prepare_image_jpeg",
                   return_value=b"jpegbytes"):
            _, _, safe = asyncio.run(read_selected_safe_history(
                self.vault, client_factory=self.factory,
                now=datetime(2026, 10, 8, 14, tzinfo=timezone.utc),
                vision_client=vision, vision_model="qwen3-vl:4b",
                max_images=1,
            ))
        self.assertEqual(len(safe), 3)
        self.assertEqual(self.client.events.count("download"), 1)
        self.assertEqual(vision.describe_image.call_count, 1)
        self.assertEqual(sum("лимит" in x.text for x in safe), 2)

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
        self.assertEqual(stats.messages, 3)
        self.assertEqual(stats.participants, 2)
        self.assertEqual((stats.first_time, stats.last_time), ("06:00", "17:00"))
        self.assertFalse(stats.window_finished)
        self.assertEqual((stats.window_start, stats.window_end), ("00:00", "19:00"))
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

    def test_today_includes_messages_after_1800(self):
        self.vault.save_selected_chat(SelectedChat("megagroup", 555, -777))
        self.client.messages = [
            fake_msg(14, "19:00", 3),
            fake_msg(13, "18:00", 2),
            fake_msg(12, "17:00", 1),
        ]
        stats = asyncio.run(preview_selected_group(
            self.vault, day=date(2026, 10, 8), client_factory=self.factory,
            now=datetime(2026, 10, 8, 14, 45, tzinfo=timezone.utc),
            from_time=time(7),
        ))
        self.assertEqual(stats.messages, 3)
        self.assertEqual(stats.window_start, "07:00")
        self.assertEqual(stats.window_end, "19:45")

    def test_past_date_full_day_and_explicit_end(self):
        now = datetime(2026, 10, 9, 14, tzinfo=timezone.utc)
        window = resolve_window(day=date(2026, 10, 8), now=now)
        self.assertEqual(window.start.strftime("%Y-%m-%d %H:%M"),
                         "2026-10-08 00:00")
        self.assertEqual(window.end.strftime("%Y-%m-%d %H:%M"),
                         "2026-10-09 00:00")
        bounded = resolve_window(
            day=date(2026, 10, 8), now=now,
            from_time=time(7), to_time=time(19, 30),
        )
        self.assertTrue(bounded.contains(datetime(
            2026, 10, 8, 14, tzinfo=timezone.utc)))
        self.assertFalse(bounded.contains(datetime(
            2026, 10, 8, 15, tzinfo=timezone.utc)))

    def test_invalid_future_window_fails_before_network(self):
        now = datetime(2026, 10, 8, 14, tzinfo=timezone.utc)
        cases = [
            {"day": date(2026, 10, 9)},
            {"day": date(2026, 10, 8), "to_time": time(20)},
            {"day": date(2026, 10, 8), "from_time": time(20)},
            {"day": date(2026, 10, 8), "from_time": time(18),
             "to_time": time(17)},
        ]
        for case in cases:
            with self.subTest(case=case), self.assertRaises(ValueError):
                resolve_window(now=now, **case)

    def test_tz_aware_times_rejected(self):
        with self.assertRaises(ValueError):
            resolve_window(
                now=datetime(2026, 10, 8, 14, tzinfo=timezone.utc),
                from_time=time(7, tzinfo=timezone.utc),
            )

if __name__ == "__main__":
    unittest.main()
