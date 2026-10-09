import asyncio
from datetime import date, datetime, timezone
from types import SimpleNamespace
import unittest
from chatpulse.history import daily_window, collect_history, collect_safe_history

class FakeClient:
    def __init__(self, msgs):
        self.msgs, self.calls = msgs, []
    async def iter_messages(self, entity, *, offset_date):
        self.calls.append((entity, offset_date))
        for m in self.msgs:
            yield m

def msg(hour, content, sender=1):
    return SimpleNamespace(date=datetime(2026, 10, 8, hour, tzinfo=timezone.utc),
                           message=content, sender_id=sender)

class HistoryTests(unittest.TestCase):
    def test_timezone(self):
        w = daily_window(date(2026, 10, 8))
        self.assertEqual(w.start.astimezone(timezone.utc).hour, 2)
        self.assertEqual(w.end.astimezone(timezone.utc).hour, 13)
        self.assertTrue(w.contains(msg(2, "yes").date))
        self.assertFalse(w.contains(msg(13, "no").date))

    def test_allowlist_fails_before_network(self):
        c = FakeClient([msg(5, "secret")])
        with self.assertRaises(PermissionError):
            asyncio.run(collect_history(c, chat_id=22, allowed_chat_ids=frozenset({11}),
                       window=daily_window(date(2026, 10, 8))))
        self.assertEqual(c.calls, [])

    def test_boundaries_order_and_pseudonyms(self):
        c = FakeClient([msg(14, "late"), msg(12, "Бля", 2), msg(5, "hello"),
                        msg(1, "early")])
        safe = asyncio.run(collect_safe_history(c, chat_id=11,
            allowed_chat_ids=frozenset({11}), window=daily_window(date(2026, 10, 8))))
        self.assertEqual([m.text for m in safe], ["hello", "Бля"])
        self.assertEqual([m.time for m in safe], ["10:00", "17:00"])
        self.assertEqual([m.author for m in safe], ["Participant 1", "Participant 2"])
        self.assertEqual(c.calls[0][1].hour, 13)

    def test_cached_sender_names_are_only_used_for_local_redaction(self):
        data = msg(5, "Андрей показал фотку, а AndreyCool заценил")
        data.sender = SimpleNamespace(
            first_name="Андрей", last_name="Синтетический",
            username="AndreyCool",
        )
        safe = asyncio.run(collect_safe_history(
            FakeClient([data]), chat_id=11,
            allowed_chat_ids=frozenset({11}),
            window=daily_window(date(2026, 10, 8)),
        ))
        self.assertEqual(len(safe), 1)
        self.assertNotIn("Андрей", safe[0].text)
        self.assertNotIn("AndreyCool", safe[0].text)
        self.assertIn("[person]", safe[0].text)

    def test_fail_closed_on_limit(self):
        with self.assertRaisesRegex(ValueError, "Message limit exceeded"):
            asyncio.run(collect_history(FakeClient([msg(6, "b"), msg(5, "a")]),
                chat_id=11, allowed_chat_ids=frozenset({11}),
                window=daily_window(date(2026, 10, 8)), max_messages=1))

    def test_media_only_scan_is_bounded(self):
        media_only = [msg(5, None)] * 4
        with self.assertRaisesRegex(ValueError, "Scan limit exceeded"):
            asyncio.run(collect_history(
                FakeClient(media_only), chat_id=11,
                allowed_chat_ids=frozenset({11}),
                window=daily_window(date(2026, 10, 8)), max_messages=1,
            ))

    def test_prior_chatpulse_digest_is_not_included_in_new_digest(self):
        from chatpulse.history import DigestWindow
        from zoneinfo import ZoneInfo
        zone = ZoneInfo("Asia/Yekaterinburg")
        w = DigestWindow(
            datetime(2026, 10, 8, 0, tzinfo=zone),
            datetime(2026, 10, 9, 0, tzinfo=zone),
        )
        c = FakeClient([
            msg(14, "⚡ CHATPULSE · ДАЙДЖЕСТ ⚡\\nOld digest"),
            msg(13, "Actual new message"),
        ])
        result = asyncio.run(collect_history(
            c, chat_id=11, allowed_chat_ids=frozenset({11}), window=w,
        ))
        self.assertEqual([item.text for item in result], ["Actual new message"])

    def test_media_skipped(self):
        output = asyncio.run(collect_history(FakeClient([msg(5, None), msg(4, "text")]),
             chat_id=11, allowed_chat_ids=frozenset({11}),
             window=daily_window(date(2026, 10, 8))))
        self.assertEqual(len(output), 1)
