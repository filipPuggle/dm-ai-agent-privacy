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
IG_VERIFY_TOKEN               = os.getenv("IG_VERIFY_TOKEN")
IG_APP_SECRET                 = os.getenv("IG_APP_SECRET")
OPENAI_API_KEY                = os.getenv("OPENAI_API_KEY")
INSTAGRAM_ACCESS_TOKEN        = os.getenv("INSTAGRAM_ACCESS_TOKEN")
INSTAGRAM_BUSINESS_ACCOUNT_ID = os.getenv("INSTAGRAM_BUSINESS_ACCOUNT_ID")
DEFAULT_REPLY                 = os.getenv(
    "DEFAULT_RESPONSE_MESSAGE",
    "Agent unavailable right now."
)

_missing = [
    name for name, val in (
        ("IG_VERIFY_TOKEN", IG_VERIFY_TOKEN),
        ("IG_APP_SECRET", IG_APP_SECRET),
        ("OPENAI_API_KEY", OPENAI_API_KEY),
        ("INSTAGRAM_ACCESS_TOKEN", INSTAGRAM_ACCESS_TOKEN),
        ("INSTAGRAM_BUSINESS_ACCOUNT_ID", INSTAGRAM_BUSINESS_ACCOUNT_ID),
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
    abort(403)

# ─── 4. HMAC signature check ──────────────────────────────────────────────
def verify_signature(req):
    sig256 = req.headers.get("X-Hub-Signature-256")
    sig1   = req.headers.get("X-Hub-Signature")
    sig    = sig256 or sig1
    if not sig:
        abort(403)

    algo = hashlib.sha256 if sig.startswith("sha256=") else hashlib.sha1
    received = sig.split("=",1)[1]
    body     = req.get_data()
    expected = hmac.new(IG_APP_SECRET.encode(), body, algo).hexdigest()
    if not hmac.compare_digest(received, expected):
        abort(403)

# ─── 5. Main webhook endpoint (POST) ──────────────────────────────────────
@app.route("/webhook", methods=["POST"])
def webhook():
    verify_signature(request)

    data = request.get_json()
    if not data or "entry" not in data:
        abort(400, "Invalid payload")

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

# ─── 6. Process and reply ─────────────────────────────────────────────────
def process_and_reply(sender_id, message_text):
    # 1) Generate reply via OpenAI v1.0+ SDK
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
