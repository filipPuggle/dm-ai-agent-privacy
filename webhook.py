import os, hmac, hashlib, json, logging
from flask import Flask, request, abort
from dotenv import load_dotenv
from openai import OpenAI

from send_message import send_instagram_message

load_dotenv()
app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
VERIFY_TOKEN   = os.getenv("IG_VERIFY_TOKEN")   # pentru GET hub.challenge
APP_SECRET     = os.getenv("IG_APP_SECRET")     # pentru X-Hub-Signature-256

client = OpenAI(api_key=OPENAI_API_KEY)

@app.get("/health")
def health():
    return "ok", 200

# --- 1) Verificare webhook (GET) ---
@app.get("/webhook")
def verify():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and challenge is not None:
        if VERIFY_TOKEN and token == VERIFY_TOKEN:
            return challenge, 200
        app.logger.error("Verify token invalid")
        return "Forbidden", 403
    return "Not Found", 404

# --- 2) Validare semnătură Meta (POST) ---
def _verify_signature():
    if not APP_SECRET:
        # dacă nu ai setat IG_APP_SECRET, sari validarea (nu recomand în producție)
        return True
    signature = request.headers.get("X-Hub-Signature-256", "")
    mac = hmac.new(APP_SECRET.encode("utf-8"), msg=request.data, digestmod=hashlib.sha256)
    expected = "sha256=" + mac.hexdigest()
    return hmac.compare_digest(expected, signature)

# --- 3) Procesare evenimente (POST) ---
@app.post("/webhook")
def webhook():
    if not _verify_signature():
        app.logger.error("Invalid X-Hub-Signature-256")
        abort(403)

    data = request.get_json(force=True, silent=True) or {}
    app.logger.info("Webhook payload: %s", json.dumps(data, ensure_ascii=False))

    # Instagram Messaging livrează evenimente în entry[].messaging[] cu sender.id + message.text
    # (model Messenger pentru IG).
    for entry in data.get("entry", []):
        for msg in entry.get("messaging", []):
            sender_id = (msg.get("sender") or {}).get("id")
            message   = (msg.get("message") or {})
            text      = message.get("text")

            if not sender_id or not text:
                continue

            # --- 3a) Răspuns AI ---
            try:
                completion = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system",
                         "content": "Ești un asistent politicos, concis, care răspunde la DM-uri pe Instagram."},
                        {"role": "user", "content": text},
                    ],
                    temperature=0.3,
                )
                reply = (completion.choices[0].message.content or "").strip()
                if not reply:
                    reply = "Mulțumim pentru mesaj! Revenim imediat cu detalii."
            except Exception as e:
                app.logger.exception("OpenAI error: %s", e)
                reply = "Mulțumim pentru mesaj! Revenim curând."

            # --- 3b) Trimite DM înapoi ---
            try:
                send_instagram_message(sender_id, reply)
            except Exception as e:
                app.logger.exception("Instagram send error: %s", e)

    return "EVENT_RECEIVED", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "3000")))
