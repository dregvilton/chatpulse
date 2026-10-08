# Ollama integration (local-only, experimental)

This feature is **opt-in**. `chatpulse preview` never invokes an LLM.

## Setup

1. Install [Ollama](https://ollama.com/download) for your operating system,
   but do not install any model until you deliberately choose one.
2. **Disable Ollama cloud features in the Ollama server**, rather than setting
   an environment variable on ChatPulse alone. Edit the user's
   `~/.ollama/server.json` so the file contains:

   ```json
   {
     "disable_ollama_cloud": true
   }
   ```

   If you already have server settings, add this key without deleting them.
   Restart the Ollama application/service to apply the change. Official
   Ollama docs: https://docs.ollama.com/faq#how-do-i-disable-ollama-cloud-features

3. Deliberately download a **local model** suitable for your memory. For
   example, `ollama pull qwen3:4b-instruct` (the actual model may be changed).
   This download contacts Ollama's model registry; only subsequent
   inference is local. ChatPulse never downloads models automatically.
4. Run `chatpulse local-models`. It requires the cloud-disabled config and
   lists eligible downloaded models. Remote aliases and names containing
   `cloud` are excluded.
5. Run `chatpulse digest --date 2026-10-08 --model qwen3:4b-instruct`.
   Use `--tone friends` (default) or `--tone neutral`.

The entire command reads **only the previously approved chat**, in
`07:00–18:00 Asia/Yekaterinburg`, pseudonymizes/redacts messages in
memory, then sends *only those projections* to the local HTTP Ollama server.
The digest is printed to the **local terminal**, never sent to Telegram or
saved to a file. Terminal scrollback and a compromised local OS/user are
outside ChatPulse's protection boundary.

A typical 700+ message conversation needs multiple local inference calls.
The process shows chunk counts, without quoting chat messages or identities.
Model processing can take substantial time on less powerful machines.

## Security boundaries

- ChatPulse only uses an explicitly numeric loopback HTTP origin such as
  `http://127.0.0.1:11434`. It uses standard-library `HTTPConnection`,
  which does not consult environment proxies or follow HTTP redirects.
  No HTTP request may target anything but `/api/tags`, `/api/show`, and
  `/api/chat`.
- Local-only config `disable_ollama_cloud: true` must exist at the local
  `~/.ollama/server.json`. Cloud-labelled model names, remote
  `remote_host`/`remote_model` metadata and implausibly small model
  entries are refused **before** sending message content.
- ChatPulse re-checks the model's local status before every inference.
- The model receives `SafeMessage` projections only, not `RawMessage`,
  unredacted Telegram objects, media, contact records or group identifiers.
- The model is instructed to treat message content and intermediary notes
  as **untrusted data**. A language model may still be deceived by prompt
  injection and may repeat identifying details not caught by redaction.
- ChatPulse cannot cryptographically prove the running Ollama daemon has
  *reloaded* the cloud-disable setting or that no other local software
  proxies content elsewhere. A malicious, replaced or externally bridged
  local daemon is **not** trustworthy. Review Ollama logs for
  `Ollama cloud disabled: true` and do not expose the Ollama service to a
  public network. If Ollama runs as another OS user or in a container,
  ChatPulse's local config check may not match the daemon's effective config
  and will require additional administrative verification.
- No content logging, telemetry, model downloads, scheduled actions or
  background sending is performed. Unit tests run entirely offline.

## About model choice

Larger 12B models may be slow or too large for lower-memory Apple Silicon
Macs. A small locally downloaded 4B model is a reasonable first smoke test,
but quality should be evaluated on your actual chat. Model choice does not
change the privacy guarantees of an appropriately isolated local Ollama
daemon. Don't use the `:cloud` variants.
