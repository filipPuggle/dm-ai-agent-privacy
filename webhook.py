import os
import hmac
import hashlib
from flask import Flask, request, jsonify, abort, send_from_directory
from dotenv import load_dotenv
from agency_swarm.util.oai import set_openai_key
from agency import Agency  # importăm clasa corectă
# dacă nu folosești YL, poți comenta tot ce ține de Agency

# Încarcă variabilele din .env
load_dotenv()

# Cheia OpenAI e obligatorie
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise RuntimeError("⚠️ OPENAI_API_KEY nu este setat în mediul de execuție")
set_openai_key(OPENAI_API_KEY)

# Inițializează agentul (dacă ai nevoie de el)
try:
    agency = Agency(
        assistant_id=os.getenv("ASSISTANT_ID"),
        # alte setări necesare...
    )
except Exception as e:
    # dacă nu ai un folder schemas/files, prinde eroarea
    agency = None
    print(f"⚠️ Agent initialization warning: {e}")

app = Flask(__name__, static_folder=None)

# Endpoint de healthcheck
@app.route("/health", methods=["GET"])
def health():
    return jsonify(status="ok")

# Privacy policy
@app.route("/privacy_policy", methods=["GET"])
def privacy_policy():
    return send_from_directory(".", "privacy_policy.html")

# Webhook de Instagram
@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    # Verificare GET pentru challenge
    if request.method == "GET":
        mode = request.args.get("hub.mode")
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")
        if mode == "subscribe" and token == os.getenv("IG_VERIFY_TOKEN"):
            return challenge, 200
        else:
            abort(403)

    # POST → primește notificări
    sig_header = request.headers.get("X-Hub-Signature-256", "")
    body = request.get_data()
    secret = os.getenv("IG_APP_SECRET").encode()
    expected_sig = "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_sig, sig_header):
        abort(400, "Invalid signature")

    data = request.get_json(force=True)
    # aici tratezi mesajele (example: trimite la agent sau direct răspunde)
    for entry in data.get("entry", []):
        for change in entry.get("changes", []):
            if change.get("field") == "messages":
                for msg in change["value"].get("messages", []):
                    sender = msg.get("from")
                    text = msg.get("text", "")
                    # → apelează agent.send_message(sender, text) sau
                    #    trimite direct prin send_message.py
    return "", 200

if __name__ == "__main__":
    # fallback pentru local
    port = int(os.getenv("PORT", 3000))
    app.run(host="0.0.0.0", port=port)
