# teleping — Telegram notification CLI & MCP server

A single-file, stdlib-only Python CLI to send yourself push notifications
via a Telegram bot. Covers 14 message types.

## Setup

1. Create a bot with [@BotFather](https://t.me/BotFather) (`/newbot`) and copy the token.
2. Message your bot once, then find your chat id:
   `curl -s "https://api.telegram.org/bot<TOKEN>/getUpdates"`
3. Export credentials (never commit the token):

```bash
export TG_BOT_TOKEN="123456:ABC..."
export TG_CHAT_ID="8596273711"
```

## Usage

```bash
python3 teleping.py <TYPE> [args...]
```

| Type | Example |
|------|---------|
| `text` | `python3 teleping.py text "Deploy finished ✅"` |
| `html` | `python3 teleping.py html "<b>Alert:</b> disk at <code>91%</code> <tg-spoiler>secret</tg-spoiler>"` |
| `markdown` | `python3 teleping.py markdown "*bold* _italic_ \|\|spoiler\|\|"` |
| `silent` | `python3 teleping.py silent "FYI, no buzz"` |
| `buttons` | `python3 teleping.py buttons "Build failed" --button "Logs=https://ci.example.com"` |
| `photo` | `python3 teleping.py photo ./chart.png --caption "Daily stats"` |
| `document` | `python3 teleping.py document ./error.log --caption "Full log"` |
| `location` | `python3 teleping.py location 48.8584 2.2945` |
| `venue` | `python3 teleping.py venue 51.5007 -0.1246 "Big Ben" "London"` |
| `poll` | `python3 teleping.py poll "Lunch?" "Pizza" "Sushi" "Salad"` |
| `quiz` | `python3 teleping.py quiz "2+2?" --answers 3 4 5 --correct 1` |
| `dice` | `python3 teleping.py dice --emoji 🎰` |
| `contact` | `python3 teleping.py contact +15551234567 Jane --last-name Doe` |
| `reply` | `python3 teleping.py reply 42 "Replying to message 42"` |
| `read` | `python3 teleping.py read` — list incoming messages; replies show `↳ in reply to #id: <original text>` |

Global flags usable with any type: `--silent`, `--protect` (block
forwarding), `--reply-to MSG_ID`, `--token`, `--chat-id`.

`photo` and `document` accept either a URL or a local file path
(local files are uploaded; documents up to 50 MB).

`read` extras: `--wait N` long-polls up to N seconds for new messages;
`--ack` marks shown messages consumed so the next `read --ack` only shows
newer ones. Note: Telegram keeps unconsumed updates for ~24h, and `read`
won't work while a webhook is set on the bot.

Run `python3 teleping.py --help` or `python3 teleping.py <TYPE> --help` for details.

## teleping — remote MCP server (for Claude cloud sessions)

`teleping_mcp.py` exposes the same functionality as a remote MCP server so any
Claude session (cloud or local) can send/read Telegram messages as native
tools — no shell needed. One deployment serves many bots: every tool takes
an optional `bot` name; credentials stay server-side.

**Tools (13):** `send_message` (plain/HTML/MarkdownV2, silent, threaded
replies), `send_with_buttons`, `send_photo`, `send_document` (URL only),
`send_location`, `send_venue`, `send_poll` (regular or quiz mode),
`send_dice`, `send_contact`, `read_replies` (with reply-to tracking),
plus `list_bots`, `add_bot` (also rotates tokens), `remove_bot`.
Server instructions teach connected agents the full menu, the multi-bot
pattern, and what is unsupported.

**Bot registry:** a JSON object in a GCS bucket (`BOTS_GCS_BUCKET` env
var), editable live via the `add_bot`/`remove_bot` tools or `gsutil` — no
redeploy needed to add/remove bots. Falls back to a read-only `TG_BOTS`
env var if no bucket is configured:

```json
{"default": "personal",
 "bots": {"personal": {"token": "123:ABC", "chat_id": "42"},
          "alerts":   {"token": "456:DEF", "chat_id": "42"}}}
```

**Deploy to Cloud Run:**

```bash
PROJECT_ID=my-gcp-project bash deploy-mcp.sh
```

The script creates the registry bucket, builds/deploys, grants the service
account access, and prints the connector URL, which embeds a random secret
path (the only access control — treat the URL itself as a secret):

```
https://teleping-xxxx.a.run.app/<secret>/mcp
```

**Connect:** claude.ai → Settings → Connectors → Add custom connector →
paste that URL. Then any cloud session can call `send_message` etc.

**Managing bots from your local machine** (`botctl.sh` — edits the GCS
registry directly, so tokens never pass through a chat; requires an
authenticated `gcloud`/`gsutil`):

```bash
export BUCKET=my-project-teleping-bots

./botctl.sh list                                  # names, masked tokens
./botctl.sh add alerts <token> <chat_id>          # add or overwrite a bot
./botctl.sh add alerts <token> <chat_id> --default
./botctl.sh rotate personal <new_token>           # after revoking in @BotFather
./botctl.sh remove alerts
./botctl.sh set-default alerts
```

Tokens are verified against Telegram (`getMe`) before saving, and the
server picks up changes on its next request — no redeploy or restart.

**Local test:**

```bash
TG_BOTS='{"default":"x","bots":{"x":{"token":"...","chat_id":"..."}}}' \
  MCP_PATH_SECRET=dev PORT=8931 python3 teleping_mcp.py
# endpoint: http://127.0.0.1:8931/dev/mcp
```
