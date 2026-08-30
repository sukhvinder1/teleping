#!/usr/bin/env bash
# addbot — register a new Telegram bot with just its token.
#
# Derives the registry name from the bot's own @username (via getMe),
# and the chat_id from the most recent message you've sent it (via
# getUpdates) — so you only need to message the bot once, then run this.
#
# Usage:
#   BUCKET=my-project-teleping-bots ./addbot.sh <token> [--default]
#
# Example:
#   BUCKET=sukh-mcp-teleping-bots ./addbot.sh 8786274884:AAExxxxx
set -euo pipefail

: "${BUCKET:?Set BUCKET to your registry bucket (e.g. <project>-teleping-bots)}"
TOKEN="${1:?usage: addbot.sh <token> [--default]}"
MAKE_DEFAULT="${2:-}"

ME_JSON="$(curl -s "https://api.telegram.org/bot${TOKEN}/getMe")"
NAME="$(printf '%s' "${ME_JSON}" | python3 -c '
import json, sys, re
r = json.load(sys.stdin)
if not r.get("ok"):
    sys.exit("error: Telegram rejected the token: " + str(r.get("description")))
username = r["result"]["username"]
# the_munim_bot -> the-munim
name = re.sub(r"_bot$", "", username)
name = name.replace("_", "-")
print(name)')"
echo "bot username resolved to name: ${NAME}"

UPDATES_JSON="$(curl -s "https://api.telegram.org/bot${TOKEN}/getUpdates")"
CHAT_ID="$(printf '%s' "${UPDATES_JSON}" | python3 -c '
import json, sys
r = json.load(sys.stdin)
results = r.get("result", [])
if not results:
    sys.exit("error: no messages found yet — message this bot once in Telegram, then re-run")
chat = results[-1].get("message", {}).get("chat", {})
chat_id = chat.get("id")
if chat_id is None:
    sys.exit("error: could not find a chat id in the latest update")
print(chat_id)')"
echo "chat_id resolved to: ${CHAT_ID}"

BUCKET="${BUCKET}" ./botctl.sh add "${NAME}" "${TOKEN}" "${CHAT_ID}" "${MAKE_DEFAULT}"
