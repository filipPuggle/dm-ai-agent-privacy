import os, hmac, hashlib, json, logging
from flask import Flask, request, abort
from dotenv import load_dotenv
from openai import OpenAI
from tools.catalog_pricing import format_initial_offer
from send_message import send_instagram_message

load_dotenv()
app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
VERIFY_TOKEN   = os.getenv("IG_VERIFY_TOKEN", "").strip()
APP_SECRET     = os.getenv("IG_APP_SECRET", "").strip()  # opțional

client = OpenAI(api_key=OPENAI_API_KEY)

@app.get("/health")
def health():
    return {"ok": True}, 200

# --- 1) Verify webhook (GET) ---
@app.get("/webhook")
def verify():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode == "subscribe" and token and token == VERIFY_TOKEN:
        return challenge, 200
    return "Forbidden", 403

# --- helper: verify X-Hub-Signature-256 (opțional) ---
def _verify_signature() -> bool:
    if not APP_SECRET:
        return True  # în dev nu verificăm semnătura
    sig = request.headers.get("X-Hub-Signature-256", "")
    if not sig.startswith("sha256="):
        return False
    digest = hmac.new(APP_SECRET.encode(), request.data, hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig[7:], digest)

# --- 2) Procesare evenimente (POST) ---
@app.post("/webhook")
def webhook():
    if not _verify_signature():
        app.logger.error("Invalid X-Hub-Signature-256")
        abort(403)

    data = request.get_json(force=True, silent=True) or {}
    app.logger.info("Incoming webhook: %s", json.dumps(data, ensure_ascii=False))

    # Instagram Messaging -> entry[].messaging[] (IGSID în sender.id)
    for entry in data.get("entry", []):
        for item in entry.get("messaging", []):
            sender_id = item.get("sender", {}).get("id")
            msg = item.get("message", {})
            text_in = (msg.get("text") or "").strip()
            if not sender_id or not text_in:
                continue

            # --- Răspuns determinist la întrebări de preț/ofertă inițială ---
            _price_triggers_ro = ("ce preț", "ce pret", "preț", "pret", "cât costă", "cat costa")
            if text_in and any(t in text_in.lower() for t in _price_triggers_ro):
                try:
                    reply = format_initial_offer()
                    send_instagram_message(sender_id, reply[:900])
                except Exception as e:
                    app.logger.exception("Offer send error: %s", e)
                continue    

            try:
                completion = client.chat.completions.create(
                    model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                    messages=[
                        {"role": "system", "content": f"Ești un asistent prietenos pentru magazinul nostru online. Răspunde la întrebări despre produse, comenzi și suport clienți.  "},
                        {"role": "user", "content": text_in},
                    ],
                    temperature=1.0,
                )
                reply = completion.choices[0].message.content.strip()
            except Exception as e:
                app.logger.exception("OpenAI error: %s", e)
                reply = "Mulțumim pentru mesaj! Revenim curând."

            # --- 2b) Trimite DM înapoi (Instagram Login flow) ---
            try:
                send_instagram_message(sender_id, reply[:900])
            except Exception as e:
                app.logger.exception("Instagram send error: %s", e)

    return "EVENT_RECEIVED", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)