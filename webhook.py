import os, hmac, hashlib, json, logging
from flask import Flask, request, abort
from dotenv import load_dotenv
from openai import OpenAI

from send_message import send_instagram_message
from catalog import search_products

load_dotenv()
app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# ---- Env
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
VERIFY_TOKEN   = os.getenv("IG_VERIFY_TOKEN", "").strip()
APP_SECRET     = os.getenv("IG_APP_SECRET", "").strip()   # opțional
OPENAI_MODEL   = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

client = OpenAI(api_key=OPENAI_API_KEY)

# ---- Helpers
def _verify_signature() -> bool:
    if not APP_SECRET:
        return True
    sig = request.headers.get("X-Hub-Signature-256", "")
    if not sig.startswith("sha256="):
        return False
    digest = hmac.new(APP_SECRET.encode(), request.data, hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig[7:], digest)

def _read_prompt_template(catalog_context: str) -> str:
    path = os.path.join("prompts", "assistant.md")
    try:
        with open(path, "r", encoding="utf-8") as f:
            tpl = f.read()
    except FileNotFoundError:
        tpl = ("Ești asistentul yourlamp.md. Răspunde concis. "
               "Nu inventa prețuri. Context:\n{{catalog_context}}")
    # înlocuiri simple (fără Jinja2)
    return (tpl
            .replace("{{brand}}", "yourlamp.md")
            .replace("{{currency}}", "MDL")
            .replace("{{policy_24h}}", "Răspundem în fereastra de 24h de la ultimul mesaj.")
            .replace("{{catalog_context}}", catalog_context or "Nu am găsit potriviri în catalog."))

def _catalog_context_for(user_text: str, limit: int = 3) -> str:
    hits = search_products(user_text, limit=limit)
    if not hits:
        return ""
    lines = []
    for p in hits:
        name = p.get("name", "")
        size = p.get("size", "")
        sku  = p.get("sku", "")
        price = p.get("price")
        unit  = p.get("unit", "MDL")
        line = f"- {name}"
        if size: line += f" ({size})"
        if price is not None: line += f" — {price} MDL"
        if unit and unit != "MDL": line += f" ({unit})"
        line += f" [SKU: {sku}]"
        lines.append(line)
    return "\n".join(lines)

def _generate_reply(user_text: str) -> str:
    context = _catalog_context_for(user_text, limit=3)
    system = _read_prompt_template(context)
    try:
        resp = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_text},
            ],
            temperature=0.3,
            max_tokens=220,
        )
        return (resp.choices[0].message.content or "").strip() or \
               "Mulțumim! Ne poți spune dimensiunile și culoarea dorită?"
    except Exception as e:
        app.logger.exception("OpenAI error: %s", e)
        return "Mulțumim pentru mesaj! Revenim curând cu detalii exacte."

# ---- Routes
@app.get("/health")
def health():
    return {"ok": True}, 200

@app.get("/webhook")
def verify():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token and token == VERIFY_TOKEN:
        return challenge, 200
    return "Forbidden", 403

@app.post("/webhook")
def webhook():
    if not _verify_signature():
        app.logger.error("Invalid X-Hub-Signature-256")
        abort(403)

    data = request.get_json(force=True, silent=True) or {}
    app.logger.info("Incoming webhook: %s", json.dumps(data, ensure_ascii=False)[:2000])

    for entry in data.get("entry", []):
        for item in entry.get("messaging", []):
            # ignoră echo (mesaje trimise de noi)
            if item.get("message", {}).get("is_echo"):
                continue

            sender_id = item.get("sender", {}).get("id")
            msg = item.get("message", {})
            text_in = (msg.get("text") or "").strip()
            if not sender_id or not text_in:
                continue

            reply = _generate_reply(text_in)
            try:
                # Trimite DM înapoi (Instagram Login flow)
                send_instagram_message(sender_id, reply[:900])
                app.logger.info("✅ Sent reply to %s", sender_id)
            except Exception as e:
                app.logger.exception("Instagram send error: %s", e)

    return "EVENT_RECEIVED", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
