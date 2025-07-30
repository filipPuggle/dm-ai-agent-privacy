import os
import hmac
import hashlib
from flask import Flask, request, jsonify, abort, send_from_directory
from dotenv import load_dotenv
from agency_swarm.util.oai import set_openai_key
from agency import Agency  # importăm clasa Agency definită în agency.py

# Încărcăm variabilele din fișierul .env (dacă există) și din mediul sistem
load_dotenv()

# Cheia OpenAI este obligatorie pentru a rula agentul
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise RuntimeError("⚠️ OPENAI_API_KEY nu este setat în mediul de execuție")
set_openai_key(OPENAI_API_KEY)

# Inițializăm agentul (dacă configurația este prezentă și corectă)
try:
    agency = Agency(
        assistant_id=os.getenv("ASSISTANT_ID"),
        # Aici se pot adăuga și alți parametri necesari (e.g. 'instructions', 'model', etc.)
    )
except Exception as e:
    # Dacă nu există folderele necesare (ex: schemas/ sau files/) sau apar alte erori,
    # agentul nu va fi pornit, iar aplicația va continua să ruleze.
    agency = None
    print(f"⚠️ Agent initialization warning: {e}")

app = Flask(__name__, static_folder=None)

# Endpoint de healthcheck pentru Railway
@app.route("/health", methods=["GET"])
def health():
    return jsonify(status="ok")

# Endpoint pentru Privacy Policy (servește un fișier HTML static)
@app.route("/privacy_policy", methods=["GET"])
def privacy_policy():
    return send_from_directory(".", "privacy_policy.html")

# Webhook pentru Instagram (primește evenimente prin API-ul Facebook/Instagram)
@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    # Verificare Webhook (GET) pentru handshake (challenge)
    if request.method == "GET":
        mode = request.args.get("hub.mode")
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")
        if mode == "subscribe" and token == os.getenv("IG_VERIFY_TOKEN"):
            return challenge, 200
        else:
            abort(403)

    # Tratăm cererile POST (notificări de mesaje)
    sig_header = request.headers.get("X-Hub-Signature-256", "")
    body = request.get_data()
    secret = os.getenv("IG_APP_SECRET", "").encode()
    expected_sig = "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_sig, sig_header or ""):
        abort(400, "Invalid signature")

    data = request.get_json(force=True)
    # Parcurgem fiecare mesaj primit și răspundem (direct sau folosind agentul AI)
    for entry in data.get("entry", []):
        for change in entry.get("changes", []):
            if change.get("field") == "messages":
                for msg in change["value"].get("messages", []):
                    sender = msg.get("from")
                    text = msg.get("text", "")
                    # TODO: Apelare logica de răspuns
                    # Exemplu: dacă agentul este disponibil, îi trimitem mesajul:
                    # if agency:
                    #     agency.send_message(sender, text)
                    # Altfel, răspuns direct folosind funcția send_instagram_message:
                    # send_instagram_message(sender, "<mesaj fallback>", os.getenv("IG_PAGE_ACCESS_TOKEN"))
    return "", 200

if __name__ == "__main__":
    # Fallback pentru rularea locală - folosește PORT din mediu sau 3000 implicit
    port = int(os.getenv("PORT", 3000))
    app.run(host="0.0.0.0", port=port)

