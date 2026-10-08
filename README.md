# ChatPulse

**Privacy-first Telegram digests powered by local language models.**

> Early security foundation only — not a functional Telegram bot yet.

ChatPulse is being built as a portable, open-source CLI for scheduled summaries of busy Telegram conversations. It is **not** designed to forward message history to cloud LLM providers.

## Security-first design

- Local model inference only (planned Ollama integration; cloud-model support must be disabled).
- No raw Telegram objects in LLM requests: an explicitly allowlisted data projection is used.
- Participant pseudonyms, configurable redaction aliases and best-effort identifier removal.
- Loopback-only model endpoint; no cloud API fallback.
- Never check in Telegram sessions, secrets or chat transcripts.
- Configurable time windows and digest profiles are planned, not yet implemented.

**Important:** Pseudonymization does not guarantee anonymity. The local model may still infer identities from context. Telegram itself remains an external service for history access and delivery.

## Offline quick start

Python 3.11 or newer, on macOS / Windows / Linux.

```sh
python -m pip install -e .
chatpulse doctor
chatpulse demo
python -m unittest discover -s tests -v
```

`doctor` validates only the URL format; it does not verify Ollama settings or connect to the network. `demo` only uses synthetic chat messages.

## Roadmap

1. Secure foundation, tests, documented trust boundaries.
2. Explicit Telegram login, safe session storage, allowlisted chat history.
3. Local-only Ollama with cloud refusal, chunking and hierarchical summaries.
4. Ergonomic setup, configurable schedules, portable packaging and security review.

See [security model](docs/SECURITY.md).

Originally built to survive 1000 unread messages in a friends' group chat.
