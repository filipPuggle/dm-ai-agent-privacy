import os
from dotenv import load_dotenv
from flask import Flask, request
from agency import Agency
from send_message import send_instagram_message

# Încarcă variabilele de mediu din .env
load_dotenv()

# Crează folderele necesare (pentru YL/tools, schemas etc.)
os.makedirs("YL/files", exist_ok=True)
os.makedirs("YL/schemas", exist_ok=True)
os.makedirs("YL/tools", exist_ok=True)

# Verifică că toate variabilele de mediu esențiale sunt setate
REQUIRED_ENV_VARS = [
    "OPENAI_API_KEY",
    "IG_VERIFY_TOKEN",
    "IG_APP_SECRET",
    "INSTAGRAM_ACCESS_TOKEN",
    "INSTAGRAM_BUSINESS_ACCOUNT_ID"
]
for var in REQUIRED_ENV_VARS:
    if not os.getenv(var):
        raise RuntimeError(f"⚠️ {var} nu este setată în environment!")

# Înregistrează cheia OpenAI la nivelul agency-swarm
from agency_swarm import set_openai_key
set_openai_key(os.getenv("OPENAI_API_KEY"))

# Inițializează Agentul
try:
    agency = Agency()
except Exception as e:
    agency = None
    print(f"⚠️ Agency init error: {e}")

app = Flask(__name__)

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    sender_id   = data["entry"][0]["messaging"][0]["sender"]["id"]
    message_text = data["entry"][0]["messaging"][0]["message"]["text"]

    if agency:
        try:
            # Apel corect către Agent: metoda get_completion()
            response_text = agency.get_completion(message_text)
        except Exception as err:
            # Dacă apare orice eroare, fallback la mesaj predeterminat
            print(f"⚠️ Eroare AI (get_completion): {err}")
            response_text = os.getenv(
                "DEFAULT_RESPONSE_MESSAGE",
                "Agent indisponibil temporar."
            )
    else:
        # Fallback dacă Agency n-a pornit corect
        response_text = os.getenv(
            "DEFAULT_RESPONSE_MESSAGE",
            "Agent indisponibil temporar."
        )

    # Trimite răspuns prin Instagram Graph API
    send_instagram_message(sender_id, response_text)
    return "ok", 200

@app.route("/webhook", methods=["GET"])
def webhook_verify():
    mode      = request.args.get("hub.mode")
    token     = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode and token and challenge and token == os.getenv("IG_VERIFY_TOKEN"):
        return challenge, 200
    return "Token invalid sau parametri lipsă", 403

@app.route("/health", methods=["GET"])
def health():
    return "ok", 200