import os
import hmac
import hashlib
from flask import Flask, request, abort, jsonify
from dotenv import load_dotenv
from agency import agent
from agency_swarm.util.oai import set_openai_key

# ─── setup ─────────────────────────────────────────────
load_dotenv()  # încarcă .env
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise RuntimeError("⚠️ OPENAI_API_KEY nu e setat")
set_openai_key(OPENAI_API_KEY)

WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")
if not WEBHOOK_SECRET:
    raise RuntimeError("⚠️ WEBHOOK_SECRET nu e setat")

app = Flask(__name__)

# ─── health endpoint ───────────────────────────────────
@app.route("/health", methods=["GET"])
def health():
    return jsonify(status="ok")

# ─── helper pentru HMAC SHA256 ─────────────────────────
def verify_signature(payload: bytes, sig_header: str) -> bool:
    mac = hmac.new(WEBHOOK_SECRET.encode(), payload, hashlib.sha256)
    expected = f"sha256={mac.hexdigest()}"
    return hmac.compare_digest(expected, sig_header)

# ─── webhook endpoint ──────────────────────────────────
@app.route("/webhook", methods=["POST"])
def webhook():
    sig = request.headers.get("X-Hub-Signature-256", "")
    body = request.get_data()  # raw bytes
    if not verify_signature(body, sig):
        app.logger.error(f"Invalid signature: got {sig}")
        abort(403)

    try:
        data = request.get_json(force=True)
    except Exception as e:
        app.logger.error(f"Bad JSON: {e}")
        abort(400)

    # aici procesezi payload-ul cu agent:
    # ex: agent.handle_webhook(data)
    agent.handle_webhook(data)

    return ("", 204)

# ─── bootstrap local ───────────────────────────────────
if __name__ == "__main__":
    port = int(os.getenv("PORT", 3000))
    app.run(host="0.0.0.0", port=port)
