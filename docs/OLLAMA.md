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
   example, `ollama pull huihui_ai/qwen3-abliterated:8b` (the actual model may be changed).
   This download contacts Ollama's model registry; only subsequent
   inference is local. ChatPulse never downloads models automatically.
4. Run `chatpulse local-models`. It requires the cloud-disabled config and
   lists eligible downloaded models. Remote aliases and names containing
   `cloud` are excluded.
5. Run `chatpulse digest --date 2026-10-08 --model huihui_ai/qwen3-abliterated:8b`.
   Use `--tone friends` (default) or `--tone neutral`.

The entire command reads **only the previously approved chat**, in
the selected day's local window (by default 00:00 until invocation
for today), pseudonymizes/redacts messages in
memory, then sends *only those projections* to the local HTTP Ollama server.
The digest is printed to the **local terminal** by default. Only an
explicit `digest --send` delivers the generated (not raw) summary to the
already approved Telegram group via the logged-in account; it cannot be
used with `--sample-messages`. No background delivery or scheduled posts.
Telegram, group members, terminal scrollback and compromised local OS/users
are outside ChatPulse's local-inference protection boundary.

A typical 700+ message conversation needs multiple local inference calls.
The process shows chunk counts, without quoting chat messages or identities.
A running note and recent message overlap are passed forward to preserve
conversation context across technical chunks, and related stories are merged
at the final stage. This is best effort, not a factual accuracy guarantee.
Model processing can take substantial time on less powerful machines.

## Optional image/sticker comprehension

Photos and static WebP stickers are excluded unless `--vision-model` is
explicitly supplied. Use `chatpulse vision-check --model qwen3-vl:4b-instruct`
to validate local visual inference first on an in-memory synthetic image,
without ever contacting Telegram. A failed optional visual caption logs
only a fixed reason code and continues with text-only chat context.
Local model verification failures remain fatal. Install with `pip install -e '.[vision]'`, pull
`qwen3-vl:4b-instruct` deliberately, then use `--vision-model qwen3-vl:4b-instruct
--max-images 4`. Each media file must advertise a size no greater than
3 MB; decoding and JPEG resizing (maximum 768 pixels per side) happen
in RAM, with at most 4 images by default and an absolute cap of 8.
An image is sent only to the approved local Ollama server and its downloaded
vision model; it is not written to a file. Vision descriptions are
best-effort; animated stickers/GIFs are labeled but not decoded.
The vision model is unloaded after each request to leave memory for the
main text summarizer.

Reply relationships are mapped to per-run turn numbers (`m1` etc.).
Telegram's original message IDs are not sent to the model.
Media may contain personal information; the local vision model may
misidentify it or hallucinate details. Do not publish without checking
the digest for errors.

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
- No content logging, telemetry, automatic model downloads, scheduled actions
  or background sending. `--send` is a one-time explicit delivery that sends
  the summarized digest to Telegram and cannot be undone. Unit tests run
  entirely offline.

## About model choice

Larger 12B models may be slow or too large for lower-memory Apple Silicon
Macs. A locally downloaded 8B abliterated model is a reasonable first alternative,
but quality should be evaluated on your actual chat. Model choice does not
change the privacy guarantees of an appropriately isolated local Ollama
daemon. Don't use the `:cloud` variants.
