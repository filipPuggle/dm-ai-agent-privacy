# webhook.py — template-only (fără catalog), cu suport RO/RU + poze (vision)
import os
import hmac
import hashlib
import json
import logging
import re
from typing import Any, Dict

from flask import Flask, request, abort
from dotenv import load_dotenv
from openai import OpenAI

from send_message import send_instagram_message
from templates import render as tpl_render, load_templates

# -------------------- Bootstrap --------------------
load_dotenv()
app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s: %(message)s')

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
VERIFY_TOKEN   = os.getenv("IG_VERIFY_TOKEN", "").strip()
APP_SECRET     = os.getenv("IG_APP_SECRET", "").strip()          # opțional (semnătură webhook)
OPENAI_MODEL   = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()

if not OPENAI_API_KEY or not VERIFY_TOKEN:
    raise RuntimeError("Lipsește OPENAI_API_KEY sau IG_VERIFY_TOKEN în environment.")

client = OpenAI(api_key=OPENAI_API_KEY)

# Prețuri „fixe” (doar dacă vrei să le schimbi rapid din env)
SIMPLE_LAMP_PRICE = os.getenv("SIMPLE_LAMP_PRICE", "650")
PHOTO_LAMP_PRICE  = os.getenv("PHOTO_LAMP_PRICE",  "779")

# Încarcă polițe/feature-uri din templates.json (pentru placeholders)
TPL_CFG = load_templates()
FEATURES = (TPL_CFG.get("policies", {}) or {}).get("features", {}) or {}
FEATURES_COLORS = FEATURES.get("colors", 16)
FEATURES_MODES  = FEATURES.get("work_modes", 4)

# -------------------- Helpers --------------------
CYRILLIC_RE = re.compile(r"[\u0400-\u04FF]")
DIM_RE      = re.compile(r"(\d{2,3})\s*[x×*]\s*(\d{2,3})", re.IGNORECASE)

def detect_lang(text: str) -> str:
    """Heuristic simplu: dacă există chirilice → ru, altfel ro."""
    return "ru" if text and CYRILLIC_RE.search(text) else "ro"

def parse_dims(text: str):
    m = DIM_RE.search(text or "")
    if not m:
        return None, None
    return int(m.group(1)), int(m.group(2))

def _verify_signature() -> bool:
    """Verifică X-Hub-Signature-256 dacă IG_APP_SECRET e setat (altfel trece)."""
    if not APP_SECRET:
        return True
    sig = request.headers.get("X-Hub-Signature-256", "")
    if not sig.startswith("sha256="):
        return False
    digest = hmac.new(APP_SECRET.encode(), request.data, hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig[7:], digest)

def _llm_vision_guess(image_url: str, lang: str) -> str:
    """Folosește OpenAI pentru a deduce tipul produsului din fotografie (scurt)."""
    system = (
        "Ești consultant yourlamp.md. Spune pe scurt ce tip de lampă e în imagine "
        "(ex: lampă simplă, lampă după poză, neon logo). Nu inventa dimensiuni."
    )
    if lang == "ru":
        system = (
            "Ты консультант yourlamp.md. Кратко определи тип лампы на фото "
            "(напр.: простая лампа, лампа по фото, неон-логотип). Не выдумывай размеры."
        )
    try:
        resp = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": [
                    {"type": "text", "text": "Определи тип по изображению." if lang == "ru" else "Identifică tipul din imagine."},
                    {"type": "image_url", "image_url": {"url": image_url}}
                ]}
            ],
            temperature=0.2,
            max_tokens=120,
        )
        guess = (resp.choices[0].message.content or "").strip()
        return guess or ("лампа по фото" if lang == "ru" else "lampă după poză")
    except Exception as e:
        app.logger.exception("OpenAI vision error: %s", e)
        return "лампа" if lang == "ru" else "lampă"

def _send(sender_id: str, text: str):
    if text:
        send_instagram_message(sender_id, text[:900])

# -------------------- Intent routing (template-only) --------------------
def handle_text_message(sender_id: str, text_in: str):
    lang = detect_lang(text_in)
    lo = text_in.lower()

    # intenții simple
    wants_price   = any(k in lo for k in ["pret", "preț", "price", "цена", "стоимость"])
    asks_catalog  = any(k in lo for k in ["gama", "asortiment", "produse", "ассортимент", "товары"])
    is_simple     = any(k in lo for k in ["simpl", "multicolor", "ursule", "inim", "прост", "мульти", "медв", "сердц"])
    is_photo_lamp = any(k in lo for k in ["poz", "foto", "poza", "по фото", "фото", "картин"])

    # 1) cere preț/asortiment fără dimensiuni -> cerem o clarificare
    w, _ = parse_dims(text_in)
    if (wants_price or asks_catalog) and not w:
        _send(sender_id, tpl_render("need_details", lang=lang))
        return

    # 2) lampă simplă (pitch + features + garanție + livrare)
    if is_simple and not is_photo_lamp:
        _send(sender_id, tpl_render("simple_lamp_offer", lang=lang))
        _send(sender_id, tpl_render("features_info", lang=lang, colors=FEATURES_COLORS, work_modes=FEATURES_MODES))
        _send(sender_id, tpl_render("warranty_info", lang=lang))
        _send(sender_id, tpl_render("ask_delivery", lang=lang))
        return

    # 3) lampă după poză
    if is_photo_lamp:
        _send(sender_id, tpl_render("photo_lamp_offer", lang=lang))
        _send(sender_id, tpl_render("features_info", lang=lang, colors=FEATURES_COLORS, work_modes=FEATURES_MODES))
        _send(sender_id, tpl_render("warranty_info", lang=lang))
        _send(sender_id, tpl_render("ask_delivery", lang=lang))
        return

    # 4) fallback: prezentare scurtă a ofertei de bază
    _send(sender_id, tpl_render("simple_models_pitch", lang=lang))

def handle_media_message(sender_id: str, item: Dict[str, Any]) -> bool:
    """Procesează poze/share; întoarce True dacă a răspuns deja."""
    atts = item.get("message", {}).get("attachments", [])
    if not atts:
        return False

    image_url = None
    shared_url = None
    for a in atts:
        t = a.get("type")
        payload = a.get("payload", {})
        if t in ("image", "photo") and (payload.get("url") or a.get("image_url")):
            image_url = payload.get("url") or a.get("image_url")
            break
        if t in ("share", "fallback") and payload.get("url"):
            shared_url = payload.get("url")

    lang = "ro"  # default; poți persista ultima limbă per sender_id dacă dorești

    if image_url:
        guess = _llm_vision_guess(image_url, lang)
        lst = f"Lampă simplă — {SIMPLE_LAMP_PRICE} MDL; Lampă după poză — {PHOTO_LAMP_PRICE} MDL"
        _send(sender_id, tpl_render("image_detected", lang=lang, guess=guess, list=lst))
        _send(sender_id, tpl_render("ask_delivery", lang=lang))
        return True

    if shared_url:
        _send(sender_id, "Mulțumesc! Îmi spui dimensiunile dorite (lățime×înălțime) ca să-ți dau prețul exact?")
        return True

    return False

# -------------------- Routes --------------------
@app.get("/")
def root():
    return "OK", 200

@app.get("/health")
def health():
    return {"ok": True}, 200

# Rută combinată: acceptă GET (verify) și POST (events), cu și fără slash
@app.route("/webhook", methods=["GET", "POST"])
@app.route("/webhook/", methods=["GET", "POST"])
def webhook_combined():
    app.logger.info("Webhook %s %s", request.method, request.path)

    if request.method == "GET":
        mode = request.args.get("hub.mode")
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")
        if mode == "subscribe" and token and token == VERIFY_TOKEN:
            return (challenge or ""), 200
        return "Forbidden", 403

    # POST (events)
    if not _verify_signature():
        app.logger.error("Invalid X-Hub-Signature-256")
        return "Forbidden", 403

    # Acceptă JSON sau raw JSON string
    body = {}
    if request.is_json:
        body = request.get_json(silent=True) or {}
    else:
        try:
            body = json.loads(request.data.decode("utf-8") or "{}")
        except Exception:
            body = {}

    app.logger.info("Incoming webhook body: %s", json.dumps(body, ensure_ascii=False)[:2000])

    for entry in body.get("entry", []):
        for item in entry.get("messaging", []):
            # Ignoră echo (mesaje trimise de noi)
            if item.get("message", {}).get("is_echo"):
                continue

            sender_id = item.get("sender", {}).get("id")
            if not sender_id:
                continue

            # 1) atașamente (poze/share)
            if handle_media_message(sender_id, item):
                continue

            # 2) text
            text_in = (item.get("message", {}).get("text") or "").strip()
            if text_in:
                handle_text_message(sender_id, text_in)

    return "EVENT_RECEIVED", 200

# -------------------- Main --------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
