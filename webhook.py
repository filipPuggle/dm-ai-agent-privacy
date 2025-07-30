import os
import json
import hmac
import hashlib
import logging

from dotenv import load_dotenv
from flask import Flask, request, abort, make_response, send_from_directory, jsonify

from send_message import send_instagram_message
from agency_swarm import set_openai_key, Agency
from YL.YL import YL

# ── 1) Încarcă variabile de mediu ───────────────────────────────
load_dotenv()

# ── 2) Setează OpenAI API Key ───────────────────────────────────
OPENAI_KEY = os.getenv("OPENAI_API_KEY", "")
if not OPENAI_KEY:
    raise RuntimeError("💥 OPENAI_API_KEY nu este setată!")
set_openai_key(OPENAI_KEY)

# ── 3) Creează Agency aici (fără import ambigu) ────────────────
yl_agent = YL()
agency = Agency(agency_chart=[yl_agent])

# ── 4) Configurează logger ─────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── 5) Încarcă token‑uri Instagram ─────────────────────────────
VERIFY_TOKEN = os.getenv("IG_VERIFY_TOKEN", "")
APP_SECRET   = os.getenv("IG_APP_SECRET", "")

# ── 6) Initializează Flask ─────────────────────────────────────
app = Flask(__name__)
app.logger.setLevel(logging.INFO)

def verify_signature(req):
    sig_header = req.headers.get("X-Hub-Signature-256", "")
    if not APP_SECRET or not sig_header:
        logger.warning("🔒 Semnătura nu e verificată (APP_SECRET/antet lipsă).")
        return False
    expected = "sha256=" + hmac.new(
        APP_SECRET.encode(),
        req.get_data(),
        hashlib.sha256
    ).hexdigest()
    valid = hmac.compare_digest(expected, sig_header)
    if not valid:
        logger.error("Invalid signature: expected %s but got %s", expected, sig_header)
    return valid

# ── 7) Healthcheck pentru Railway ───────────────────────────────
@app.route("/health", methods=["GET", "HEAD"])
def health_check():
    return jsonify(status="ok"), 200

# ── 8) Rute de bază ────────────────────────────────────────────
@app.route("/", methods=["GET"])
def hello_world():
    return "<p>Hello, World!</p>"

@app.route("/privacy_policy", methods=["GET"])
def privacy_policy():
    return send_from_directory(".", "privacy_policy.html", mimetype="text/html")

# ── 9) Instagram Webhook ────────────────────────────────────────
@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    if request.method == "GET":
        mode      = request.args.get("hub.mode")
        challenge = request.args.get("hub.challenge")
        token     = request.args.get("hub.verify_token")
        if mode == "subscribe" and token == VERIFY_TOKEN:
            return make_response(challenge, 200)
        logger.error("Webhook verification failed: %s %s", mode, token)
        return abort(403)

    # POST
    if not verify_signature(request):
        return abort(403)

    payload = request.get_json(force=True)
    logger.info("Payload primit:\n%s", json.dumps(payload, indent=2))

    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            for msg in change.get("value", {}).get("messages", []):
                sender_id     = msg.get("from")
                incoming_text = msg.get("text", "")
                logger.info("Mesaj de la %s: %s", sender_id, incoming_text)

                try:
                    reply_text = agency.get_completion(incoming_text)
                except Exception as e:
                    logger.error("Eroare get_completion: %s", e)
                    reply_text = "Îmi pare rău, a intervenit o eroare internă."

                try:
                    resp = send_instagram_message(sender_id, reply_text)
                    logger.info("Trimis către %s: %s", sender_id, resp)
                except Exception as e:
                    logger.error("Eroare la trimitere mesaj: %s", e)

    return make_response("", 200)

# ── 10) Boot Flask ─────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    app.run(host="0.0.0.0", port=port)

