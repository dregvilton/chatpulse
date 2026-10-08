# Security and privacy

## Trust boundaries

1. Telegram itself is external: login, fetching history and delivering
   digests contact Telegram. Only a person who deliberately authorizes an
   account should use this tool.
2. A user session has the **full privileges of the logged-in Telegram
   account**. A ChatPulse chat allowlist is a safeguard against accidental
   selection, not an access-control sandbox for a stolen session.
3. **Secret storage:** a native OS credential store only. The session
   auth key (Telethon StringSession) and API hash are stored in Keychain,
   Credential Manager or supported Linux Secret Service/KWallet. Refuse
   third-party/plaintext/keyring chainer backends. No .session files.
4. OS keyrings are not protection against malware running with the same
   user privileges. A compromised Python interpreter or OS account could
   still access stored secrets; review packages before installation.
5. **Model input (planned):** only safe model-facing projections;
   never send raw Telegram objects, ID, contacts, files or location payloads.
6. **Local inference (planned):** numeric loopback-only model origin, no
   redirects or environment proxy usage. Loopback alone is insufficient:
   Ollama supports remotely hosted models. The future adapter must require
   cloud disabled and refuse cloud model names before digest features launch.
7. No analytics or telemetry. No logs or exception strings containing
   message texts, session keys, names, API hashes, phone, codes or passwords.
8. Redaction is best effort, **not guaranteed anonymity**. Chat references,
   local slang, rare names or indirectly identifying events can remain.
9. Telegram digest delivery necessarily transmits the resulting text to
   Telegram, so sending must be an explicit, configured operation.

## Auth flows

- `chatpulse login`: collect credentials interactively; connect directly to
  Telegram; persist session to OS keyring **after** successful authorization;
  avoid session-file creation; no dialog discovery.
- `chatpulse status`: checks existence of OS secret **only**, no network.
- `chatpulse logout`: revoke the Telegram authorization first and delete
  local secret after confirmation. On network failure retain secret and
  instruct revocation in Telegram > Settings > Devices.

## Group selection and safe preview

- `chatpulse select-chat` requires typing `LIST` *before* dialog discovery.
  The bounded dialog response can contain last-message metadata returned by
  Telegram; ChatPulse ignores this content and offers **groups only**.
- Telegram group titles are displayed locally, with terminal control/bidi
  characters removed; titles are not saved.
- The selected group InputPeer ID and per-account access hash are stored in
  the same native OS keyring. The choice is removed after successful logout
  or overwritten on reauthorization.
- `chatpulse preview` makes a narrow, one-chat time-bounded history request,
  runs the privacy projection in memory, and displays only aggregate counts
  and times. No messages are sent to any model, logged or exported.
- A group allowlist is a code-level protection against accidental reads, not
  a capability-security boundary on the Telegram session itself.
- Live real-account testing is required before claiming the entire path
  works against Telegram. CI uses fake clients without network access.

## Pending before first real digest

- Explicit approved chat/entity resolution with no dialog enumeration;
  limited history scope, dry-run and non-LLM fixture tests.
- Stronger redaction tests and prompt-injection isolation.
- Local Ollama adapter, disable cloud features, refuse remote models,
  proxies and redirects; never automatically download models.
- Large context handling, final delivery guard and production review.
- Packaging supply-chain checks, secret scan and robust version pinning.

## Vulnerability reporting

Do not include API hashes, Telethon sessions, real private chats or other
secrets in public GitHub issues. Contact repository maintainers privately.
