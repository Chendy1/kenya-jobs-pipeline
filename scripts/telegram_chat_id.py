"""Print the chat id(s) that have messaged your bot. Send your bot a message first.
Never prints the token."""
import os

import requests
from dotenv import load_dotenv

load_dotenv()
token = os.environ["TELEGRAM_BOT_TOKEN"]
try:
    data = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=20).json()
except requests.RequestException as exc:
    raise SystemExit(f"Request failed ({type(exc).__name__})")
if not data.get("ok"):
    raise SystemExit(f"Telegram said: {data.get('description')}")

seen = {}
for update in data.get("result", []):
    chat = (update.get("message") or {}).get("chat") or {}
    if chat.get("id") is not None:
        seen[chat["id"]] = chat.get("first_name") or chat.get("title") or chat.get("username")
if not seen:
    print("No messages yet: send your bot any message, then run this again.")
for chat_id, name in seen.items():
    print(f"chat_id={chat_id}  ({name})")