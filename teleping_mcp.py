#!/usr/bin/env python3
"""teleping — remote MCP server exposing Telegram bot notifications as tools.

One deployment serves any number of bots ("option 1" multi-bot design):
tools take a `bot` name; credentials live server-side, never in chats.

Bot registry (pick one):
  * GCS (recommended, no redeploy to change bots): set BOTS_GCS_BUCKET and
    optionally BOTS_GCS_OBJECT (default "teleping-bots.json"). The object holds:
        {"default": "personal",
         "bots": {"personal": {"token": "123:ABC", "chat_id": "42"},
                  "alerts":   {"token": "456:DEF", "chat_id": "42"}}}
    The Cloud Run service account needs roles/storage.objectAdmin on the
    bucket. The add_bot / remove_bot tools edit this object in place.
  * Env var fallback (read-only, redeploy to change): TG_BOTS holding the
    same JSON.

Other env vars:
  MCP_PATH_SECRET  unguessable path segment; the MCP endpoint becomes
                   /<secret>/mcp. Required in production — it is the only
                   thing keeping strangers from using your bots.
  PORT             listen port (Cloud Run sets this).

Connect from claude.ai: Settings -> Connectors -> Add custom connector ->
  https://<cloud-run-url>/<MCP_PATH_SECRET>/mcp
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

TG_API = "https://api.telegram.org"
GCS_API = "https://storage.googleapis.com"
METADATA_TOKEN_URL = ("http://metadata.google.internal/computeMetadata/v1/"
                      "instance/service-accounts/default/token")


# Subclassing ToolError makes the message visible to the calling agent
# instead of a generic "Error executing tool".
class TgError(ToolError):
    pass


def http_json(req: urllib.request.Request) -> dict:
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")[:500]
        raise TgError(f"HTTP {e.code}: {body}") from None
    except urllib.error.URLError as e:
        raise TgError(f"network error: {e.reason}") from None


def tg_call(token: str, method: str, params: dict) -> dict:
    params = {k: (json.dumps(v) if isinstance(v, (dict, list)) else v)
              for k, v in params.items() if v is not None}
    req = urllib.request.Request(
        f"{TG_API}/bot{token}/{method}",
        data=urllib.parse.urlencode(params).encode())
    result = http_json(req)
    if not result.get("ok"):
        raise TgError(f"Telegram: {result.get('description', result)}")
    return result["result"]


# ---------------------------------------------------------------- registry

def _gcs_config() -> tuple[str, str] | None:
    bucket = os.environ.get("BOTS_GCS_BUCKET")
    if not bucket:
        return None
    return bucket, os.environ.get("BOTS_GCS_OBJECT", "teleping-bots.json")


def _gcs_token() -> str:
    req = urllib.request.Request(METADATA_TOKEN_URL,
                                 headers={"Metadata-Flavor": "Google"})
    return http_json(req)["access_token"]


def load_registry() -> dict:
    gcs = _gcs_config()
    if gcs:
        bucket, obj = gcs
        url = (f"{GCS_API}/storage/v1/b/{bucket}/o/"
               f"{urllib.parse.quote(obj, safe='')}?alt=media")
        req = urllib.request.Request(
            url, headers={"Authorization": f"Bearer {_gcs_token()}"})
        try:
            return http_json(req)
        except TgError as e:
            if "HTTP 404" in str(e):
                return {"default": None, "bots": {}}
            raise
    env = os.environ.get("TG_BOTS")
    if env:
        return json.loads(env)
    raise TgError("no bot registry: set BOTS_GCS_BUCKET or TG_BOTS")


def save_registry(registry: dict) -> None:
    gcs = _gcs_config()
    if not gcs:
        raise TgError("registry is read-only (TG_BOTS env var); "
                      "configure BOTS_GCS_BUCKET to enable add/remove")
    bucket, obj = gcs
    url = (f"{GCS_API}/upload/storage/v1/b/{bucket}/o"
           f"?uploadType=media&name={urllib.parse.quote(obj, safe='')}")
    req = urllib.request.Request(
        url, data=json.dumps(registry, indent=2).encode(),
        headers={"Authorization": f"Bearer {_gcs_token()}",
                 "Content-Type": "application/json"})
    http_json(req)


def resolve_bot(bot: str | None) -> tuple[str, str, str]:
    """Return (name, token, chat_id) for `bot` or the registry default."""
    registry = load_registry()
    bots = registry.get("bots", {})
    if not bots:
        raise TgError("registry has no bots; use add_bot first")
    name = bot or registry.get("default") or next(iter(bots))
    entry = bots.get(name)
    if not entry:
        raise TgError(f"unknown bot {name!r}; known: {sorted(bots)}")
    return name, entry["token"], str(entry["chat_id"])


# ------------------------------------------------------------------ server

mcp = MCPServer(
    "teleping",
    instructions=(
        "Teleping sends Telegram notifications to the user's phone through "
        "named bots and reads their replies. Every send/read tool takes an "
        "optional `bot` name selecting which bot (and therefore which "
        "destination chat) to use; omit it for the default bot, and call "
        "list_bots to discover what exists.\n"
        "Message types: send_message covers plain text, HTML, MarkdownV2 "
        "(parse_mode), silent delivery, and threaded replies "
        "(reply_to_message_id). Richer types have dedicated tools: "
        "send_with_buttons (tappable URL buttons), send_photo, "
        "send_document, send_location, send_venue, send_poll (regular or "
        "quiz mode), send_dice (animated emoji), send_contact.\n"
        "Two-way: read_replies returns messages the user sent to the bot, "
        "including which earlier message each reply was to (in_reply_to); "
        "pass ack=true to consume them so the next ack'd read only shows "
        "newer ones.\n"
        "Limits: photos/documents are sent by public URL only (no file "
        "upload). Anything not listed above (stickers, audio, video, "
        "albums, editing sent messages) is unsupported — say so rather "
        "than improvising. Bot management: add_bot (also rotates a token "
        "when reusing a name) and remove_bot."),
)


@mcp.tool()
def list_bots() -> dict:
    """List configured bot names and which one is the default.

    Never returns tokens or chat ids.
    """
    registry = load_registry()
    return {"bots": sorted(registry.get("bots", {})),
            "default": registry.get("default")}


@mcp.tool()
def add_bot(name: str, token: str, chat_id: str, make_default: bool = False) -> str:
    """Register a bot (or update an existing one) in the registry.

    `token` is the @BotFather bot token, `chat_id` the destination chat.
    Verifies the token with Telegram before saving. Reusing an existing
    name overwrites that bot — this is also how you rotate a token.
    """
    me = tg_call(token, "getMe", {})
    registry = load_registry()
    registry.setdefault("bots", {})[name] = {"token": token, "chat_id": chat_id}
    if make_default or not registry.get("default"):
        registry["default"] = name
    save_registry(registry)
    return (f"saved bot {name!r} (@{me.get('username')}), "
            f"default={registry['default']!r}")


@mcp.tool()
def remove_bot(name: str) -> str:
    """Remove a bot from the registry."""
    registry = load_registry()
    if name not in registry.get("bots", {}):
        raise TgError(f"unknown bot {name!r}")
    del registry["bots"][name]
    if registry.get("default") == name:
        registry["default"] = next(iter(registry["bots"]), None)
    save_registry(registry)
    return f"removed {name!r}, default={registry.get('default')!r}"


@mcp.tool()
def send_message(text: str, bot: str | None = None,
                 parse_mode: str | None = None, silent: bool = False,
                 reply_to_message_id: int | None = None) -> dict:
    """Send a text notification to the bot's configured chat.

    parse_mode: None (plain), "HTML", or "MarkdownV2".
    silent: deliver without sound/vibration.
    """
    name, token, chat_id = resolve_bot(bot)
    msg = tg_call(token, "sendMessage", {
        "chat_id": chat_id, "text": text, "parse_mode": parse_mode,
        "disable_notification": silent or None,
        "reply_to_message_id": reply_to_message_id})
    return {"bot": name, "message_id": msg["message_id"]}


@mcp.tool()
def send_with_buttons(text: str, buttons: dict[str, str],
                      bot: str | None = None) -> dict:
    """Send text with tappable URL buttons; `buttons` maps label -> URL."""
    name, token, chat_id = resolve_bot(bot)
    keyboard = {"inline_keyboard": [[{"text": k, "url": v}
                                     for k, v in buttons.items()]]}
    msg = tg_call(token, "sendMessage", {
        "chat_id": chat_id, "text": text, "reply_markup": keyboard})
    return {"bot": name, "message_id": msg["message_id"]}


@mcp.tool()
def send_photo(photo_url: str, caption: str | None = None,
               bot: str | None = None) -> dict:
    """Send a photo by public URL with an optional caption.

    URL only — uploading local file content is not supported.
    """
    name, token, chat_id = resolve_bot(bot)
    msg = tg_call(token, "sendPhoto", {
        "chat_id": chat_id, "photo": photo_url, "caption": caption})
    return {"bot": name, "message_id": msg["message_id"]}


@mcp.tool()
def send_document(document_url: str, caption: str | None = None,
                  bot: str | None = None) -> dict:
    """Send a file by public URL with an optional caption.

    URL only — uploading local file content is not supported.
    """
    name, token, chat_id = resolve_bot(bot)
    msg = tg_call(token, "sendDocument", {
        "chat_id": chat_id, "document": document_url, "caption": caption})
    return {"bot": name, "message_id": msg["message_id"]}


@mcp.tool()
def send_location(latitude: float, longitude: float,
                  bot: str | None = None) -> dict:
    """Send a map pin at the given coordinates."""
    name, token, chat_id = resolve_bot(bot)
    msg = tg_call(token, "sendLocation", {
        "chat_id": chat_id, "latitude": latitude, "longitude": longitude})
    return {"bot": name, "message_id": msg["message_id"]}


@mcp.tool()
def send_venue(latitude: float, longitude: float, title: str, address: str,
               bot: str | None = None) -> dict:
    """Send a map pin labeled with a place name and address."""
    name, token, chat_id = resolve_bot(bot)
    msg = tg_call(token, "sendVenue", {
        "chat_id": chat_id, "latitude": latitude, "longitude": longitude,
        "title": title, "address": address})
    return {"bot": name, "message_id": msg["message_id"]}


@mcp.tool()
def send_poll(question: str, options: list[str], bot: str | None = None,
              quiz_correct_option: int | None = None,
              quiz_explanation: str | None = None,
              allows_multiple_answers: bool = False) -> dict:
    """Send a poll the user can vote on (2-10 options).

    Set quiz_correct_option (0-based index into options) to make it a quiz
    with one right answer; quiz_explanation is shown after answering.
    allows_multiple_answers only applies to regular polls, not quizzes.
    """
    name, token, chat_id = resolve_bot(bot)
    if not 2 <= len(options) <= 10:
        raise TgError("polls need 2-10 options")
    params = {"chat_id": chat_id, "question": question, "options": options}
    if quiz_correct_option is not None:
        if not 0 <= quiz_correct_option < len(options):
            raise TgError(f"quiz_correct_option must be 0..{len(options) - 1}")
        params.update({"type": "quiz",
                       "correct_option_id": quiz_correct_option,
                       "explanation": quiz_explanation})
    else:
        params["allows_multiple_answers"] = allows_multiple_answers or None
    msg = tg_call(token, "sendPoll", params)
    return {"bot": name, "message_id": msg["message_id"]}


@mcp.tool()
def send_dice(emoji: str = "🎲", bot: str | None = None) -> dict:
    """Send an animated emoji that lands on a random value.

    emoji must be one of: 🎲 🎯 🏀 ⚽ 🎳 🎰
    """
    allowed = {"🎲", "🎯", "🏀", "⚽", "🎳", "🎰"}
    if emoji not in allowed:
        raise TgError(f"emoji must be one of {' '.join(sorted(allowed))}")
    name, token, chat_id = resolve_bot(bot)
    msg = tg_call(token, "sendDice", {"chat_id": chat_id, "emoji": emoji})
    return {"bot": name, "message_id": msg["message_id"],
            "value": msg.get("dice", {}).get("value")}


@mcp.tool()
def send_contact(phone_number: str, first_name: str,
                 last_name: str | None = None,
                 bot: str | None = None) -> dict:
    """Send a contact card (phone number + name)."""
    name, token, chat_id = resolve_bot(bot)
    msg = tg_call(token, "sendContact", {
        "chat_id": chat_id, "phone_number": phone_number,
        "first_name": first_name, "last_name": last_name})
    return {"bot": name, "message_id": msg["message_id"]}


@mcp.tool()
def read_replies(bot: str | None = None, ack: bool = False) -> list[dict]:
    """Read incoming messages sent to the bot from its configured chat.

    Each item has message_id, from, date, text, and — when the message was
    a reply — in_reply_to {message_id, text}. With ack=True the returned
    messages are consumed: the next ack'd read only shows newer ones.
    Note: does not work if a webhook is set on the bot.
    """
    name, token, chat_id = resolve_bot(bot)
    updates = tg_call(token, "getUpdates",
                      {"timeout": 0, "allowed_updates": ["message"]})
    out = []
    for u in updates:
        msg = u.get("message")
        if not msg or str(msg.get("chat", {}).get("id")) != chat_id:
            continue
        item = {"bot": name, "message_id": msg["message_id"],
                "from": msg.get("from", {}).get("first_name"),
                "date": msg.get("date"),
                "text": msg.get("text") or msg.get("caption")}
        reply = msg.get("reply_to_message")
        if reply:
            item["in_reply_to"] = {
                "message_id": reply["message_id"],
                "text": reply.get("text") or reply.get("caption")}
        out.append(item)
    if ack and updates:
        tg_call(token, "getUpdates",
                {"offset": max(u["update_id"] for u in updates) + 1,
                 "timeout": 0})
    return out


def main() -> None:
    secret = os.environ.get("MCP_PATH_SECRET", "")
    path = f"/{secret}/mcp" if secret else "/mcp"
    if not secret:
        print("WARNING: MCP_PATH_SECRET unset — endpoint is guessable (/mcp)")
    mcp.run_streamable_http_async  # attribute check before asyncio import
    import asyncio
    asyncio.run(mcp.run_streamable_http_async(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8080")),
        streamable_http_path=path,
        stateless_http=True,
        json_response=True,
    ))


if __name__ == "__main__":
    main()
