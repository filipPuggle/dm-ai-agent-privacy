import os
import json
import hmac
import hashlib
import logging

from dotenv import load_dotenv
from flask import Flask, request, abort, make_response, send_from_directory, jsonify

# 1. Încarcă variabilele de mediu din .env
load_dotenv()

# 2. Setează cheia OpenAI în clientul agency_swarm
from agency_swarm import set_openai_key
set_openai_key(os.getenv("OPENAI_API_KEY"))

# 3. Importă celelalte componente
from send_message import send_instagram_message
from agency import agency  # instanța definită în agency.py

# Configurează logger‑ul
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Creează aplicația Flask
app = Flask(__name__)
app.logger.setLevel(logging.INFO)

# Token‑uri pentru webhook
VERIFY_TOKEN = os.getenv("IG_VERIFY_TOKEN")
APP_SECRET   = os.getenv("IG_APP_SECRET")


def verify_signature(req):
    """
    Verifică semnătura HMAC SHA-256 de la Instagram.
    Dacă lipsește APP_SECRET sau header-ul, se ocolește verificarea (dev).
    """
    signature = req.headers.get("X-Hub-Signature-256")
    if not APP_SECRET or not signature:
        logger.warning("Skipping signature verification (dev bypass).")
        return True

    expected = "sha256=" + hmac.new(
        APP_SECRET.encode(), req.data, hashlib.sha256
    ).hexdigest()
    valid = hmac.compare_digest(expected, signature)
    if not valid:
        logger.error("Invalid signature: expected %s but got %s", expected, signature)
    return valid


@app.route("/")
def hello_world():
    return "<p>Hello, World!</p>"


@app.route("/privacy_policy")
def privacy_policy():
    return send_from_directory(
        directory=".",
        filename="privacy_policy.html",
        mimetype="text/html"
    )


@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    # --- GET pentru setup în Meta UI ---
    if request.method == "GET":
        mode      = request.args.get("hub.mode")
        challenge = request.args.get("hub.challenge")
        token     = request.args.get("hub.verify_token")
        if mode == "subscribe" and VERIFY_TOKEN and token == VERIFY_TOKEN:
            return make_response(challenge, 200)
        logger.error("Webhook verification failed.")
        return abort(403)

    # --- POST: validare semnătură și procesare eveniment ---
    if not verify_signature(request):
        return abort(403)

    payload = request.get_json(force=True)
    logger.info("Instagram Webhook Payload:\n%s", json.dumps(payload, indent=2))

    for entry in payload.get("entry", []):
        for ev in entry.get("messaging", []):
            sender_id     = ev.get("sender", {}).get("id")
            incoming_text = ev.get("message", {}).get("text", "")
            logger.info("Mesaj de la %s: %s", sender_id, incoming_text)

            # Obține răspuns prin Agency Swarm
            reply_text = agency.get_completion(incoming_text)
            logger.info("Răspuns agenție: %s", reply_text)

            # Trimite mesajul înapoi
            try:
                resp = send_instagram_message(sender_id, reply_text)
                logger.info("Trimis către %s: %s", sender_id, resp)
            except Exception as e:
                logger.error("Eroare la trimitere: %s", e)
                send_instagram_message(sender_id, "Îmi pare rău, a intervenit o eroare.")

    return make_response("", 200)


# --- endpoint pentru Railway healthcheck ---
@app.route("/health")
def health_check():
    """
    Health check endpoint for Railway.
    """
    return "OK", 200


@app.route("/instagram/callback")
def instagram_callback():
    data = request.args.to_dict()
    logger.info("OAuth callback data: %s", data)
    return jsonify(data), 200


if __name__ == "__main__":
    # Railway definește PORT în variabila de mediu, default 5000
    port = int(os.environ.get("PORT", 3000))
    app.run(host="0.0.0.0", port=port)
