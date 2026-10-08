import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from chatpulse.credentials import CredentialVault
from chatpulse.telegram_auth import TelegramAuthError, login, revoke
from tests.fakes import FakeKeyring


class FakeClient:
    def __init__(self, api_id, api_hash, session):
        self.api_id, self.api_hash, self.input_session = api_id, api_hash, session
        self.events = []
        self.session = SimpleNamespace(save=lambda: "1" + "A" * 100)
        self.signed_in = False
        self.revoke_ok = True
    async def connect(self):
        self.events.append("connect")
    async def disconnect(self):
        self.events.append("disconnect")
    async def send_code_request(self, phone):
        self.events.append("request")
        return SimpleNamespace(phone_code_hash="HASH")
    async def sign_in(self, **kwargs):
        self.events.append("signin")
        self.signed_in = True
    async def is_user_authorized(self):
        return self.signed_in
    async def log_out(self):
        self.events.append("logout")
        return self.revoke_ok


class AuthTests(unittest.TestCase):
    def setUp(self):
        self.backend = FakeKeyring()
        with patch("chatpulse.credentials._is_trusted_backend", return_value=True):
            self.vault = CredentialVault(self.backend)
        self.clients = []

    def factory(self, api_id, api_hash, session):
        client = FakeClient(api_id, api_hash, session)
        self.clients.append(client)
        return client

    def do_login(self, phone="+79991234567"):
        return asyncio.run(login(
            self.vault, api_id=123, api_hash="a" * 32, phone=phone,
            prompt_code=lambda: "12345", prompt_password=lambda: "secret",
            client_factory=self.factory,
        ))

    def test_success_and_revoke(self):
        self.do_login()
        self.assertEqual(self.clients[0].events,
                         ["connect", "request", "signin", "disconnect"])
        self.assertIsNotNone(self.vault.load())
        self.assertEqual(self.clients[0].input_session, "")
        self.assertTrue(asyncio.run(revoke(self.vault, client_factory=self.factory)))
        self.assertEqual(self.clients[1].input_session, "1" + "A" * 100)
        self.assertEqual(self.clients[1].events, ["connect", "logout", "disconnect"])
        self.assertIsNone(self.vault.load())

    def test_refuse_existing_without_network(self):
        self.do_login()
        with self.assertRaises(TelegramAuthError):
            self.do_login()
        self.assertEqual(len(self.clients), 1)

    def test_invalid_phone_no_network(self):
        with self.assertRaises(TelegramAuthError):
            self.do_login("12345")
        self.assertEqual(self.clients, [])

    def test_failed_vault_write_attempts_remote_revoke(self):
        with patch.object(self.vault, "save_new", side_effect=RuntimeError("write failed")):
            with self.assertRaises(RuntimeError):
                self.do_login()
        self.assertEqual(
            self.clients[0].events,
            ["connect", "request", "signin", "logout", "disconnect"],
        )
        self.assertIsNone(self.vault.load())

    def test_remote_failure_keeps_vault(self):
        self.do_login()
        def factory(api_id, api_hash, session):
            client = self.factory(api_id, api_hash, session)
            client.revoke_ok = False
            return client
        with self.assertRaises(TelegramAuthError):
            asyncio.run(revoke(self.vault, client_factory=factory))
        self.assertIsNotNone(self.vault.load())


if __name__ == "__main__":
    unittest.main()
