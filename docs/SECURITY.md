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
5. **Model input:** only safe model-facing projections;
   never send raw Telegram objects, ID, contacts, files or location payloads.
6. **Local inference (experimental):** numeric loopback-only model origin,
   no redirects or environment proxy usage. Ollama cloud mode is explicitly
   disabled in server config, and local model status is checked per request.
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
- Real Mac verification succeeded for group selection and preview; CI also
  uses fake Telegram clients for isolated regression tests.

## Experimental on-device inference

- `chatpulse digest` will **not read Telegram history** until it has
  verified the local Ollama cloud-disable config and the selected model.
- Its HTTP client connects directly to a numeric loopback address with
  no proxy following, redirect handling or DNS lookup.
- The selected model must be downloaded and appear in the local model list;
  names marked `cloud` or entries with `remote_host` or `remote_model`
  are excluded. We check those properties before each inference request.
- Cloud disabling must be configured on the **actual Ollama server**;
  ChatPulse can check the local `~/.ollama/server.json`, but cannot attest
  that a compromised daemon obeys it or has restarted.
- Content sent to the local model is best-effort redacted, not guaranteed
  anonymous. Any summary printed to a local terminal remains visible in
  terminal scrollback and potentially to local malware.
- Prompts explicitly treat chat contents as data, not instructions;
  prompt-injection attacks can still influence LLM output.
- No automatic downloads, system prompts containing user secrets, remote
  requests, exports, or Telegram delivery.
- See [Ollama setup and trust boundaries](OLLAMA.md).

## Pending for production readiness

- Inspect quality and factual fidelity of an alternative model against real
  chat messages, without uploading private chat content.
- Evaluate local summary performance and bounded adaptive scheduling; currently
  all runs are manual and the current day ends at invocation.
- Stronger free-text redaction and prompt-injection resistance tests.
- Delivery opt-in, production security review and dependency pinning.
- Packaging supply-chain verification and secret scanning.

## Vulnerability reporting

Do not include API hashes, Telethon sessions, real private chats or other
secrets in public GitHub issues. Contact repository maintainers privately.
