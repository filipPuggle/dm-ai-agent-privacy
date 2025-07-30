import os
from dotenv import load_dotenv
from flask import Flask, request
from agency import Agency
from send_message import send_instagram_message

load_dotenv()

# Creează directoarele necesare pentru agent
os.makedirs("YL/files", exist_ok=True)
os.makedirs("YL/schemas", exist_ok=True)

# Verifică variabilele de mediu critice
REQUIRED_ENV_VARS = [
    "OPENAI_API_KEY",
    "IG_VERIFY_TOKEN",
    "IG_APP_SECRET",
    "INSTAGRAM_ACCESS_TOKEN",
    "INSTAGRAM_BUSINESS_ACCOUNT_ID"
]

for var in REQUIRED_ENV_VARS:
    if not os.getenv(var):
        raise RuntimeError(f"⚠️ {var} nu este setată in environment!")

# Setează cheia OpenAI
from agency_swarm.tools.openai_tools import set_openai_key
set_openai_key(os.getenv("OPENAI_API_KEY"))

# Creează instanța agentului
try:
    agency = Agency(assistant_id=os.getenv("ASSISTANT_ID"))
except Exception as e:
    agency = None
    print(f"⚠️ Agency init error: {e}")

# Flask app + route
app = Flask(__name__)

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    # extrage sender & text din data, exemplu (modifică la nevoie):
    sender_id = data["entry"][0]["messaging"][0]["sender"]["id"]
    message_text = data["entry"][0]["messaging"][0]["message"]["text"]

    if agency:
        # aici adaugă metoda ta de procesare AI
        response_text = agency.chat(message_text)
    else:
        response_text = os.getenv("DEFAULT_RESPONSE_MESSAGE", "Agent indisponibil temporar.")

    send_instagram_message(sender_id, response_text)
    return "ok", 200