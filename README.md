# tg — Telegram notification CLI

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
python3 tg.py <TYPE> [args...]
```

| Type | Example |
|------|---------|
| `text` | `python3 tg.py text "Deploy finished ✅"` |
| `html` | `python3 tg.py html "<b>Alert:</b> disk at <code>91%</code> <tg-spoiler>secret</tg-spoiler>"` |
| `markdown` | `python3 tg.py markdown "*bold* _italic_ \|\|spoiler\|\|"` |
| `silent` | `python3 tg.py silent "FYI, no buzz"` |
| `buttons` | `python3 tg.py buttons "Build failed" --button "Logs=https://ci.example.com"` |
| `photo` | `python3 tg.py photo ./chart.png --caption "Daily stats"` |
| `document` | `python3 tg.py document ./error.log --caption "Full log"` |
| `location` | `python3 tg.py location 48.8584 2.2945` |
| `venue` | `python3 tg.py venue 51.5007 -0.1246 "Big Ben" "London"` |
| `poll` | `python3 tg.py poll "Lunch?" "Pizza" "Sushi" "Salad"` |
| `quiz` | `python3 tg.py quiz "2+2?" --answers 3 4 5 --correct 1` |
| `dice` | `python3 tg.py dice --emoji 🎰` |
| `contact` | `python3 tg.py contact +15551234567 Jane --last-name Doe` |
| `reply` | `python3 tg.py reply 42 "Replying to message 42"` |
| `read` | `python3 tg.py read` — list incoming messages; replies show `↳ in reply to #id: <original text>` |

Global flags usable with any type: `--silent`, `--protect` (block
forwarding), `--reply-to MSG_ID`, `--token`, `--chat-id`.

`photo` and `document` accept either a URL or a local file path
(local files are uploaded; documents up to 50 MB).

`read` extras: `--wait N` long-polls up to N seconds for new messages;
`--ack` marks shown messages consumed so the next `read --ack` only shows
newer ones. Note: Telegram keeps unconsumed updates for ~24h, and `read`
won't work while a webhook is set on the bot.

Run `python3 tg.py --help` or `python3 tg.py <TYPE> --help` for details.
