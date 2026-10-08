"""Account secrets are stored only in approved operating-system keyrings.

This module deliberately has no plaintext-file, environment-variable, or
third-party keyring fallback. Do not log repr() of secret-bearing values.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import re
from typing import Protocol

_SERVICE = "chatpulse.telegram"
_ACCOUNT = "default"
# Exact built-in backend classes, not arbitrary third-party plugins or chainers.
_TRUSTED_BACKENDS = frozenset({
    "keyring.backends.macOS.Keyring",
    "keyring.backends.Windows.WinVaultKeyring",
    "keyring.backends.SecretService.Keyring",
    "keyring.backends.libsecret.Keyring",
    "keyring.backends.kwallet.DBusKeyring",
})


class SecureStorageError(RuntimeError):
    """Deliberately excludes potentially sensitive backend error details."""


class AlreadyConfiguredError(SecureStorageError):
    pass


class KeyringBackend(Protocol):
    def get_password(self, service: str, username: str) -> str | None: ...
    def set_password(self, service: str, username: str, password: str) -> None: ...
    def delete_password(self, service: str, username: str) -> None: ...


@dataclass(frozen=True, repr=False, slots=True)
class TelegramCredentials:
    api_id: int
    api_hash: str = field(repr=False)
    session: str = field(repr=False)

    def __post_init__(self) -> None:
        if type(self.api_id) is not int or self.api_id <= 0:
            raise ValueError("Invalid API ID")
        if not re.fullmatch(r"[a-fA-F0-9]{32}", self.api_hash):
            raise ValueError("Invalid API hash")
        if not isinstance(self.session, str) or not self.session.startswith("1") or len(self.session) < 50:
            raise ValueError("Invalid session format")


def _is_trusted_backend(backend: object) -> bool:
    klass = type(backend)
    name = f"{klass.__module__}.{klass.__qualname__}"
    return name in _TRUSTED_BACKENDS


class CredentialVault:
    """A single Telegram identity in the OS vault, never in repository files."""

    def __init__(self, backend: KeyringBackend) -> None:
        if not _is_trusted_backend(backend):
            raise SecureStorageError("A supported native OS keyring is required")
        self._backend = backend

    def load(self) -> TelegramCredentials | None:
        try:
            raw = self._backend.get_password(_SERVICE, _ACCOUNT)
        except Exception:
            raise SecureStorageError("Unable to read OS keyring") from None
        if raw is None:
            return None
        try:
            obj = json.loads(raw)
            if not isinstance(obj, dict) or set(obj) != {"api_id", "api_hash", "session"}:
                raise ValueError("Unexpected stored data")
            return TelegramCredentials(**obj)
        except (TypeError, ValueError):
            raise SecureStorageError("Stored credentials are invalid; no overwrite performed") from None

    def save_new(self, credentials: TelegramCredentials) -> None:
        if self.load() is not None:
            raise AlreadyConfiguredError("A session is already stored; logout first")
        data = json.dumps({
            "api_id": credentials.api_id,
            "api_hash": credentials.api_hash,
            "session": credentials.session,
        }, separators=(",", ":"))
        try:
            self._backend.set_password(_SERVICE, _ACCOUNT, data)
        except Exception:
            raise SecureStorageError("Unable to write OS keyring") from None

    def forget(self) -> None:
        if self.load() is None:
            return
        try:
            self._backend.delete_password(_SERVICE, _ACCOUNT)
        except Exception:
            raise SecureStorageError("Unable to delete keyring entry") from None


def open_system_vault() -> CredentialVault:
    import keyring

    try:
        backend = keyring.get_keyring()
    except Exception:
        raise SecureStorageError("OS keyring could not be initialized") from None
    return CredentialVault(backend)
