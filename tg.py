#!/usr/bin/env python3
"""tg — send Telegram notifications from the command line.

Supports all 14 message types demoed for this bot, each as a subcommand.
Uses only the Python standard library (no pip installs needed).

Setup:
    export TG_BOT_TOKEN="123456:ABC..."   # from @BotFather
    export TG_CHAT_ID="8596273711"        # your chat id (getUpdates)

Examples:
    ./tg.py text "Deploy finished ✅"
    ./tg.py html "<b>Alert:</b> disk at <code>91%</code>"
    ./tg.py markdown "*bold* _italic_ ||spoiler||"
    ./tg.py silent "Low-priority FYI"
    ./tg.py buttons "Build failed" --button "Logs=https://example.com/logs" --button "Dashboard=https://example.com"
    ./tg.py photo https://picsum.photos/600/400 --caption "A chart"
    ./tg.py photo ./graph.png --caption "Local file works too"
    ./tg.py document ./error.log --caption "Full log attached"
    ./tg.py location 48.8584 2.2945
    ./tg.py venue 51.5007 -0.1246 "Big Ben" "London SW1A 0AA"
    ./tg.py poll "Lunch?" "Pizza" "Sushi" "Salad"
    ./tg.py quiz "2+2?" --answers "3" "4" "5" --correct 1
    ./tg.py dice --emoji 🎰
    ./tg.py contact +15551234567 "Jane" --last-name "Doe"
    ./tg.py reply 42 "Replying to message 42" --protect
"""

import argparse
import json
import mimetypes
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid

API_BASE = "https://api.telegram.org"


def die(msg: str) -> "NoReturn":  # noqa: F821
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def get_config(args) -> tuple[str, str]:
    token = args.token or os.environ.get("TG_BOT_TOKEN")
    chat_id = args.chat_id or os.environ.get("TG_CHAT_ID")
    if not token:
        die("bot token missing: set TG_BOT_TOKEN or pass --token")
    if not chat_id:
        die("chat id missing: set TG_CHAT_ID or pass --chat-id")
    return token, chat_id


def call_api(token: str, method: str, params: dict, files: dict | None = None) -> dict:
    """POST to the Bot API. `files` maps field name -> local file path."""
    url = f"{API_BASE}/bot{token}/{method}"
    params = {k: v for k, v in params.items() if v is not None}

    if files:
        boundary = uuid.uuid4().hex
        body = b""
        for key, value in params.items():
            if isinstance(value, (dict, list)):
                value = json.dumps(value)
            body += (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{key}"\r\n\r\n'
                f"{value}\r\n"
            ).encode()
        for key, path in files.items():
            filename = os.path.basename(path)
            ctype = mimetypes.guess_type(filename)[0] or "application/octet-stream"
            with open(path, "rb") as f:
                content = f.read()
            body += (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{key}"; filename="{filename}"\r\n'
                f"Content-Type: {ctype}\r\n\r\n"
            ).encode() + content + b"\r\n"
        body += f"--{boundary}--\r\n".encode()
        req = urllib.request.Request(
            url, data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
    else:
        for k, v in list(params.items()):
            if isinstance(v, (dict, list)):
                params[k] = json.dumps(v)
        req = urllib.request.Request(url, data=urllib.parse.urlencode(params).encode())

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.load(resp)
    except urllib.error.HTTPError as e:
        try:
            err = json.load(e)
            desc = err.get("description", str(e))
        except Exception:
            desc = str(e)
        die(f"Telegram API {e.code}: {desc}")
    except urllib.error.URLError as e:
        die(f"network error: {e.reason}")

    if not result.get("ok"):
        die(f"Telegram API error: {result.get('description', result)}")
    return result["result"]


def send_media(token, chat_id, method, field, source, extra):
    """Send a photo/document/etc. from either a URL/file_id or a local path."""
    params = {"chat_id": chat_id, **extra}
    if os.path.isfile(source):
        return call_api(token, method, params, files={field: source})
    params[field] = source
    return call_api(token, method, params)


def parse_buttons(specs: list[str]) -> dict:
    """Turn 'Label=https://url' specs into an inline_keyboard reply_markup."""
    row = []
    for spec in specs:
        label, sep, url = spec.partition("=")
        if not sep or not url.startswith(("http://", "https://", "tg://")):
            die(f'bad --button "{spec}": expected "Label=https://url"')
        row.append({"text": label, "url": url})
    return {"inline_keyboard": [row]}


def format_update(update: dict) -> str | None:
    """Render one getUpdates entry as a human-readable line (or None to skip)."""
    msg = update.get("message") or update.get("edited_message")
    if not msg:
        return None
    who = msg.get("from", {}).get("first_name", "?")
    when = msg.get("date", 0)
    import datetime
    ts = datetime.datetime.fromtimestamp(when).strftime("%Y-%m-%d %H:%M:%S")
    text = msg.get("text") or msg.get("caption") or "<non-text message>"
    line = f"[{ts}] #{msg['message_id']} {who}: {text}"
    reply = msg.get("reply_to_message")
    if reply:
        orig = reply.get("text") or reply.get("caption") or "<non-text message>"
        if len(orig) > 60:
            orig = orig[:57] + "..."
        line += f"\n    ↳ in reply to #{reply['message_id']}: {orig}"
    if "edited_message" in update:
        line += "  (edited)"
    return line


def cmd_read(token: str, chat_id: str, args) -> None:
    """Read incoming messages (your replies to the bot) via getUpdates."""
    params: dict = {"timeout": 0, "allowed_updates": ["message", "edited_message"]}
    if args.wait:
        params["timeout"] = args.wait
    if args.offset is not None:
        params["offset"] = args.offset

    updates = call_api(token, "getUpdates", params)
    # Only show messages from the configured chat.
    updates = [u for u in updates
               if str((u.get("message") or u.get("edited_message") or {})
                      .get("chat", {}).get("id")) == str(chat_id)]
    if not updates:
        print("no new messages")
        return
    for u in updates:
        line = format_update(u)
        if line:
            print(line)
    if args.ack:
        # Confirm consumption so the next `read --ack` only shows newer messages.
        last_id = max(u["update_id"] for u in updates)
        call_api(token, "getUpdates", {"offset": last_id + 1, "timeout": 0})
        print(f"(acknowledged through update {last_id}; next read shows only newer)")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="tg",
        description="Send Telegram notifications (14 message types).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("Examples:")[1] if "Examples:" in __doc__ else None,
    )
    parser.add_argument("--token", help="bot token (default: $TG_BOT_TOKEN)")
    parser.add_argument("--chat-id", help="chat id (default: $TG_CHAT_ID)")
    parser.add_argument("--silent", action="store_true",
                        help="deliver without sound/vibration (any type)")
    parser.add_argument("--protect", action="store_true",
                        help="prevent forwarding/saving (any type)")
    parser.add_argument("--reply-to", type=int, metavar="MSG_ID",
                        help="send as a reply to this message id (any type)")
    sub = parser.add_subparsers(dest="command", required=True, metavar="TYPE")

    p = sub.add_parser("text", help="1. plain text message")
    p.add_argument("text")

    p = sub.add_parser("html", help="2. HTML-formatted text (<b>, <i>, <code>, <tg-spoiler>, ...)")
    p.add_argument("text")

    p = sub.add_parser("markdown", help="3. MarkdownV2-formatted text (*bold*, _italic_, ||spoiler||)")
    p.add_argument("text")

    p = sub.add_parser("silent", help="4. text with no sound/vibration")
    p.add_argument("text")

    p = sub.add_parser("buttons", help="5. text with tappable URL buttons")
    p.add_argument("text")
    p.add_argument("--button", action="append", required=True, metavar="LABEL=URL",
                   help="repeatable, e.g. --button 'Logs=https://...'")

    p = sub.add_parser("photo", help="6. photo (URL or local file) with optional caption")
    p.add_argument("source", help="image URL or local file path")
    p.add_argument("--caption")

    p = sub.add_parser("document", help="7. file attachment (any type, up to 50 MB)")
    p.add_argument("source", help="file URL or local file path")
    p.add_argument("--caption")

    p = sub.add_parser("location", help="8. map pin")
    p.add_argument("latitude", type=float)
    p.add_argument("longitude", type=float)

    p = sub.add_parser("venue", help="9. map pin with a title and address")
    p.add_argument("latitude", type=float)
    p.add_argument("longitude", type=float)
    p.add_argument("title")
    p.add_argument("address")

    p = sub.add_parser("poll", help="10. poll with 2-10 options")
    p.add_argument("question")
    p.add_argument("options", nargs="+", metavar="OPTION")
    p.add_argument("--anonymous", action="store_true",
                   help="hide voters (default: visible)")
    p.add_argument("--multiple", action="store_true",
                   help="allow choosing several answers")

    p = sub.add_parser("quiz", help="11. quiz poll with one correct answer")
    p.add_argument("question")
    p.add_argument("--answers", nargs="+", required=True, metavar="ANSWER")
    p.add_argument("--correct", type=int, required=True, metavar="INDEX",
                   help="0-based index of the correct answer")
    p.add_argument("--explanation", help="shown after answering")

    p = sub.add_parser("dice", help="12. animated emoji roll")
    p.add_argument("--emoji", default="🎲", choices=["🎲", "🎯", "🏀", "⚽", "🎳", "🎰"],
                   help="default: 🎲")

    p = sub.add_parser("contact", help="13. contact card")
    p.add_argument("phone")
    p.add_argument("first_name")
    p.add_argument("--last-name")

    p = sub.add_parser("reply", help="14. threaded reply to an earlier message")
    p.add_argument("message_id", type=int)
    p.add_argument("text")

    p = sub.add_parser("read", help="read incoming messages; shows which message each reply is to")
    p.add_argument("--wait", type=int, metavar="SECONDS",
                   help="long-poll: block up to N seconds waiting for new messages")
    p.add_argument("--ack", action="store_true",
                   help="mark shown messages as consumed (next read --ack shows only newer)")
    p.add_argument("--offset", type=int,
                   help="start from this update_id (advanced)")

    args = parser.parse_args()
    token, chat_id = get_config(args)

    if args.command == "read":
        cmd_read(token, chat_id, args)
        return

    common = {
        "chat_id": chat_id,
        "disable_notification": True if (args.silent or args.command == "silent") else None,
        "protect_content": True if args.protect else None,
        "reply_to_message_id": args.reply_to,
    }

    cmd = args.command
    if cmd in ("text", "silent"):
        result = call_api(token, "sendMessage", {**common, "text": args.text})
    elif cmd == "html":
        result = call_api(token, "sendMessage",
                          {**common, "text": args.text, "parse_mode": "HTML"})
    elif cmd == "markdown":
        result = call_api(token, "sendMessage",
                          {**common, "text": args.text, "parse_mode": "MarkdownV2"})
    elif cmd == "buttons":
        result = call_api(token, "sendMessage",
                          {**common, "text": args.text,
                           "reply_markup": parse_buttons(args.button)})
    elif cmd == "photo":
        result = send_media(token, chat_id, "sendPhoto", "photo", args.source,
                            {**common, "caption": args.caption})
    elif cmd == "document":
        result = send_media(token, chat_id, "sendDocument", "document", args.source,
                            {**common, "caption": args.caption})
    elif cmd == "location":
        result = call_api(token, "sendLocation",
                          {**common, "latitude": args.latitude,
                           "longitude": args.longitude})
    elif cmd == "venue":
        result = call_api(token, "sendVenue",
                          {**common, "latitude": args.latitude,
                           "longitude": args.longitude,
                           "title": args.title, "address": args.address})
    elif cmd == "poll":
        result = call_api(token, "sendPoll",
                          {**common, "question": args.question,
                           "options": args.options,
                           "is_anonymous": args.anonymous,
                           "allows_multiple_answers": args.multiple})
    elif cmd == "quiz":
        if not 0 <= args.correct < len(args.answers):
            die(f"--correct must be 0..{len(args.answers) - 1}")
        result = call_api(token, "sendPoll",
                          {**common, "question": args.question,
                           "options": args.answers, "type": "quiz",
                           "correct_option_id": args.correct,
                           "explanation": args.explanation})
    elif cmd == "dice":
        result = call_api(token, "sendDice", {**common, "emoji": args.emoji})
    elif cmd == "contact":
        result = call_api(token, "sendContact",
                          {**common, "phone_number": args.phone,
                           "first_name": args.first_name,
                           "last_name": args.last_name})
    elif cmd == "reply":
        common["reply_to_message_id"] = args.message_id
        result = call_api(token, "sendMessage", {**common, "text": args.text})
    else:  # unreachable: argparse enforces the subcommand set
        die(f"unknown command {cmd}")

    print(f"sent: {cmd} (message_id={result.get('message_id', '?')})")


if __name__ == "__main__":
    main()
