# History reader (experimental)

No Telegram login is implemented yet. An authenticated, Telethon-compatible
client must be supplied by a future adapter. The reader never enumerates
dialogs or downloads media and accepts only an explicitly allowlisted numeric
chat ID. It fails rather than silently truncate history.

The digest window defaults to 07:00 inclusive and 18:00 exclusive, in
`Asia/Yekaterinburg` (UTC+05:00), independent of computer timezone.
Times are converted from the aware UTC timestamps received from Telegram.

Security warning: application-level chat allowlisting does NOT limit the
permissions of a stolen Telegram account session. No session or credentials
should ever be committed. Pseudonymization does not guarantee anonymity.
