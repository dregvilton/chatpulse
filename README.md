# ChatPulse

**Privacy-first Telegram chat digests powered by local language models.**

> **Experimental:** Telegram group selection and history reading are tested
> on a real account. Local Ollama digest code is available for user testing,
> but the full multimodal pipeline still needs real-chat validation.

ChatPulse aims to produce on-demand summaries of busy Telegram conversations,
without sending private chat content to cloud AI services.

## Security model

- **Telegram sessions:** native OS keyring only (macOS Keychain, Windows
  Credential Manager, approved Linux Secret Service/KWallet).
- **Local models:** local-only Ollama mode is required; ChatPulse refuses
  known cloud/remote model configurations and non-loopback inference.
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
chatpulse login --qr  # Preferred: scan QR with Telegram mobile Settings > Devices
chatpulse login       # Alternative: one-time code (Telegram controls delivery)
chatpulse status    # Checks whether a local secret exists; no network calls
chatpulse logout    # Revokes this session via Telegram, then clears keyring
```

Set up an API ID and hash at [my.telegram.org](https://my.telegram.org/).
**Do not paste credentials or a session into issues, chat messages, AI tools
or your repository.** Use only the private interactive prompts.

See [Telegram setup and known limitations](docs/TELEGRAM.md).

## Choose one chat and preview its history

Once Telegram authorization is stored, you can approve **one** group at a
time. No automatic discovery occurs on login.

```sh
chatpulse select-chat
# Enter LIST to explicitly allow a limited, temporary group listing
# Then select a group by its number
chatpulse preview
chatpulse preview --date 2026-10-08
```

Only group titles and selection numbers appear while choosing a group. The
list contains at most 50 group titles from the first 200 recent dialogs;
private one-to-one chats and broadcast channels are not offered. Telegram
may include latest-message metadata internally in its dialog response, but
ChatPulse never prints or saves that content.

The group ID/access hash is stored in the same **OS Keychain** as the
account's session; its name is not retained. `preview` uses the approved
InputPeer only, reads text messages within the selected local-day window,
and prints counts, anonymous participant count and first/last times —
**never message contents**. By default it reads today from 00:00 until now;
`--date` reads a selected past day (00:00–24:00). A message limit is enforced
to prevent silent truncation. `chatpulse logout` clears the saved group.

Preview is read-only. Only an explicit `digest --send` invokes Telegram
publication after successful local summarization.

## On-device Ollama digest (experimental)

After `chatpulse login --qr` and `chatpulse select-chat`, you can generate
an in-memory group summary with a **downloaded local model**. Ollama's cloud
features must be **disabled in the Ollama server config** and Ollama
restarted; merely connecting to `localhost` is *not* enough.

```sh
# After configuring ~/.ollama/server.json and pulling a local model yourself:
chatpulse local-models
chatpulse digest --model fredrezones55/Qwen3.5-Uncensored-HauhauCS-Aggressive:9b
chatpulse digest --model fredrezones55/Qwen3.5-Uncensored-HauhauCS-Aggressive:9b --date 2026-10-08 \
  --from-time 07:00 --to-time 19:30
# For faster model comparisons, summarize only the last 100 messages:
chatpulse digest --model fredrezones55/Qwen3.5-Uncensored-HauhauCS-Aggressive:9b \
  --date 2026-10-08 --sample-messages 100
# Optional: --tone neutral
```

### Post a prominent daily digest to the selected Telegram group

```sh
# Safe first check: count today's messages, no sending
chatpulse preview

# Preview the full digest locally, from midnight until invocation
chatpulse digest --model fredrezones55/Qwen3.5-Uncensored-HauhauCS-Aggressive:9b

# Recommended: review the generated digest, then type SEND to publish it.
# Same generation: no duplicate model call and no draft saved to disk.
chatpulse digest --model fredrezones55/Qwen3.5-Uncensored-HauhauCS-Aggressive:9b --review-send

# Advanced/unchecked: immediately publish without confirmation.
chatpulse digest --model fredrezones55/Qwen3.5-Uncensored-HauhauCS-Aggressive:9b --send
```

`--review-send` is recommended: show a full digest first, then type
`SEND` in the **same interactive terminal** to publish the exact summary
already generated. There is no saved draft, no second generation and no
send on Enter/other input. This preserves the original no-content-on-disk
privacy boundary. `--send` remains an **explicit unchecked immediate**
one-time publishing action, not a schedule or background bot. Both work
only for full digests (never with `--sample-messages`) and send one
formatted message to the already selected
group, and does not retry if Telegram delivery becomes ambiguous. The post
has a bold ⚡ ChatPulse header, date, local time window and compact text.
Review model accuracy and private details before choosing to publish.
Telegram receives the resulting digest, not original raw chat history.
Each subsequent run reads fresh chat messages but excludes earlier posts
with the ChatPulse header.

For multi-chunk days, the summarizer passes previous context and
recent replies into the next chunk; technical chunk boundaries are NOT
treated as separate discussions. This improves continuity but does not
guarantee factual accuracy.

### Rate the latest digest (1–5)

After each successful `chatpulse digest` run (including previews and sends),
ChatPulse stores **only minimal local run metadata**, never the chat, image,
generated summary, raw Telegram IDs or group name. Rate the most recent digest
at any time before generating another one:

```sh
chatpulse rate 5   # great, factual and funny
chatpulse rate 3   # acceptable
chatpulse rate 1   # wrong or unusable
```

Scores and model/duration/message-count metadata are stored on your own
machine at `~/.chatpulse/ratings.json` (private permissions on POSIX),
outside the repository and never sent to a server. Last 100 runs are
retained. Rating a digest does **not** train the model by itself; these
scores will help us compare versions before opting in to a separate,
local-only training dataset. No automatically collected Telegram content
is saved for training. `chatpulse rate` requires no network connection.

### Remove unused Ollama experiments

```sh
ollama list
ollama rm llama3.1:latest
ollama rm huihui_ai/qwen3-abliterated:8b
ollama rm dolphin3:8b
ollama rm CognitiveComputations/dolphin-mistral-nemo:12b-v2.9.3-Q4_K_M
```

Keep your current `fredrezones55/Qwen3.5-Uncensored-HauhauCS-Aggressive:9b`
and `qwen3-vl:4b` if installed. Deleting models only affects local Ollama
model files; confirm names with `ollama list` before deleting.

### Optional local image and sticker context

ChatPulse can now preserve Telegram reply-thread structure in a digest by
mapping raw Telegram IDs to transient `m1`, `m2`, etc., and indicating
which earlier turn each reply addresses. Raw IDs are never given to Ollama.

Vision is **opt-in**. Before trying it, explicitly install the image
preprocessing extra and download a local vision model:

```sh
python -m pip install -e '.[vision]'
ollama pull qwen3-vl:4b
chatpulse local-models

# Preview only: includes up to 4 photos or static WebP stickers, all in RAM
chatpulse digest \
  --model fredrezones55/Qwen3.5-Uncensored-HauhauCS-Aggressive:9b \
  --vision-model qwen3-vl:4b --max-images 4

# Recommended for real group: same generation, inspect and type SEND
chatpulse digest \
  --model fredrezones55/Qwen3.5-Uncensored-HauhauCS-Aggressive:9b \
  --vision-model qwen3-vl:4b --max-images 4 --review-send
```

The vision model describes eligible photos and *static* WebP stickers in
short Russian captions, directly in memory. GIFs, videos, voice messages,
animated stickers, oversized files, and images beyond the cap are not
decoded. No image data or captions are written to disk or forwarded to
remote LLM services. The original Telegram server already hosts the
media: downloading it requires an approved, authorized group session.
Descriptions are best-effort and can misread memes or contain identifying
details. No media is downloaded without the explicit `--vision-model` flag.
On a 16 GB Mac the vision model is unloaded after each image and
the main digest model runs afterward, so the first multimodal preview
can take longer. Test **without `--send` first**.

For less-filtered text in friends' chats, experiment with a downloaded
uncensored/abliterated model, such as
`fredrezones55/Qwen3.5-Uncensored-HauhauCS-Aggressive:9b`. First check
`ollama run MODEL "Привет"` independently before a private chat digest.
The default `friends` tone now preserves actual profanity and teasing
without moralizing or inventing jokes. For one-chunk samples ChatPulse
summarizes the redacted messages directly instead of losing details through
two LLM passes. Model quality and factual accuracy must be reviewed.

`--sample-messages 20..250` is a **quick test only**, not a full-day
digest. It reads the chosen time window into memory, uses only its last
N redacted messages for inference, clearly labels the output as partial,
and does not save or transmit anything beyond the local model process.

The digest uses today's messages until invocation by default, or an explicit
local time range, redacts and
pseudonymizes messages before local inference, and prints the result
to your terminal. **Only `--send` additionally posts the generated digest**
to the selected Telegram group. Large chats are summarized in bounded stages.

See [Ollama setup and security limitations](docs/OLLAMA.md).

## Defaults for the future digest

- Timezone: `Asia/Yekaterinburg`.
- Window: 00:00 to invocation for today; 00:00 to 24:00 for past days.
- Optional `--from-time HH:MM` and `--to-time HH:MM` for a custom window.
- Input: user-approved Telegram chat history.
- Output: a local LLM-generated digest.

The opt-in `digest` command is experimental and runs only when invoked.
No unattended scheduling exists. Delivery is opt-in via `--send`.

## Roadmap

1. Secure offline package, redaction, portable CI.
2. Allowlisted, time-bounded history-reader core.
3. OS-vault account authorization and remote session revocation.
4. Explicit chat selection, local-only LLM and hierarchical digests.
5. Portable scheduled jobs and public-release security review.

Originally built to survive 1000 unread messages in a friends' group chat.
