# ChatPulse

**Privacy-first Telegram chat digests powered by local language models.**

> **Early development:** Auth and an isolated history-reader library are
> implemented, but the end-to-end digest pipeline is not yet available.

ChatPulse aims to produce scheduled summaries of busy Telegram conversations,
without sending private chat content to cloud AI services.

## Security model

- **Telegram sessions:** native OS keyring only (macOS Keychain, Windows
  Credential Manager, approved Linux Secret Service/KWallet).
- **Local models:** only local inference is planned; cloud Ollama models and
  remote API providers will be rejected.
- **Privacy:** model-facing fields are allowlisted, with pseudonyms and
  best-effort redaction. This does **not** guarantee anonymity.
- **Safety:** no telemetry, message-content logs, session files in the
  repository, or account credentials on the command line.
- **Telegram limitation:** session auth keys still have the logged-in user's
  normal Telegram privileges. The account owner must secure their OS account.

See [security design](docs/SECURITY.md).

## Install (macOS / Windows / Linux)

Python **3.11+**. On Linux, a running Secret Service-compatible keyring or
KWallet is needed for account authorization.

```sh
python -m pip install -e .
chatpulse doctor
chatpulse demo
```

For development:

```sh
python -m pip install -e ".[dev]"
python -m unittest discover -s tests -v
```

`chatpulse doctor` checks the **format** of a local Ollama endpoint; it
does not contact Ollama or prove that cloud modes are disabled. `demo` is
entirely synthetic and offline.

## Telegram login

```sh
chatpulse login     # Interactive login, stores authorization in OS keyring
chatpulse status    # Checks whether a local secret exists; no network calls
chatpulse logout    # Revokes this session via Telegram, then clears keyring
```

Set up an API ID and hash at [my.telegram.org](https://my.telegram.org/).
**Do not paste credentials or a session into issues, chat messages, AI tools
or your repository.** Use only the private interactive prompts.

See [Telegram setup and known limitations](docs/TELEGRAM.md).

## Defaults for the future digest

- Timezone: `Asia/Yekaterinburg` (configurable later).
- Window: `07:00–18:00` local time (configurable later).
- Input: user-approved Telegram chat history.
- Output: a local LLM-generated digest.

There is no scheduling or digest generation command yet.

## Roadmap

1. Secure offline package, redaction, portable CI.
2. Allowlisted, time-bounded history-reader core.
3. OS-vault account authorization and remote session revocation.
4. Explicit chat selection, local-only LLM and hierarchical digests.
5. Portable scheduled jobs and public-release security review.

Originally built to survive 1000 unread messages in a friends' group chat.
