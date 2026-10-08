# Telegram authentication and history (experimental)

## Account login (no bot token)

The CLI `chatpulse login` uses a normal Telegram **user account** because a
bot token cannot fetch arbitrary chat history on demand.

1. Install package dependencies and have a functioning OS keyring.
2. Create **your own** Telegram API ID + hash at https://my.telegram.org.
3. Run `chatpulse login` in a terminal. Paste API ID; enter API hash and
   phone privately (not as command-line arguments). Complete Telegram login
   code and optional 2FA prompts.
4. `chatpulse status` reports only whether the local secret exists; it does
   not make a Telegram API call or verify that the session remains valid.
5. `chatpulse logout` revokes the session at Telegram and then removes the
   stored secret. It requires an interactive confirmation. If revocation
   cannot be confirmed, use Telegram **Settings > Devices**.

The Telethon `StringSession` authentication key, API ID and API hash are saved
together in a supported OS keyring. Nothing is placed into a `.session` file,
an environment variable, GitHub Actions secret, or stdout. No account name,
phone number, code or 2FA password is stored by ChatPulse. The secrets are
still in process memory while a command runs.

Supported backends: macOS Keychain, Windows Credential Manager, Linux
SecretService/libsecret/KWallet. Unknown backends and plaintext-file
alternatives are rejected. For headless Linux, configure a working OS secret
service or wait for a future explicitly reviewed solution; there is no
insecure fallback.

**Security tradeoff:** A vault protects against casual file disclosure, not
against every process running as the same OS user. macOS Keychain may allow
other Python scripts using the same interpreter to access an item once
authorized. Never install untrusted Python packages under the same account.

## Digest reader (not wired into authenticated CLI yet)

`chatpulse.history.collect_history` accepts an already-authenticated
Telethon-compatible client with an explicitly allowlisted numeric chat ID.
It never enumerates all dialogs, downloads media or fetches contacts.

Default window: 07:00 (inclusive) to 18:00 (exclusive) in
`Asia/Yekaterinburg` (UTC+05:00), regardless of OS timezone. Message count
overflow fails rather than silently truncating.

**Known integration issue:** Telethon may require an entity access hash to
resolve a numeric ID when entity caching is disabled. The next iteration
must implement explicit, user-approved chat selection/resolution before
connecting history and CLI. This is not yet an end-to-end bot.
