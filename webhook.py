import os
import json
import hmac
import hashlib
import logging

from dotenv import load_dotenv
from flask import Flask, request, abort, make_response, send_from_directory, jsonify
from send_message import send_instagram_message
from agency_swarm import set_openai_key

# ── 1) Load env vars & set OpenAI key ──────────────────────────
load_dotenv()
OPENAI_KEY   = os.getenv("OPENAI_API_KEY", "")
VERIFY_TOKEN = os.getenv("IG_VERIFY_TOKEN", "")
APP_SECRET   = os.getenv("IG_APP_SECRET", "")
PORT         = int(os.getenv("PORT", 3000))

if not OPENAI_KEY:
    raise RuntimeError("💥 OPENAI_API_KEY nu este setată!")
set_openai_key(OPENAI_KEY)

# ── 2) Logger setup ────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── 3) Flask app ───────────────────────────────────────────────
app = Flask(__name__)

def verify_signature(req):
    sig = req.headers.get("X-Hub-Signature-256", "")
    if not APP_SECRET or not sig:
        logger.warning("Skipping signature verification (dev bypass).")
        return True
    expected = "sha256=" + hmac.new(
        APP_SECRET.encode(), req.get_data(), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, sig):
        logger.error("Invalid signature: expected %s but got %s", expected, sig)
        return False
    return True

# ── 4) Healthcheck endpoint ────────────────────────────────────
@app.route("/health", methods=["GET", "HEAD"])
def health_check():
    return jsonify(status="ok"), 200

# ── 5) Rute de bază ────────────────────────────────────────────
@app.route("/", methods=["GET"])
def hello():
    return "<p>Hello, World!</p>", 200

@app.route("/privacy_policy", methods=["GET"])
def privacy():
    return send_from_directory(".", "privacy_policy.html", mimetype="text/html")

# ── 6) Lazy-init Agency ────────────────────────────────────────
_agency = None
def get_agency():
    global _agency
    if _agency is None:
        from agency_swarm import Agency
        from YL.YL import YL
        yl = YL()
        _agency = Agency(agency_chart=[yl])
    return _agency

# ── 7) Instagram webhook ───────────────────────────────────────
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

    if not verify_signature(request):
        return abort(403)

    try:
        payload = request.get_json(force=True)
    except Exception as e:
        logger.error("Invalid JSON payload: %s", e)
        return abort(400)

    logger.info("Payload primit:\n%s", json.dumps(payload, indent=2))

    # procesare mesaje
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            for msg in change.get("value", {}).get("messages", []):
                sender = msg.get("from")
                text   = msg.get("text", "")
                logger.info("Mesaj de la %s: %s", sender, text)

                try:
                    reply = get_agency().get_completion(text)
                except Exception as e:
                    logger.error("Eroare la get_completion: %s", e)
                    reply = "Îmi pare rău, a intervenit o eroare internă."

                try:
                    resp = send_instagram_message(sender, reply)
                    logger.info("Trimis către %s: %s", sender, resp)
                except Exception as e:
                    logger.error("Eroare la trimitere mesaj: %s", e)

    return "", 200

# ── 8) Run app ──────────────────────────────────────────────────
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)

