"""Local CLI: no secrets on command lines, in logs, or printed responses."""
from __future__ import annotations

import argparse
import asyncio
from datetime import date, datetime, time as clock_time, timezone
import json
import sys
import time
from typing import Sequence

from chatpulse.privacy import RawMessage, sanitize_messages, validate_ollama_url
from chatpulse.ollama_local import LocalModelError
from chatpulse.digest import DigestError


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



def _select_chat() -> None:
    from chatpulse.credentials import open_system_vault
    from chatpulse.group_workflow import approve_group
    from chatpulse.selection import GroupChoice
    from prompt_toolkit import PromptSession
    from prompt_toolkit.history import DummyHistory
    from prompt_toolkit.validation import Validator

    _interactive_only()
    vault = open_system_vault()
    if vault.load() is None:
        print("Not logged in. Run chatpulse login --qr first.")
        return
    print("This action temporarily fetches up to 200 recent Telegram dialog records.")
    print("Only group titles will appear locally. Private chats and messages are not shown.")
    print("Telegram may transmit recent-message metadata during dialog discovery.")
    if input("Type LIST to inspect eligible groups: ").strip() != "LIST":
        print("Cancelled: no dialog discovery.")
        return

    def show(groups: list[GroupChoice]) -> None:
        print("\nGroups available (at most 50):")
        for index, group in enumerate(groups, 1):
            print(f"  {index:2}. {group.title}")

    async def choose(limit: int) -> int:
        session: PromptSession[str] = PromptSession(history=DummyHistory())
        number = await session.prompt_async(
            "\nSelect group number: ",
            validator=Validator.from_callable(
                lambda value: value.isascii() and value.isdecimal()
                and 1 <= int(value) <= limit,
                error_message="Enter one of the listed group numbers",
            ),
            validate_while_typing=False,
        )
        return int(number)

    print("Connecting to Telegram and loading group choices...", flush=True)
    if asyncio.run(approve_group(
        vault, consent=True, present_choices=show, choose_number=choose,
    )):
        print("Approved group saved in OS keyring. Other chats remain unselected.")
    else:
        print("No eligible groups found in the first 200 dialogs.")


def _preview_history(day: date | None, from_time: clock_time | None = None,
                     to_time: clock_time | None = None) -> None:
    from chatpulse.credentials import open_system_vault
    from chatpulse.group_workflow import preview_selected_group

    print("Reading the approved group history (no messages will be printed)...", flush=True)
    stats = asyncio.run(preview_selected_group(
        open_system_vault(), day=day, from_time=from_time, to_time=to_time
    ))
    print(f"Group history preview: {stats.day.isoformat()} (Asia/Yekaterinburg)")
    print(f"Time window: {stats.window_start}-{stats.window_end}, local timezone")
    print(f"Text messages: {stats.messages}")
    print(f"Participants (pseudonymized): {stats.participants}")
    if stats.first_time is not None:
        print(f"First / last message: {stats.first_time} / {stats.last_time}")
    if not stats.window_finished:
        print("Today is still ongoing; this is a snapshot at the requested cutoff.")
    print("No message contents, user IDs or group names were printed or saved.")


def _local_models() -> None:
    from chatpulse.ollama_local import OllamaLocal

    models = OllamaLocal().local_models()
    if not models:
        print("No eligible downloaded local Ollama models found.")
        return
    print("Downloaded local models (cloud-tagged models are excluded):")
    for item in models:
        print(f"  {item.name} ({item.disk_bytes // (1024**2)} MiB on disk)")


def _digest_history(*, day: date | None, model: str, tone: str,
                    from_time: clock_time | None = None,
                    to_time: clock_time | None = None,
                    sample_messages: int | None = None) -> None:
    from chatpulse.credentials import open_system_vault
    from chatpulse.digest import summarize_safe_messages
    from chatpulse.group_workflow import read_selected_safe_history
    from chatpulse.ollama_local import OllamaLocal

    # Reject invalid sampling arguments before network reads or model inference.
    if sample_messages is not None and not 20 <= sample_messages <= 250:
        raise ValueError("Sample size must be between 20 and 250 messages")

    # Privacy gate before the first chat-history request. No Telegram content
    # is retrieved unless local model/configuration checks are successful.
    local = OllamaLocal()
    local.ensure_local(model)
    print("Local-only model preflight passed. Reading the approved group...", flush=True)
    window, finished, messages = asyncio.run(
        read_selected_safe_history(
            open_system_vault(), day=day, from_time=from_time, to_time=to_time
        )
    )
    if not messages:
        print("No text messages found in the selected time window.")
        return
    full_count = len(messages)
    if sample_messages is not None:
        messages = messages[-sample_messages:]
        print(
            f"TEST SAMPLE: using last {len(messages)} of {full_count} messages "
            f"({messages[0].time}–{messages[-1].time} local). "
            "This is NOT a full-day digest.",
            flush=True,
        )
    print(f"Summarizing {len(messages)} redacted messages in memory...", flush=True)
    started = time.monotonic()
    digest = summarize_safe_messages(
        messages, model_client=local, model=model, tone=tone,
        on_progress=lambda index, count: print(
            f"  Local summary chunk {index}/{count} "
            f"(elapsed {int(time.monotonic() - started)} s)", flush=True
        ),
    )
    print(f"  Total generation: {int(time.monotonic() - started)} s, "
          f"{digest.chunks} chunks", flush=True)
    cutoff = window.end.strftime("%H:%M") if window.start.date() == window.end.date() else "24:00"
    print(f"\nChatPulse digest — {window.start.date().isoformat()} "
          f"({window.start.strftime('%H:%M')}–{cutoff}, Asia/Yekaterinburg)")
    if not finished:
        print("(Snapshot: new messages may arrive after this run.)")
    if sample_messages is not None:
        print("(TEST SAMPLE ONLY: not representative of the entire day.)")
    print("(Local summary. No Telegram messages sent or files written.)\n")
    print(digest.text)

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
    sub.add_parser("select-chat", help="Opt in to listing groups and approve one group")
    preview_parser = sub.add_parser("preview", help="Count safe messages from approved group")
    preview_parser.add_argument("--date", type=date.fromisoformat, default=None,
                                help="Local YYYY-MM-DD (default: today, up to now)")
    preview_parser.add_argument("--from-time", type=clock_time.fromisoformat, default=None,
                                help="Local HH:MM start (default 00:00)")
    preview_parser.add_argument("--to-time", type=clock_time.fromisoformat, default=None,
                                help="Local HH:MM cutoff (default now today, 24:00 past days)")
    sub.add_parser("local-models", help="List eligible local Ollama models; no Telegram reads")
    digest_parser = sub.add_parser("digest", help="Generate a local-only group digest")
    digest_parser.add_argument("--model", required=True, help="Downloaded Ollama model")
    digest_parser.add_argument("--date", type=date.fromisoformat, default=None,
                               help="Local YYYY-MM-DD (default: today, up to now)")
    digest_parser.add_argument("--tone", choices=("friends", "neutral"), default="friends")
    digest_parser.add_argument("--from-time", type=clock_time.fromisoformat, default=None,
                               help="Local HH:MM start (default 00:00)")
    digest_parser.add_argument("--to-time", type=clock_time.fromisoformat, default=None,
                               help="Local HH:MM cutoff (default now today, 24:00 past days)")
    digest_parser.add_argument(
        "--sample-messages", type=int, default=None,
        help="TEST ONLY: summarize the last 20-250 messages instead of the full period"
    )
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
        elif args.command == "select-chat":
            _select_chat()
        elif args.command == "preview":
            _preview_history(args.date, args.from_time, args.to_time)
        elif args.command == "local-models":
            _local_models()
        elif args.command == "digest":
            _digest_history(
                day=args.date, model=args.model, tone=args.tone,
                from_time=args.from_time, to_time=args.to_time,
                sample_messages=args.sample_messages,
            )
        elif args.command == "logout":
            _logout()
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled.", file=sys.stderr)
        return 130
    except LocalModelError:
        print(
            "Local Ollama verification failed. Check that cloud features "
            "are disabled in ~/.ollama/server.json, restart Ollama, "
            "and run chatpulse local-models. No chat content was sent "
            "unless generation had already started.",
            file=sys.stderr,
        )
        return 1
    except DigestError:
        print(
            "Digest could not be completed within safety and size limits. "
            "No summary was saved or sent to Telegram.",
            file=sys.stderr,
        )
        return 1
    except TimeoutError:
        if args.command == "login":
            message = (
                "Telegram did not respond in time. A login code may still "
                "arrive; avoid repeatedly requesting new ones."
            )
        else:
            message = "Telegram request timed out. No messages were saved."
        print(message, file=sys.stderr)
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
