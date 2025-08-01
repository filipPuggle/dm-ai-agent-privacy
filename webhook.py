# webhook.py

import os
import threading
from dotenv import load_dotenv
from flask import Flask, request, abort
from send_message import send_instagram_message
from agency_swarm import set_openai_key
from agency import Agency

# ─── 1. Load & validate env vars ───────────────────────────────────────────
load_dotenv()

FB_APP_ID                     = os.getenv("FB_APP_ID")
FB_APP_SECRET                 = os.getenv("FB_APP_SECRET")
IG_VERIFY_TOKEN               = os.getenv("IG_VERIFY_TOKEN")
IG_ACCESS_TOKEN               = os.getenv("INSTAGRAM_ACCESS_TOKEN")
INSTAGRAM_BUSINESS_ACCOUNT_ID = os.getenv("INSTAGRAM_BUSINESS_ACCOUNT_ID")
OPENAI_API_KEY                = os.getenv("OPENAI_API_KEY")
DEFAULT_REPLY                 = os.getenv(
    "DEFAULT_RESPONSE_MESSAGE",
    "Agent unavailable right now."
)

_missing = [n for n in (
    "FB_APP_ID",
    "FB_APP_SECRET",
    "IG_VERIFY_TOKEN",
    "INSTAGRAM_ACCESS_TOKEN",
    "INSTAGRAM_BUSINESS_ACCOUNT_ID",
    "OPENAI_API_KEY",
) if not os.getenv(n)]
if _missing:
    raise RuntimeError(f"❌ Missing env vars: {', '.join(_missing)}")

# configure Agency Swarm
set_openai_key(OPENAI_API_KEY)
agent = Agency()

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

# MAIN POST — HMAC verification temporarily disabled
@app.route("/webhook", methods=["POST"])
def webhook():
    # ⚠️ Temporarily skipping verify_signature(request)
    # verify_signature(request)

    data = request.get_json()
    if not data or "entry" not in data:
        abort(400, description="Malformed webhook payload")

    for entry in data["entry"]:
        for event in entry.get("messaging", []):
            sender_id = event.get("sender", {}).get("id")
            text      = event.get("message", {}).get("text")
            if sender_id and text:
                threading.Thread(
                    target=process_and_reply,
                    args=(sender_id, text),
                    daemon=True
                ).start()

    return "OK", 200

def process_and_reply(sender_id, message_text):
    try:
        resp = agent.chat(
            system="You are an Instagram support bot.",
            user=message_text
        )
        reply = resp.choices[0].message.content
    except Exception as e:
        print(f"❌ Agent error: {e}")
        reply = DEFAULT_REPLY

    try:
        send_instagram_message(sender_id, reply)
    except Exception as e:
        print(f"❌ IG send error: {e}")

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
