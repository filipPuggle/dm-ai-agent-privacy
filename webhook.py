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
GREETED_AT = defaultdict(float)     # sender_id -> epoch
GREET_TTL = 60 * 60                 # 1 oră

# Initialize a dictionary to track seen message IDs with a TTL of 5 minutes
SEEN_MIDS = {}  # global, mid -> epoch

# Define LAST_PRODUCT to track the last mentioned product for each user
LAST_PRODUCT = defaultdict(lambda: None)

def _should_greet(sender_id: str) -> bool:
    last = GREETED_AT[sender_id]         # cu defaultdict, default=0.0
    return (time.time() - last) > GREET_TTL

def _maybe_greet(sender_id: str, low_text: str):
    if any(tok in low_text for tok in ("salut", "bună", "buna", "hello", "hi")):
        last = GREETED_AT[sender_id]
        if (time.time() - last) > GREET_TTL:
            send_instagram_message(sender_id, "Salut! Cu ce vă pot ajuta astăzi?")
            GREETED_AT[sender_id] = time.time()

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

            # Call the greeting function immediately after calculating `low`
            low = (text_in or "").strip().lower()
            _maybe_greet(sender_id, low)

            # Inside the message loop, before processing triggers
            mid = msg.get("mid")
            now = time.time()
            if mid:
                ts = SEEN_MIDS.get(mid, 0)
                if now - ts < 300:   # 5 minute
                    continue
                SEEN_MIDS[mid] = now

            # 1) Preț / ofertă multi-linie
            if any(t in low for t in ("ce preț", "ce pret", "preț", "pret", "cât costă", "cat costa", "prețul", "pretul")):
                send_instagram_message(sender_id, format_initial_offer_multiline()[:900])
                continue

            # 2) Produs (simplă / după poză etc.)
            prod = search_product_by_text(low)
            if prod:
                send_instagram_message(sender_id, format_product_detail(prod["id"])[:900])
                # Store the last mentioned product
                LAST_PRODUCT[sender_id] = prod["id"]
                continue

            # 3) Livrare specifică pe oraș/termen imediat (preferință față de intro)
            delivery_reply = ""
            if "chișinău" in low or "chisinau" in low:
                delivery_reply = get_global_template("delivery_chisinau")
            elif "bălți" in low or "balti" in low:
                delivery_reply = get_global_template("delivery_balti")
            elif any(x in low for x in ("poșt", "post", "curier")):
                delivery_reply = get_global_template("delivery_other")

            if delivery_reply:
                send_instagram_message(sender_id, delivery_reply[:900])
                continue

            # 4) Termeni de realizare & livrare – intro
            if any(k in low for k in ("termen", "realizare", "livrare")):
                intro = get_global_template("terms_delivery_intro")
                if intro:
                    send_instagram_message(sender_id, intro[:900])
                    continue

            # 5) Mai multe detalii (folosește ultimul produs dacă nu se menționează altul)
            if "detalii" in low or "mai multe detalii" in low:
                pid = LAST_PRODUCT.get(sender_id)
                if not pid:
                    # Default to a specific product if none is stored
                    pid = "P2" if "poz" in low else "P1"
                send_instagram_message(sender_id, format_product_detail(pid)[:900])
                continue

            # 6) Cum plasez comanda? (DM flow, nu pași de site)
            if any(x in low for x in ("comand", "plasa", "plasez", "finalizez")):
                reply = get_global_template("order_howto_dm") or \
                    ("Putem prelua comanda aici în chat. Vă rog:\n\n"
                     "• Cantitate\n• Nume complet\n• Telefon\n• Localitate + adresă\n"
                     "• Metoda de livrare (curier/poștă/oficiu)\n• Metoda de plată (numerar/transfer)")
                send_instagram_message(sender_id, reply[:900])
                continue

            # Replace the fallback LLM logic with an off-topic response
            off = get_global_template("off_topic")
            if off:
                send_instagram_message(sender_id, off[:900])

    return "EVENT_RECEIVED", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)