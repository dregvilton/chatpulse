import json
from unittest.mock import patch
import unittest

from chatpulse.credentials import (
    AlreadyConfiguredError, CredentialVault, SecureStorageError, TelegramCredentials,
)


from tests.fakes import FakeKeyring

class VaultTests(unittest.TestCase):
    def test_unknown_backend_rejected(self):
        with self.assertRaises(SecureStorageError):
            CredentialVault(FakeKeyring())

    def test_store_read_forget(self):
        fake = FakeKeyring()
        with patch("chatpulse.credentials._is_trusted_backend", return_value=True):
            vault = CredentialVault(fake)
        secret = TelegramCredentials(101, "a" * 32, "1" + "B" * 100)
        self.assertNotIn(secret.session, repr(secret))
        self.assertNotIn(secret.api_hash, repr(secret))
        self.assertIsNone(vault.load())
        vault.save_new(secret)
        self.assertEqual(vault.load(), secret)
        with self.assertRaises(AlreadyConfiguredError):
            vault.save_new(secret)
        self.assertEqual(len(fake.entries), 1)
        vault.forget()
        self.assertEqual(fake.entries, {})

    def test_corrupted_storage_fails_closed(self):
        fake = FakeKeyring()
        with patch("chatpulse.credentials._is_trusted_backend", return_value=True):
            vault = CredentialVault(fake)
        fake.entries[("chatpulse.telegram", "default")] = json.dumps({"session": "1BAD"})
        with self.assertRaises(SecureStorageError):
            vault.load()
        with self.assertRaises(SecureStorageError):
            vault.save_new(TelegramCredentials(123, "b" * 32, "1" + "A" * 90))
        self.assertEqual(len(fake.entries), 1)

    def test_reject_invalid_format(self):
        for api_id, api_hash, session in ((0, "a" * 32, "1" + "b" * 100),
                                          (1, "BAD", "1" + "b" * 100),
                                          (1, "a" * 32, "x")):
            with self.subTest(api_id=api_id), self.assertRaises(ValueError):
                TelegramCredentials(api_id, api_hash, session)


if __name__ == "__main__":
    unittest.main()
