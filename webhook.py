# webhook.py

import os
import threading
from dotenv import load_dotenv
from flask import Flask, request, abort
from send_message import send_instagram_message
from agency_swarm import set_openai_key
from agency import Agency

# ─── 1. Încărcare și validare variabile de mediu ───────────────────────────
load_dotenv()

FB_APP_ID                     = os.getenv("FB_APP_ID")
FB_APP_SECRET                 = os.getenv("FB_APP_SECRET")
IG_VERIFY_TOKEN               = os.getenv("IG_VERIFY_TOKEN")
IG_ACCESS_TOKEN               = os.getenv("INSTAGRAM_ACCESS_TOKEN")
INSTAGRAM_BUSINESS_ACCOUNT_ID = os.getenv("INSTAGRAM_BUSINESS_ACCOUNT_ID")
OPENAI_API_KEY                = os.getenv("OPENAI_API_KEY")
DEFAULT_REPLY                 = os.getenv("DEFAULT_RESPONSE_MESSAGE", "Agent unavailable right now.")

_missing = [
    name for name in (
        "FB_APP_ID",
        "FB_APP_SECRET",
        "IG_VERIFY_TOKEN",
        "INSTAGRAM_ACCESS_TOKEN",
        "INSTAGRAM_BUSINESS_ACCOUNT_ID",
        "OPENAI_API_KEY",
    )
    if not os.getenv(name)
]
if _missing:
    raise RuntimeError(f"❌ Missing env vars: {', '.join(_missing)}")

set_openai_key(OPENAI_API_KEY)

# ─── 2. Aplicația Flask ────────────────────────────────────────────────────
app = Flask(__name__)

# ─── 3. Health check ──────────────────────────────────────────────────────
@app.route("/health", methods=["GET"])
def health():
    return "ok", 200

# ─── 4. Handshake GET pentru Facebook webhook ──────────────────────────────
@app.route("/webhook", methods=["GET"])
def webhook_verify():
    mode      = request.args.get("hub.mode")
    token     = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == IG_VERIFY_TOKEN:
        return challenge, 200
    abort(403)

# ─── 5. Endpoint principal webhook Instagram (POST) ───────────────────────
@app.route("/webhook", methods=["POST"])
def webhook():
    # ════════════════════════════════════════════════
    # TEMPORARY BYPASS: skip HMAC verification until
    # FB_APP_SECRET is correctly configured!
    # ════════════════════════════════════════════════
    # verify_signature(request)

    data = request.get_json()
    if not data or "entry" not in data:
        abort(400, description="Malformed webhook payload")

    for entry in data["entry"]:
        for event in entry.get("messaging", []):
            sender_id = event.get("sender", {}).get("id")
            user_text = event.get("message", {}).get("text")
            if sender_id and user_text:
                threading.Thread(
                    target=process_and_reply,
                    args=(sender_id, user_text),
                    daemon=True
                ).start()

    return "OK", 200

# ─── 6. Procesare și răspuns cu OpenAI + trimitere mesaj Instagram ────────
def process_and_reply(sender_id, message_text):
    try:
        completion = Agency.chat(
            system="You are an Instagram support bot.",
            user=message_text
        )
        reply = completion.choices[0].message.content
    except Exception as e:
        print(f"Error generating reply: {e}")
        reply = DEFAULT_REPLY

    send_instagram_message(
        recipient_id=sender_id,
        message_text=reply
    )

# ─── 7. Pornire server ────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
