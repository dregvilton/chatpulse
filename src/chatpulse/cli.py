"""Offline CLI for the security foundation; no Telegram or model connection yet."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json

from chatpulse.privacy import RawMessage, sanitize_messages, validate_ollama_url


def main() -> None:
    parser = argparse.ArgumentParser(description="Local-first Telegram digest tooling")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("demo", help="Show anonymization using synthetic input")
    doctor = sub.add_parser("doctor", help="Validate local-only endpoint; no network calls")
    doctor.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    args = parser.parse_args()
    if args.command == "doctor":
        validate_ollama_url(args.ollama_url)
        print("OK: loopback-only endpoint configured; no network check performed.")
    else:
        messages = [
            RawMessage(1001, "Alex", datetime(2026, 10, 8, 10, tzinfo=timezone.utc),
                       "Alex, look at https://example.com"),
            RawMessage(1002, "Sam", datetime(2026, 10, 8, 11, tzinfo=timezone.utc),
                       "Бля, опять тысяча сообщений!"),
        ]
        safe = sanitize_messages(messages, timezone="UTC")
        print(json.dumps([m.as_payload() for m in safe], ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
