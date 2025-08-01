import os
from dotenv import load_dotenv
from flask import Flask, request
from send_message import send_instagram_message

# Agency Swarm imports
from agency_swarm import set_openai_key
from agency import Agency

# 0. Load env and set up Agency Swarm
load_dotenv()
# Point Agency Swarm at your OpenAI key (or omit if you prefer USDOT in .env)
set_openai_key(os.getenv("OPENAI_API_KEY"))

# 1. Instantiate your Agent and provision it in OpenAI
agent = Agency().init_oai()

app = Flask(__name__)

# 2. Webhook verification endpoint
@app.route("/webhook", methods=["GET"])
def verify_webhook():
    mode      = request.args.get("hub.mode")
    token     = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == os.getenv("IG_VERIFY_TOKEN"):
        return challenge, 200
    return "Forbidden", 403

# 3. Health check
@app.route("/health", methods=["GET"])
def health():
    return "ok", 200

# 4. Message handler
@app.route("/webhook", methods=["POST"])
def handle_message():
    data = request.get_json()
    # Extract the sender ID and message text
    entry = data.get("entry", [])[0]
    messaging = entry.get("messaging", [])[0]
    sender_id = messaging["sender"]["id"]
    user_text = messaging.get("message", {}).get("text", "").strip()

    if not user_text:
        # nothing to do
        return "No text", 200

    try:
        # 5. Get the assistant's reply from Agency Swarm
        response_text = agent.get_completion(user_text)
        print("✅ AI răspuns:", response_text)

    except Exception as e:
        print("⚠️ Eroare Agent:", e)
        response_text = os.getenv(
            "DEFAULT_RESPONSE_MESSAGE",
            "Agent indisponibil temporar."
        )

    # 6. Send reply back via Instagram Graph API
    send_instagram_message(
        recipient_id=sender_id,
        message_text=response_text,
        access_token=os.getenv("INSTAGRAM_ACCESS_TOKEN")
    )

    return "Handled", 200

if __name__ == "__main__":
    # Local run on PORT or default 8080
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
