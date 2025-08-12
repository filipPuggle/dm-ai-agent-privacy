import os
import json
import hmac
import hashlib
import logging
from typing import Any, Dict

from flask import Flask, request, Response, send_from_directory
from dotenv import load_dotenv
from openai import OpenAI

from send_message import send_instagram_message

load_dotenv()

# ===== Config =====
PAGE_ACCESS_TOKEN = os.getenv("PAGE_ACCESS_TOKEN")
PAGE_ID = os.getenv("PAGE_ID")
IG_VERIFY_TOKEN = os.getenv("IG_VERIFY_TOKEN")
IG_APP_SECRET = os.getenv("IG_APP_SECRET")  # optional
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# Validare minimă env
REQUIRED = {
    "PAGE_ACCESS_TOKEN": PAGE_ACCESS_TOKEN,
    "PAGE_ID": PAGE_ID,
    "IG_VERIFY_TOKEN": IG_VERIFY_TOKEN,
    "OPENAI_API_KEY": OPENAI_API_KEY,
}
missing = [k for k, v in REQUIRED.items() if not v]
if missing:
    raise RuntimeError(f"Lipsesc variabile obligatorii: {', '.join(missing)}")

# OpenAI client
client = OpenAI(api_key=OPENAI_API_KEY)

# Flask
app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s in %(module)s: %(message)s')
logger = logging.getLogger(__name__)


# ===== Helpers =====
def _verify_signature(req) -> bool:
    """Verifică X-Hub-Signature-256 dacă IG_APP_SECRET este setat. Altfel, permite trecerea (dev)."""
    if not IG_APP_SECRET:
        return True
    signature = req.headers.get("X-Hub-Signature-256")
    if not signature or not signature.startswith("sha256="):
        return False
    digest = hmac.new(IG_APP_SECRET.encode("utf-8"), req.get_data(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature.split("=", 1)[1], digest)


def _extract_text_messages(body: Dict[str, Any]):
    """Iterează prin entry[].messaging[] și yield (sender_id, text). Ignoră echo / non-text."""
    for entry in body.get("entry", []):
        for msg in entry.get("messaging", []):
            # Echo de la noi? ignora
            if msg.get("message", {}).get("is_echo"):
                continue
            sender = msg.get("sender", {})
            message = msg.get("message", {})
            text = (message.get("text") or "").strip()
            sender_id = sender.get("id")
            if sender_id and text:
                yield sender_id, text


def _generate_reply(user_text: str) -> str:
    system = (
        "Ești un asistent concis și prietenos pentru brandul yourlamp.md. "
        "Răspunde în limba utilizatorului (RO/RU/EN), folosește fraze scurte. "
        "Dacă întrebarea este vagă, cere o clarificare într-o singură propoziție."
    )
    try:
        resp = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_text},
            ],
            temperature=0.5,
            max_tokens=200,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        logger.exception("OpenAI error: %s", e)
        return "Îți mulțumim pentru mesaj! Revenim cu un răspuns în scurt timp."


# ===== Routes =====
@app.get("/")
def root():
    return Response("OK", 200)


@app.get("/health")
def health():
    return Response("healthy", 200)


@app.get("/privacy_policy")
def privacy():
    # Servește fișierul local privacy_policy.html
    return send_from_directory(".", "privacy_policy.html")


@app.get("/webhook")
def webhook_verify():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == IG_VERIFY_TOKEN:
        return Response(challenge or "", 200)
    return Response("Forbidden", 403)


@app.post("/webhook")
def webhook_events():
    if not _verify_signature(request):
        return Response("Invalid signature", 403)

    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        return Response("Bad Request", 400)

    logger.info("Incoming webhook: %s", json.dumps(body)[:1200])

    # Procesează fiecare mesaj text și răspunde
    for sender_id, text in _extract_text_messages(body):
        reply = _generate_reply(text)
        sent = send_instagram_message(PAGE_ID, PAGE_ACCESS_TOKEN, sender_id, reply)
        if not sent:
            logger.error("Nu am putut trimite răspuns către %s", sender_id)

    return Response("EVENT_RECEIVED", 200)
