import os
import threading
import hmac
import hashlib
from dotenv import load_dotenv
from flask import Flask, request, abort
from send_message import send_instagram_message
from agency_swarm import set_openai_key
from agency import Agency

# ─── 1. Încărcare și validare variabile de mediu ───────────────────────────
load_dotenv()

FB_APP_ID                      = os.getenv("FB_APP_ID")
FB_APP_SECRET                  = os.getenv("FB_APP_SECRET")
IG_VERIFY_TOKEN                = os.getenv("IG_VERIFY_TOKEN")
# În .env: INSTAGRAM_ACCESS_TOKEN
IG_ACCESS_TOKEN                = os.getenv("INSTAGRAM_ACCESS_TOKEN")
INSTAGRAM_BUSINESS_ACCOUNT_ID  = os.getenv("INSTAGRAM_BUSINESS_ACCOUNT_ID")
OPENAI_API_KEY                 = os.getenv("OPENAI_API_KEY")
DEFAULT_REPLY                  = os.getenv("DEFAULT_RESPONSE_MESSAGE", "Agent unavailable right now.")

missing = [name for name in (
    "FB_APP_ID", "FB_APP_SECRET", "IG_VERIFY_TOKEN",
    "INSTAGRAM_ACCESS_TOKEN", "INSTAGRAM_BUSINESS_ACCOUNT_ID",
    "OPENAI_API_KEY"
) if not os.getenv(name)]
if missing:
    raise RuntimeError(f"❌ Missing env vars: {', '.join(missing)}")

# Configure OpenAI
set_openai_key(OPENAI_API_KEY)

app = Flask(__name__)

# ─── 2. Health check ──────────────────────────────────────────────────────
@app.route("/health", methods=["GET"])
def health():
    return "ok", 200

# ─── 3. Verificare webhook (GET) ──────────────────────────────────────────
@app.route("/webhook", methods=["GET"])
def webhook_verify():
    mode      = request.args.get("hub.mode")
    token     = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode == "subscribe" and token == IG_VERIFY_TOKEN:
        return challenge, 200
    abort(403)

# ─── 4. Verificare semnătură HMAC (POST) ─────────────────────────────────
def verify_signature(req):
    sig_header = req.headers.get("X-Hub-Signature-256")
    if not sig_header:
        abort(403)
    method, signature = sig_header.split("=", 1)
    payload = req.get_data()
    expected = hmac.new(
        FB_APP_SECRET.encode(),
        payload,
        hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(signature, expected):
        abort(403)

# ─── 5. Endpoint principal webhook Instagram (POST) ───────────────────────
@app.route("/webhook", methods=["POST"])
def webhook():
    verify_signature(request)

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

# ─── 6. Procesare și răspuns cu OpenAI + trimis mesaj Instagram ──────────
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

    # send_instagram_message așteaptă intern IG_ACCESS_TOKEN
    send_instagram_message(
        recipient_id=sender_id,
        message_text=reply,
        access_token=IG_ACCESS_TOKEN
    )

# ─── 7. Pornire server ────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
