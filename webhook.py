import os, hmac, hashlib, json, logging, time
from collections import defaultdict
from flask import Flask, request, abort
from dotenv import load_dotenv
load_dotenv()
from openai import OpenAI
from tools.catalog_pricing import (
    format_initial_offer_multiline,
    format_product_detail,
    search_product_by_text,
    get_global_template
)
from send_message import send_instagram_message

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
VERIFY_TOKEN   = os.getenv("IG_VERIFY_TOKEN", "").strip()
APP_SECRET     = os.getenv("IG_APP_SECRET", "").strip()  # opțional

client = OpenAI(api_key=OPENAI_API_KEY)

# Greeting memory (o singură dată pe utilizator, TTL 1 oră)
GREETED_AT = defaultdict(float)          # sender_id -> epoch sec
GREET_TTL = 60 * 60                      # 1 oră

def _should_greet(sender_id: str) -> bool:
    last = GREETED_AT[sender_id]         # cu defaultdict, default=0.0
    return (time.time() - last) > GREET_TTL

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

    for entry in data.get("entry", []):
        for item in entry.get("messaging", []):
            sender_id = item.get("sender", {}).get("id")
            msg = item.get("message", {})
            text_in = (msg.get("text") or "").strip()
            if not sender_id or not text_in:
                continue

            low = (text_in or "").strip().lower()

            # 0) Salut – o singură dată per utilizator (TTL 1h)
            if low in ("salut", "bună", "buna", "hello", "hi") and _should_greet(sender_id):
                try:
                    send_instagram_message(sender_id, "Salut! Cu ce vă pot ajuta astăzi?")
                    GREETED_AT[sender_id] = time.time()
                except Exception as e:
                    app.logger.exception("Greet send error: %s", e)
                continue

            # 1) Preț / ofertă multi-linie (cu markerii din JSON)
            _price_triggers_ro = ("ce preț", "ce pret", "preț", "pret", "cât costă", "cat costa", "prețul", "pretul")
            if any(t in low for t in _price_triggers_ro):
                try:
                    reply = format_initial_offer_multiline()  # ia {p1}/{p2} din catalog
                    send_instagram_message(sender_id, reply[:900])
                except Exception as e:
                    app.logger.exception("Offer send error: %s", e)
                continue

            # 2) Produs menționat (simplă / după poză etc.)
            prod = search_product_by_text(low)
            if prod:
                try:
                    reply = format_product_detail(prod["id"])
                    send_instagram_message(sender_id, reply[:900])
                except Exception as e:
                    app.logger.exception("Product detail send error: %s", e)
                continue

            # 3) Termeni de realizare / livrare – intro
            if any(k in low for k in ("termen", "termenii", "realizare", "livrare")):
                try:
                    reply = get_global_template("terms_delivery_intro")
                    if reply:
                        send_instagram_message(sender_id, reply[:900])
                        continue
                except Exception as e:
                    app.logger.exception("Terms/Delivery intro send error: %s", e)
                    # nu face return/continue aici, lasă LLM-ul să încerce

            # 4) Livrare specifică (Chișinău/Bălți/alte localități)
            delivery_reply = ""
            if "chișinău" in low or "chisinau" in low:
                delivery_reply = get_global_template("delivery_chisinau")
            elif "bălți" in low or "balti" in low:
                delivery_reply = get_global_template("delivery_balti")
            elif any(x in low for x in ("poșt", "post", "curier", "oras", "oraș")):
                delivery_reply = get_global_template("delivery_other")

            if delivery_reply:
                try:
                    send_instagram_message(sender_id, delivery_reply[:900])
                except Exception as e:
                    app.logger.exception("Delivery send error: %s", e)
                continue

            # 5) Fallback LLM (răspunde la restul întrebărilor, ex. „cum fac comanda?”)
            try:
                completion = client.chat.completions.create(
                    model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                    messages=[
                        {"role": "system", "content": "Ești un asistent prietenos pentru magazinul nostru online. Respectă adresarea cu «dumneavoastră»."},
                        {"role": "user", "content": text_in},
                    ],
                    temperature=0.6,
                )
                reply = completion.choices[0].message.content.strip()
            except Exception as e:
                app.logger.exception("OpenAI error: %s", e)
                reply = "Mulțumim pentru mesaj! Revenim curând."

            try:
                send_instagram_message(sender_id, reply[:900])
            except Exception as e:
                app.logger.exception("Instagram send error: %s", e)

    return "EVENT_RECEIVED", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)