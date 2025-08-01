import os
import threading
from dotenv import load_dotenv
from flask import Flask, request, abort
from send_message import send_instagram_message
from agency_swarm import set_openai_key
from agency import Agency

# ─── 1. Load .env and initialise Agency Swarm ────────────────────────────
load_dotenv()
API_KEY         = os.getenv("OPENAI_API_KEY")
IG_VERIFY_TOKEN = os.getenv("IG_VERIFY_TOKEN")
IG_ACCESS_TOKEN = os.getenv("INSTAGRAM_ACCESS_TOKEN")
DEFAULT_REPLY   = os.getenv("DEFAULT_RESPONSE_MESSAGE", "Agent unavailable right now.")

if not all([API_KEY, IG_VERIFY_TOKEN, IG_ACCESS_TOKEN]):
    raise RuntimeError("Missing OPENAI_API_KEY, IG_VERIFY_TOKEN or INSTAGRAM_ACCESS_TOKEN")

set_openai_key(API_KEY)
agent = Agency().init_oai()

app = Flask(__name__)

# ─── 2. Webhook verification (GET) ───────────────────────────────────────
@app.route("/webhook", methods=["GET"])
def verify_webhook():
    mode      = request.args.get("hub.mode")
    token     = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode == "subscribe" and token == IG_VERIFY_TOKEN:
        return challenge, 200
    return "Forbidden", 403

# ─── 3. Health check ─────────────────────────────────────────────────────
@app.route("/health", methods=["GET"])
def health():
    return "ok", 200

# ─── 4. Background worker function ───────────────────────────────────────
def process_and_reply(sender_id: str, user_text: str):
    try:
        reply = agent.get_completion(user_text)
    except Exception:
        reply = DEFAULT_REPLY

    send_instagram_message(
        recipient_id=sender_id,
        message_text=reply,
        access_token=IG_ACCESS_TOKEN
    )

# ─── 5. Incoming message handler (POST) ─────────────────────────────────
@app.route("/webhook", methods=["POST"])
def handle_messages():
    data = request.get_json(force=True)

    try:
        entry     = data["entry"][0]
        message   = entry["messaging"][0]
        sender_id = message["sender"]["id"]
        user_text = message["message"]["text"].strip()
    except Exception:
        abort(400, description="Malformed webhook payload")

    if user_text:
        threading.Thread(
            target=process_and_reply,
            args=(sender_id, user_text),
            daemon=True
        ).start()

    return "OK", 200

# ─── 6. Run locally ──────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
