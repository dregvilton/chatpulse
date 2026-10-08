"""Local CLI: no secrets on command lines, in logs, or printed responses."""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
import sys
from typing import Sequence

from chatpulse.privacy import RawMessage, sanitize_messages, validate_ollama_url


def _interactive_only() -> None:
    if not sys.stdin.isatty() or not sys.stderr.isatty():
        raise RuntimeError("Login/logout requires an interactive terminal")


def _login(*, qr: bool = False) -> None:
    from chatpulse.credentials import open_system_vault
    from chatpulse.telegram_auth import login

    vault = open_system_vault()
    if vault.load() is not None:
        raise RuntimeError("A session exists already. Use logout before logging in again.")
    _interactive_only()
    from chatpulse.login_wizard import LoginWizard

    wizard = LoginWizard()
    api_id, api_hash, phone = wizard.application(qr=qr)
    if qr:
        from chatpulse.qr_auth import login_with_qr
        from chatpulse.qr_display import show_qr
        print("\nStep 2 of 2: QR verification", flush=True)
        asyncio.run(login_with_qr(
            vault, api_id=api_id, api_hash=api_hash,
            display_qr=show_qr, prompt_password=wizard.password,
            on_progress=lambda stage: print({
                "connecting": "  Connecting to Telegram...",
                "qr_ready": "  Waiting for approval on your phone...",
                "qr_expired": "  QR expired. Generating a fresh code...",
                "password_required": "  Telegram requires your two-step password.",
                "storing": "  Authorized! Saving securely in OS keyring...",
            }[stage], flush=True),
        ))
        print("\nSuccess: Telegram session stored in OS keyring.")
        return
    assert phone is not None
    print("\nStep 3 of 3: Telegram verification")
    print("  Connecting and requesting a code... (network connection may take time)", flush=True)
    asyncio.run(login(
        vault,
        api_id=api_id, api_hash=api_hash, phone=phone,
        prompt_code=wizard.code,
        prompt_password=wizard.password,
        on_progress=lambda stage: print({
            "connected": "  Connected. Requesting one-time code...",
            "code_sent": "  Code requested. Check Telegram service chat, SMS or login email.",
            "verifying": "  Verifying the code...",
            "storing": "  Authorized. Saving to your OS credential vault...",
        }[stage], flush=True),
    ))
    print("Telegram session stored in your OS credential vault.")


def _logout() -> None:
    from chatpulse.credentials import open_system_vault
    from chatpulse.telegram_auth import revoke

    vault = open_system_vault()
    if vault.load() is None:
        print("No stored Telegram session.")
        return
    _interactive_only()
    if input("Type REVOKE to invalidate this session at Telegram: ").strip() != "REVOKE":
        print("No changes made.")
        return
    if asyncio.run(revoke(vault)):
        print("Telegram confirmed revocation; local secret was deleted.")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Local-first Telegram digest tooling")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("demo", help="Show anonymization using synthetic input")
    doctor = sub.add_parser("doctor", help="Validate local-only endpoint; no network calls")
    doctor.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    login_parser = sub.add_parser(
        "login", help="Authorize through a code or --qr using OS keyring"
    )
    login_parser.add_argument("--qr", action="store_true", help="Scan with Telegram phone app")
    sub.add_parser("status", help="Show only whether a local session exists")
    sub.add_parser("logout", help="Revoke Telegram session remotely, then remove local secret")
    args = parser.parse_args(argv)
    try:
        if args.command == "doctor":
            validate_ollama_url(args.ollama_url)
            print("OK: loopback-only endpoint configured; no network check performed.")
        elif args.command == "demo":
            messages = [
                RawMessage(1001, "Alex", datetime(2026, 10, 8, 10, tzinfo=timezone.utc),
                           "Alex, look at https://example.com"),
                RawMessage(1002, "Sam", datetime(2026, 10, 8, 11, tzinfo=timezone.utc),
                           "Бля, опять тысяча сообщений!"),
            ]
            safe = sanitize_messages(messages, timezone="UTC")
            print(json.dumps([m.as_payload() for m in safe], ensure_ascii=True, indent=2))
        elif args.command == "status":
            from chatpulse.credentials import open_system_vault
            print("Session stored." if open_system_vault().load() else "Not logged in.")
        elif args.command == "login":
            _login(qr=args.qr)
        elif args.command == "logout":
            _logout()
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled.", file=sys.stderr)
        return 130
    except TimeoutError:
        print(
            "Telegram did not respond in time. Check your connection. "
            "A code may still arrive; avoid repeatedly requesting new ones.",
            file=sys.stderr,
        )
        return 1
    except Exception:
        # Telethon and OS keyring errors can contain phone numbers, codes or
        # credential backends' details. Never echo raw exception strings.
        print(
            "Operation failed. No secret details displayed. "
            "Check OS keyring and Telegram connectivity; "
            "use Telegram Settings > Devices to revoke a session if necessary.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
