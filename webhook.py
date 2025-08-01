# webhook.py

import os
import threading
import openai
from dotenv import load_dotenv
from flask import Flask, request, abort
from send_message import send_instagram_message

# ─── 1. Load & validate env vars ───────────────────────────────────────────
load_dotenv()

IG_VERIFY_TOKEN               = os.getenv("IG_VERIFY_TOKEN")
OPENAI_API_KEY                = os.getenv("OPENAI_API_KEY")
INSTAGRAM_ACCESS_TOKEN        = os.getenv("INSTAGRAM_ACCESS_TOKEN")
INSTAGRAM_BUSINESS_ACCOUNT_ID = os.getenv("INSTAGRAM_BUSINESS_ACCOUNT_ID")
DEFAULT_REPLY                 = os.getenv(
    "DEFAULT_RESPONSE_MESSAGE",
    "Agent unavailable right now."
)

_missing = [n for n in (
    "IG_VERIFY_TOKEN",
    "OPENAI_API_KEY",
    "INSTAGRAM_ACCESS_TOKEN",
    "INSTAGRAM_BUSINESS_ACCOUNT_ID",
) if not os.getenv(n)]
if _missing:
    raise RuntimeError(f"❌ Missing env var(s): {', '.join(_missing)}")

openai.api_key = OPENAI_API_KEY

# ─── 2. Flask setup ───────────────────────────────────────────────────────
app = Flask(__name__)

@app.route("/health", methods=["GET"])
def health():
    return "ok", 200

# Facebook webhook handshake
@app.route("/webhook", methods=["GET"])
def webhook_verify():
    mode      = request.args.get("hub.mode")
    token     = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == IG_VERIFY_TOKEN:
        return challenge, 200
    abort(403)

# MAIN POST: HMAC temporarily disabled
@app.route("/webhook", methods=["POST"])
def webhook():
    # verify_signature(request)

    data = request.get_json()
    if not data or "entry" not in data:
        abort(400, description="Invalid payload")

    for entry in data["entry"]:
        for ev in entry.get("messaging", []):
            sender = ev.get("sender", {}).get("id")
            text   = ev.get("message", {}).get("text")
            if sender and text:
                threading.Thread(
                    target=process_and_reply,
                    args=(sender, text),
                    daemon=True
                ).start()

    return "OK", 200

def process_and_reply(sender_id, message_text):
    # 1) Generate reply via new OpenAI v1.0+ interface
    try:
        resp = openai.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are an Instagram support bot."},
                {"role": "user",   "content": message_text}
            ]
        )
        reply = resp.choices[0].message.content
    except Exception as e:
        print(f"❌ OpenAI error: {e}")
        reply = DEFAULT_REPLY

    # 2) Send DM via Graph API (with message_type)
    try:
        send_instagram_message(sender_id, reply)
    except Exception as e:
        print(f"❌ Instagram send error: {e}")

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
