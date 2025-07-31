import os
from dotenv import load_dotenv
from flask import Flask, request
import openai
from send_message import send_instagram_message

# 0. Init
load_dotenv()
app = Flask(__name__)

# 1. Verifică și încarcă variabilele de mediu
REQUIRED = [
    "OPENAI_API_KEY",
    "IG_VERIFY_TOKEN",
    "INSTAGRAM_ACCESS_TOKEN",
    "INSTAGRAM_BUSINESS_ACCOUNT_ID",
]
for var in REQUIRED:
    if not os.getenv(var):
        raise RuntimeError(f"⚠️ {var} lipsește din .env!")

openai.organization = os.getenv("OPENAI_ORG_ID")
openai.api_key       = os.getenv("OPENAI_API_KEY")

# 2. Citește instrucțiunile agentului o singură dată
with open("instructions.md", encoding="utf-8") as f:
    INSTRUCTIONS = f.read()

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    # → preluăm sender_id și message_text exact așa cum vine de la Instagram
    sender_id    = data["entry"][0]["messaging"][0]["sender"]["id"]
    message_text = data["entry"][0]["messaging"][0]["message"]["text"]

    try:
        # 3. Trimitem la OpenAI
        resp = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": INSTRUCTIONS},
                {"role": "user",   "content": message_text}
            ],
            temperature=0.3,
        )
        response_text = resp.choices[0].message.content.strip()
        print("✅ AI răspuns:", response_text)
    except Exception as e:
        print("⚠️ Eroare OpenAI:", e)
        # fallback din .env sau mesajul hard-coded dacă nu există DEFAULT_RESPONSE_MESSAGE
        response_text = os.getenv(
            "DEFAULT_RESPONSE_MESSAGE",
            "Agent indisponibil temporar."
        )

    # 4. Trimitem mesajul înapoi pe Instagram
    send_instagram_message(sender_id, response_text)
    return "ok", 200

@app.route("/webhook", methods=["GET"])
def verify():
    mode      = request.args.get("hub.mode")
    token     = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == os.getenv("IG_VERIFY_TOKEN"):
        return challenge, 200
    return "Forbidden", 403

@app.route("/health", methods=["GET"])
def health():
    return "ok", 200

if __name__ == "__main__":
    # rulează local la portul din .env sau 8080
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
