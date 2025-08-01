import os
import threading
from dotenv import load_dotenv
from flask import Flask, request, abort
from send_message import send_instagram_message
from agency_swarm import set_openai_key
from agency import Agency

# ─── 1. Încărcare variabile de mediu și validare ───────────────────────────
load_dotenv()
API_KEY = os.getenv("OPENAI_API_KEY")
IG_VERIFY_TOKEN = os.getenv("IG_VERIFY_TOKEN")
IG_ACCESS_TOKEN = os.getenv("INSTAGRAM_ACCESS_TOKEN")
INSTAGRAM_BUSINESS_ACCOUNT_ID = os.getenv("INSTAGRAM_BUSINESS_ACCOUNT_ID")
DEFAULT_REPLY = os.getenv("DEFAULT_RESPONSE_MESSAGE", "Agent unavailable right now.")

# Verifică prezența variabilelor obligatorii
_required = {
    "OPENAI_API_KEY": API_KEY,
    "IG_VERIFY_TOKEN": IG_VERIFY_TOKEN,
    "INSTAGRAM_ACCESS_TOKEN": IG_ACCESS_TOKEN,
    "INSTAGRAM_BUSINESS_ACCOUNT_ID": INSTAGRAM_BUSINESS_ACCOUNT_ID,
}
missing = [name for name, val in _required.items() if not val]
if missing:
    raise RuntimeError(f"⚠️ Lipsesc variabilele de mediu: {', '.join(missing)}")

# Configurează cheia OpenAI pentru Agency Swarm
env_set = set_openai_key(API_KEY)

# Încarcă instrucțiunile agentului (opțional)
try:
    with open("instructions.md", encoding="utf-8") as f:
        INSTRUCTIONS = f.read()
except FileNotFoundError:
    INSTRUCTIONS = None

# ─── 2. Inițializare Flask ───────────────────────────────────────────────
app = Flask(__name__)

# Endpoint de health check
@app.route("/health", methods=["GET"])
def health():
    return "ok", 200

# Verificare hook Instagram (GET)
@app.route("/webhook", methods=["GET"])
def webhook_verify():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == IG_VERIFY_TOKEN:
        return challenge, 200
    abort(403)

# Agentul va fi încărcat lazy (la prima cerere)
agent = None

# Funcție de procesare și trimitere răspuns
def process_and_reply(sender_id: str, user_text: str):
    global agent
    try:
        if agent is None:
            agent = Agency().init_oai()
        reply = agent.get_completion(user_text)
    except Exception as e:
        print(f"Eroare în procesare mesaj: {e}")
        reply = DEFAULT_REPLY
    send_instagram_message(sender_id, reply)

# Endpoint principal de webhook Instagram (POST)
@app.route("/webhook", methods=["POST"])
def webhook():
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

# ─── 3. Pornire locală ───────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
