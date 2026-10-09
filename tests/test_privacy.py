from datetime import datetime, timezone
import json
import unittest

from chatpulse.privacy import RawMessage, redact_text, sanitize_messages, validate_ollama_url


class PrivacyTests(unittest.TestCase):
    def test_metadata_excluded_but_tone_preserved(self):
        records = [RawMessage(456798, "Алексей",
                    datetime(2026, 10, 8, 12, 30, tzinfo=timezone.utc),
                    "Алексей сказал бля")]
        payload = json.dumps(
            [m.as_payload() for m in sanitize_messages(records, timezone="Europe/Moscow")],
            ensure_ascii=False,
        )
        self.assertNotIn("456798", payload)
        self.assertNotIn("Алексей", payload)
        self.assertIn("Participant 1", payload)
        self.assertIn("бля", payload)
        self.assertIn("15:30", payload)

    def test_cached_sender_aliases_redacted_without_leaking_to_llm(self):
        source = RawMessage(
            9001, None, datetime(2026, 10, 8, 12, tzinfo=timezone.utc),
            "Андрей написал, что AndreyCool снова пропал.",
            sender_aliases=("Андрей", "AndreyCool"),
        )
        safe = sanitize_messages([source], timezone="UTC")
        self.assertNotIn("Андрей", safe[0].text)
        self.assertNotIn("AndreyCool", safe[0].text)
        self.assertIn("[person]", safe[0].text)
        self.assertNotIn("9001", str(safe[0].as_payload()))

    def test_reply_to_uses_transient_turns_never_raw_telegram_ids(self):
        t = datetime(2026, 10, 8, 12, 30, tzinfo=timezone.utc)
        messages = [
            RawMessage(44, None, t, "Warzone", message_id=900111),
            RawMessage(55, None, t, "Не, Dota", message_id=900112),
            RawMessage(44, None, t, "Варзон лучше", message_id=900113,
                       reply_to_id=900111),
            RawMessage(55, None, t, "Дота норм", message_id=900114,
                       reply_to_id=900112),
        ]
        safe = sanitize_messages(messages, timezone="UTC")
        self.assertEqual([m.turn for m in safe], ["m1", "m2", "m3", "m4"])
        self.assertEqual([m.reply_to_turn for m in safe],
                         [None, None, "m1", "m2"])
        exported = json.dumps([m.as_payload() for m in safe])
        for raw_id in ("900111", "900112", "900113", "900114"):
            self.assertNotIn(raw_id, exported)
        self.assertIn('"reply_to": "m1"', exported)

    def test_text_identifier_patterns(self):
        result = redact_text(
            "Write name@example.com @exampleuser or https://t.me/exampleuser "
            "phone +7 (999) 123-45-67"
        )
        for secret in ("name@example.com", "@exampleuser", "https://t.me", "123-45-67"):
            self.assertNotIn(secret, result)

    def test_naive_time_rejected(self):
        with self.assertRaises(ValueError):
            sanitize_messages(
                [RawMessage(1, "User", datetime(2026, 10, 8), "hi")], timezone="UTC"
            )

    def test_loopback_only(self):
        for accepted in ("http://127.0.0.1:11434", "http://[::1]:11434"):
            self.assertEqual(validate_ollama_url(accepted), accepted)
        for rejected in (
            "https://127.0.0.1:11434", "http://localhost:11434",
            "http://192.168.1.5:11434", "http://8.8.8.8:11434",
            "http://127.0.0.1:11434/api", "http://u:p@127.0.0.1:11434",
            "http://127.0.0.1:11434?x=1", "http://127.0.0.1",
        ):
            with self.subTest(url=rejected), self.assertRaises(ValueError):
                validate_ollama_url(rejected)

    def test_explicit_aliases(self):
        self.assertEqual(
            redact_text("Серёга говорил с Саней", ["Серёга", "Саней"]),
            "[person] говорил с [person]",
        )


if __name__ == "__main__":
    unittest.main()
