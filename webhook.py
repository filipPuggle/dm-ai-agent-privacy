import os
import json
import hmac
import hashlib
import logging

from dotenv import load_dotenv
from flask import (
    Flask, request, abort,
    make_response, send_from_directory, jsonify
)
from agency_swarm import set_openai_key
from send_message import send_instagram_message

# 1️⃣ Load .env
load_dotenv()

# 2️⃣ Configurează cheia OpenAI
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
if not OPENAI_API_KEY:
    raise RuntimeError("💥 Trebuie să setezi OPENAI_API_KEY în environment variables!")
set_openai_key(OPENAI_API_KEY)

# 3️⃣ Importă instanța corectă din agency.py
from agency import agency      # ← aici importăm exact 'agency' definit mai sus

# 4️⃣ Configurare logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 5️⃣ Creează aplicația Flask
app = Flask(__name__)
app.logger.setLevel(logging.INFO)

# 6️⃣ Token-uri Instagram Webhook
VERIFY_TOKEN = os.getenv("IG_VERIFY_TOKEN", "")
APP_SECRET   = os.getenv("IG_APP_SECRET", "")

def verify_signature(req):
    sig = req.headers.get("X-Hub-Signature-256")
    if not APP_SECRET or not sig:
        logger.warning("Skipping signature verification (dev).")
        return True
    expected = "sha256=" + hmac.new(
        APP_SECRET.encode(), req.data, hashlib.sha256
    ).hexdigest()
    valid = hmac.compare_digest(expected, sig)
    if not valid:
        logger.error("Invalid signature: expected %s but got %s", expected, sig)
    return valid

# 🔵 Healthcheck endpoint (Railway)
@app.route("/health", methods=["GET"])
def health():
    return jsonify(status="ok"), 200

@app.route("/", methods=["GET"])
def hello():
    return "<p>Hello, World!</p>"

@app.route("/privacy_policy", methods=["GET"])
def privacy_policy():
    return send_from_directory(
        directory=".", filename="privacy_policy.html", mimetype="text/html"
    )

@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    # — GET: verificare webhook în Meta UI —
    if request.method == "GET":
        mode      = request.args.get("hub.mode")
        challenge = request.args.get("hub.challenge")
        token     = request.args.get("hub.verify_token")
        if mode == "subscribe" and token == VERIFY_TOKEN:
            return make_response(challenge, 200)
        logger.error("Webhook verification failed.")
        return abort(403)

    # — POST: semnătură + procesare eveniment —
    if not verify_signature(request):
        return abort(403)

    payload = request.get_json(force=True)
    logger.info("Payload:\n%s", json.dumps(payload, indent=2))

    for entry in payload.get("entry", []):
        for msg in entry.get("messaging", []):
            sender_id     = msg.get("sender", {}).get("id")
            incoming_text = msg.get("message", {}).get("text", "")
            logger.info("Msg from %s: %s", sender_id, incoming_text)

            # Obține răspuns prin Agency Swarm
            try:
                reply = agency.get_completion(incoming_text)
                logger.info("Reply: %s", reply)
            except Exception as e:
                logger.error("Error in agent.get_completion: %s", e)
                reply = "Îmi pare rău, a apărut o eroare."

            # Trimite înapoi
            try:
                resp = send_instagram_message(sender_id, reply)
                logger.info("Sent to %s: %s", sender_id, resp)
            except Exception as e:
                logger.error("Error sending message: %s", e)

    return make_response("", 200)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    app.run(host="0.0.0.0", port=port)
