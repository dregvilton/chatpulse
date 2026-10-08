"""QR login tests use a fake Telegram client and in-memory OS vault."""
import asyncio
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from chatpulse.credentials import CredentialVault
from chatpulse.qr_auth import login_with_qr
from chatpulse.telegram_auth import TelegramAuthError
from tests.fakes import FakeKeyring


class FakeQR:
    def __init__(self, client, expire_first=False):
        self.client = client
        self.url = "tg://login?token=FAKE_LOCAL_TEST_TOKEN"
        self.expire_first = expire_first
        self.wait_count = 0
        self.refresh_count = 0

    async def wait(self):
        self.wait_count += 1
        if self.expire_first and self.wait_count == 1:
            raise asyncio.TimeoutError
        self.client.authorized = True

    async def recreate(self):
        self.refresh_count += 1


class FakeClient:
    def __init__(self, expire_first=False):
        self.authorized = False
        self.events = []
        self.session = SimpleNamespace(save=lambda: "1" + "Z" * 100)
        self.qr = FakeQR(self, expire_first)

    async def connect(self):
        self.events.append("connect")

    async def set_receive_updates(self, enabled):
        self.events.append(("updates", enabled))

    async def qr_login(self):
        self.events.append("qr")
        return self.qr

    async def is_user_authorized(self):
        return self.authorized

    async def disconnect(self):
        self.events.append("disconnect")

    async def log_out(self):
        self.events.append("logout")
        self.authorized = False
        return True


class QRTests(unittest.TestCase):
    def setUp(self):
        backend = FakeKeyring()
        with patch("chatpulse.credentials._is_trusted_backend", return_value=True):
            self.vault = CredentialVault(backend)

    def execute(self, fake, *, max_qr_attempts=3):
        urls, progress = [], []

        async def secret_prompt():
            raise AssertionError("2FA not needed in this scenario")

        def factory(api_id, api_hash, session):
            self.assertEqual(session, "")
            return fake

        operation = login_with_qr(
            self.vault, api_id=123, api_hash="a" * 32,
            client_factory=factory, display_qr=urls.append,
            prompt_password=secret_prompt, on_progress=progress.append,
            max_qr_attempts=max_qr_attempts,
        )
        return operation, urls, progress

    def test_scan_persists_session_and_cleans_up(self):
        fake = FakeClient()
        coro, urls, progress = self.execute(fake)
        asyncio.run(coro)
        self.assertEqual(len(urls), 1)
        self.assertEqual(progress, ["connecting", "qr_ready", "storing"])
        self.assertEqual(fake.events, ["connect", ("updates", True), "qr", "disconnect"])
        self.assertIsNotNone(self.vault.load())

    def test_expired_token_is_refreshed_without_new_code(self):
        fake = FakeClient(expire_first=True)
        coro, urls, progress = self.execute(fake)
        asyncio.run(coro)
        self.assertEqual(fake.qr.refresh_count, 1)
        self.assertEqual(len(urls), 2)
        self.assertIn("qr_expired", progress)
        self.assertIsNotNone(self.vault.load())

    def test_timeout_refuses_incomplete_login(self):
        fake = FakeClient(expire_first=True)
        coro, urls, progress = self.execute(fake, max_qr_attempts=1)
        with self.assertRaises(TelegramAuthError):
            asyncio.run(coro)
        self.assertIsNone(self.vault.load())
        self.assertEqual(fake.events[-1], "disconnect")

    def test_fails_before_network_on_invalid_credentials(self):
        fake = FakeClient()
        called = []
        async def prompt():
            return "unused"
        with self.assertRaises(TelegramAuthError):
            asyncio.run(login_with_qr(
                self.vault, api_id=123, api_hash="INVALID",
                display_qr=called.append, prompt_password=prompt,
                client_factory=lambda *args: fake,
            ))
        self.assertEqual(fake.events, [])
        self.assertEqual(called, [])


if __name__ == "__main__":
    unittest.main()
