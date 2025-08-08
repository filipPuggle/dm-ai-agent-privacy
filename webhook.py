# webhook.py
import os
import threading
import hmac
import hashlib
from dotenv import load_dotenv
from flask import Flask, request, abort
import openai

from send_message import send_instagram_message

# ─── 1. Load & validate env vars ───────────────────────────────────────────
load_dotenv()

FB_APP_ID        = os.getenv("FB_APP_ID")
FB_APP_SECRET    = os.getenv("FB_APP_SECRET")
IG_APP_ID        = os.getenv("IG_APP_ID")
IG_APP_SECRET    = os.getenv("IG_APP_SECRET")
IG_ACCOUNT_ID    = os.getenv("IG_ACCOUNT_ID")
IG_ACCESS_TOKEN  = os.getenv("IG_ACCESS_TOKEN")
IG_VERIFY_TOKEN  = os.getenv("IG_VERIFY_TOKEN")
USER_TOKEN       = os.getenv("USER_TOKEN")
OPENAI_API_KEY   = os.getenv("OPENAI_API_KEY")

_missing = [
    name for name, val in (
        ("FB_APP_ID", FB_APP_ID),
        ("FB_APP_SECRET", FB_APP_SECRET),
        ("IG_APP_ID", IG_APP_ID),
        ("IG_APP_SECRET", IG_APP_SECRET),
        ("IG_ACCOUNT_ID", IG_ACCOUNT_ID),
        ("IG_ACCESS_TOKEN", IG_ACCESS_TOKEN),
        ("IG_VERIFY_TOKEN", IG_VERIFY_TOKEN),
        ("USER_TOKEN", USER_TOKEN),
        ("OPENAI_API_KEY", OPENAI_API_KEY),
    ) if not val
]
if _missing:
    raise RuntimeError(f"❌ Missing env vars: {', '.join(_missing)}")

openai.api_key = OPENAI_API_KEY

# ─── 2. Flask setup ───────────────────────────────────────────────────────
app = Flask(__name__)

@app.route("/health", methods=["GET"])
def health():
    return "ok", 200

# ─── 3. Webhook verification (GET) ────────────────────────────────────────
@app.route("/webhook", methods=["GET"])
def webhook_verify():
    mode      = request.args.get("hub.mode")
    token     = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == IG_VERIFY_TOKEN:
        return challenge, 200
    return "Forbidden", 403

# ─── 4. Webhook receiver (POST) ───────────────────────────────────────────
@app.route("/webhook", methods=["POST"])
def webhook_receive():
    # verificare HMAC SHA1 a payload-ului
    signature = request.headers.get("X-Hub-Signature")
    body = request.get_data()
    expected_sig = hmac.new(
        IG_APP_SECRET.encode(),
        body,
        hashlib.sha1
    ).hexdigest()
    if not signature or not signature.split("=")[1] == expected_sig:
        abort(403)

    data = request.json
    for entry in data.get("entry", []):
        for msg in entry.get("messaging", []):
            sender_id = msg["sender"]["id"]
            text = msg.get("message", {}).get("text")
            if text:
                threading.Thread(
                    target=process_and_reply,
                    args=(sender_id, text),
                    daemon=True
                ).start()
    return "OK", 200

# ─── 5. Process and reply ─────────────────────────────────────────────────
DEFAULT_REPLY = os.getenv("DEFAULT_RESPONSE_MESSAGE", "Agent unavailable right now.")

def process_and_reply(sender_id, message_text):
    # 1) Generate reply via OpenAI
    try:
        resp = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are an Instagram support bot."},
                {"role": "user",   "content": message_text}
            ]
        )
        reply = resp.choices[0].message.content
    except Exception as e:
        print("❌ OpenAI error:", e)
        reply = DEFAULT_REPLY

    # 2) Send DM via Instagram Graph API
    try:
        send_instagram_message(sender_id, reply)
    except Exception as e:
        print("❌ Instagram send error:", e)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8080")))

