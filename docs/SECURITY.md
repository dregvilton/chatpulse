# Security and privacy

## Boundaries

1. Telegram is external: fetching history or sending summaries contacts Telegram.
2. Future Telethon sessions carry the **full permissions of the logged-in Telegram account**. An application chat allowlist is not a security sandbox. A stolen session can expose other chats.
3. Only `SafeMessage` projections may enter a local model prompt; do not forward raw Telegram objects, account details, contacts, files or location payloads.
4. Only numeric HTTP loopback is allowed for the model endpoint; future HTTP client must independently enforce this, disable environment proxies and refuse redirects.
5. **Loopback is not enough:** Ollama supports cloud-hosted models. Future integration must require cloud features disabled (`OLLAMA_NO_CLOUD=1`) and refuse models marked as cloud/remote. This is NOT implemented in this foundation.
6. No telemetry, raw message logs or session material in repository, CI, exceptions or prompts.
7. Message authors are pseudonymized, not reliably anonymized. Names, places, distinctive events and rephrased identifiers may survive text filtering.

## Planned safeguards

- Explicit authorized chat IDs and time windows, default read-only.
- OS-specific protected session storage, restrictive permissions and explicit logout.
- No model downloads during digest execution. User provisions models themselves.
- Local-only model, no cloud provider fallback, no redirects and no environment proxies.
- Prompt-injection-resistant prompt structure. No LLM-controlled tools or network calls.
- CLI preview and deliberate output destination: sending digest to Telegram is an external transmission.
- Fault and error logs must not contain message content.
- No persistent raw history by default.

## Vulnerability reports

Do not publish actual sessions, API credentials or private chat excerpts in issues. Contact repository owner privately before disclosure.
