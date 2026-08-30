#!/usr/bin/env bash
# botctl — manage the Teleping bot registry from your local machine.
#
# Edits the registry JSON in GCS directly, so bot tokens never pass through
# a chat transcript. Changes take effect on the server's next request — no
# redeploy or restart needed.
#
# Requires: gcloud/gsutil (authenticated), python3, curl.
#
# Usage:
#   BUCKET=my-project-teleping-bots ./botctl.sh list
#   BUCKET=... ./botctl.sh add <name> <token> <chat_id> [--default]
#   BUCKET=... ./botctl.sh rotate <name> <new_token>
#   BUCKET=... ./botctl.sh remove <name>
#   BUCKET=... ./botctl.sh set-default <name>
#
# Examples:
#   BUCKET=myproj-teleping-bots ./botctl.sh add alerts 123456:ABC... 8596273711
#   BUCKET=myproj-teleping-bots ./botctl.sh rotate personal 987654:XYZ...
#
# Tip: export BUCKET in your shell profile so you can drop the prefix.
set -euo pipefail

BUCKET="${BUCKET:?Set BUCKET to your registry bucket (e.g. <project>-teleping-bots)}"
OBJECT="${OBJECT:-teleping-bots.json}"
GCS_PATH="gs://${BUCKET}/${OBJECT}"
CMD="${1:?usage: botctl.sh list|add|rotate|remove|set-default ...}"
shift

fetch_registry() {
  gsutil cat "${GCS_PATH}" 2>/dev/null || echo '{"default": null, "bots": {}}'
}

# Run a python transform over the registry and upload the result. Read,
# transform, and write are separate steps so a failed transform never
# uploads partial or empty output.
update_registry() {
  local current updated
  current="$(fetch_registry)"
  updated="$(printf '%s' "${current}" | python3 -c "$1")"
  printf '%s' "${updated}" | gsutil -q cp - "${GCS_PATH}"
}

verify_token() {  # exits with a clear error if Telegram rejects the token
  curl -s "https://api.telegram.org/bot$1/getMe" | python3 -c '
import json, sys
r = json.load(sys.stdin)
if not r.get("ok"):
    desc = r.get("description")
    sys.exit(f"error: Telegram rejected the token: {desc}")
user = r["result"]["username"]
print(f"token ok: @{user}")'
}

case "${CMD}" in
  list)
    fetch_registry | python3 -c '
import json, sys
r = json.load(sys.stdin)
bots = r.get("bots", {})
if not bots:
    print("(no bots)")
for name, cfg in sorted(bots.items()):
    marker = " (default)" if name == r.get("default") else ""
    tok, cid = cfg["token"], cfg["chat_id"]
    print(f"  {name}{marker}: token={tok[:6]}...{tok[-4:]} chat_id={cid}")'
    ;;

  add)
    NAME="${1:?add <name> <token> <chat_id> [--default]}"
    TOKEN="${2:?missing token}"
    CHAT_ID="${3:?missing chat_id}"
    MAKE_DEFAULT="${4:-}"
    verify_token "${TOKEN}"
    export NAME TOKEN CHAT_ID MAKE_DEFAULT
    update_registry '
import json, os, sys
r = json.load(sys.stdin)
r.setdefault("bots", {})[os.environ["NAME"]] = {
    "token": os.environ["TOKEN"], "chat_id": os.environ["CHAT_ID"]}
if os.environ["MAKE_DEFAULT"] == "--default" or not r.get("default"):
    r["default"] = os.environ["NAME"]
json.dump(r, sys.stdout, indent=2)'
    echo "saved bot '${NAME}'"
    ;;

  rotate)
    NAME="${1:?rotate <name> <new_token>}"
    TOKEN="${2:?missing new token}"
    verify_token "${TOKEN}"
    export NAME TOKEN
    update_registry '
import json, os, sys
r = json.load(sys.stdin)
name = os.environ["NAME"]
if name not in r.get("bots", {}):
    sys.exit(f"error: unknown bot {name!r}; run: botctl.sh list")
r["bots"][name]["token"] = os.environ["TOKEN"]
json.dump(r, sys.stdout, indent=2)'
    echo "rotated token for '${NAME}' (chat_id unchanged)"
    echo "reminder: revoke the OLD token in @BotFather if you have not already"
    ;;

  remove)
    NAME="${1:?remove <name>}"
    export NAME
    update_registry '
import json, os, sys
r = json.load(sys.stdin)
name = os.environ["NAME"]
if name not in r.get("bots", {}):
    sys.exit(f"error: unknown bot {name!r}")
del r["bots"][name]
if r.get("default") == name:
    r["default"] = next(iter(r["bots"]), None)
json.dump(r, sys.stdout, indent=2)'
    echo "removed '${NAME}'"
    ;;

  set-default)
    NAME="${1:?set-default <name>}"
    export NAME
    update_registry '
import json, os, sys
r = json.load(sys.stdin)
name = os.environ["NAME"]
if name not in r.get("bots", {}):
    sys.exit(f"error: unknown bot {name!r}")
r["default"] = name
json.dump(r, sys.stdout, indent=2)'
    echo "default is now '${NAME}'"
    ;;

  *)
    echo "error: unknown command '${CMD}' (use list|add|rotate|remove|set-default)" >&2
    exit 1
    ;;
esac
