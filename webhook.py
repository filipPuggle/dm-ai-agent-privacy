import os
import json
import hmac
import hashlib
import logging

from dotenv import load_dotenv
from flask import Flask, request, abort, make_response, send_from_directory, jsonify
from agency_swarm import set_openai_key
from send_message import send_instagram_message
from agency import agent                # ← importăm instanța din agency.py

# --- 1. Load env vars ---
load_dotenv()

# --- 2. Set OpenAI key în clientul agency_swarm ---
OPENAI_KEY = os.getenv("OPENAI_API_KEY", "")
if not OPENAI_KEY:
    raise RuntimeError("💥 OPENAI_API_KEY nu e setată!")
set_openai_key(OPENAI_KEY)

# --- 3. Configurare logging ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- 4. Creare Flask app ---
app = Flask(__name__)
app.logger.setLevel(logging.INFO)

# --- 5. Token-uri Instagram Webhook ---
VERIFY_TOKEN = os.getenv("IG_VERIFY_TOKEN")
APP_SECRET   = os.getenv("IG_APP_SECRET", "")

def verify_signature(req):
    signature = req.headers.get("X-Hub-Signature-256")
    if not APP_SECRET or not signature:
        logger.warning("Skipping signature verification (dev mode).")
        return True
    expected = "sha256=" + hmac.new(APP_SECRET.encode(), req.data, hashlib.sha256).hexdigest()
    valid = hmac.compare_digest(expected, signature)
    if not valid:
        logger.error("Invalid signature: expected %s but got %s", expected, signature)
    return valid

# --- Healthcheck endpoint pentru Railway ---
@app.route("/health", methods=["GET"])
def health_check():
    return jsonify(status="ok"), 200

@app.route("/", methods=["GET"])
def hello_world():
    return "<p>Hello, World!</p>"

@app.route("/privacy_policy", methods=["GET"])
def privacy_policy():
    return send_from_directory(directory=".", filename="privacy_policy.html", mimetype="text/html")

@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    # --- GET: verificare webhook în Meta UI ---
    if request.method == "GET":
        mode      = request.args.get("hub.mode")
        challenge = request.args.get("hub.challenge")
        token     = request.args.get("hub.verify_token")
        if mode == "subscribe" and token == VERIFY_TOKEN:
            return make_response(challenge, 200)
        logger.error("Webhook verification failed.")
        return abort(403)

    # --- POST: validare semnătură + procesare eveniment ---
    if not verify_signature(request):
        return abort(403)

    payload = request.get_json(force=True)
    logger.info("Instagram Webhook Payload:\n%s", json.dumps(payload, indent=2))

    for entry in payload.get("entry", []):
        for messaging_event in entry.get("messaging", []):
            sender_id     = messaging_event.get("sender", {}).get("id")
            incoming_text = messaging_event.get("message", {}).get("text", "")
            logger.info("Message from %s: %s", sender_id, incoming_text)

            # --- Obţine răspunsul prin Agency Swarm ---
            try:
                reply_text = agent.get_completion(incoming_text)
                logger.info("Agent reply: %s", reply_text)
            except Exception as e:
                logger.error("Error getting agent completion: %s", e)
                reply_text = "Îmi pare rău, a intervenit o eroare."

            # --- Trimite mesajul înapoi ---
            try:
                resp = send_instagram_message(sender_id, reply_text)
                logger.info("Sent to %s: %s", sender_id, resp)
            except Exception as e:
                logger.error("Error sending message: %s", e)

    return make_response("", 200)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    app.run(host="0.0.0.0", port=port)
