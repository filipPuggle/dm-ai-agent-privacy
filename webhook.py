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
from templates import render as tpl_render

# -------------------- Bootstrap --------------------
load_dotenv()
app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s: %(message)s')

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
VERIFY_TOKEN   = os.getenv("IG_VERIFY_TOKEN", "").strip()
APP_SECRET     = os.getenv("IG_APP_SECRET", "").strip()   # opțional
OPENAI_MODEL   = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

if not OPENAI_API_KEY or not VERIFY_TOKEN:
    raise RuntimeError("Lipsește OPENAI_API_KEY sau IG_VERIFY_TOKEN din environment.")

client = OpenAI(api_key=OPENAI_API_KEY)

# Prețuri “fixe” folosite în șabloane/mesaje scurte (fără catalog)
SIMPLE_LAMP_PRICE = os.getenv("SIMPLE_LAMP_PRICE", "650")
PHOTO_LAMP_PRICE  = os.getenv("PHOTO_LAMP_PRICE",  "779")

# -------------------- Helpers --------------------
CYRILLIC_RE = re.compile(r"[\u0400-\u04FF]")
DIM_RE      = re.compile(r"(\d{2,3})\s*[x×*]\s*(\d{2,3})", re.IGNORECASE)

def detect_lang(text: str) -> str:
    """Heuristic: dacă există chirilice → ru, altfel ro."""
    return "ru" if text and CYRILLIC_RE.search(text) else "ro"

def parse_dims(text: str):
    m = DIM_RE.search(text or "")
    if not m: return None, None
    return int(m.group(1)), int(m.group(2))

def _verify_signature() -> bool:
    if not APP_SECRET:
        return True
    sig = request.headers.get("X-Hub-Signature-256", "")
    if not sig.startswith("sha256="):
        return False
    digest = hmac.new(APP_SECRET.encode(), request.data, hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig[7:], digest)

def _llm_vision_guess(image_url: str, lang: str) -> str:
    """Folosește OpenAI pentru a deduce tipul produsului din fotografie."""
    system = "Ești consultant yourlamp.md. Spune pe scurt ce tip de lampă pare în foto (ex: lampă simplă, lampă după poză, neon logo). Nu inventa dimensiuni."
    if lang == "ru":
        system = "Ты консультант yourlamp.md. Кратко определи тип лампы на фото (напр.: простая лампа, лампа по фото, неон-логотип). Не выдумывай размеры."
    try:
        resp = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": [
                    {"type": "text", "text": "Определи тип по изображению." if lang=="ru" else "Identifică tipul din imagine."},
                    {"type": "image_url", "image_url": {"url": image_url}}
                ]}
            ],
            temperature=0.2,
            max_tokens=120,
        )
        guess = (resp.choices[0].message.content or "").strip()
        return guess or ("лампа по фото" if lang=="ru" else "lampă după poză")
    except Exception as e:
        app.logger.exception("OpenAI vision error: %s", e)
        return "лампа" if lang=="ru" else "lampă"

def reply(sender_id: str, text: str):
    """Helper pentru trimitere + truncare sigură."""
    if not text: 
        return
    send_instagram_message(sender_id, text[:900])

# -------------------- Intent routing (template-only) --------------------
def handle_text_message(sender_id: str, text_in: str):
    lang = detect_lang(text_in)
    lo = text_in.lower()

    # flags de intent
    wants_price   = any(k in lo for k in ["pret", "preț", "price", "цена", "стоимость"])
    asks_catalog  = any(k in lo for k in ["gama", "asortiment", "produse", "ассортимент", "товары"])
    is_simple     = any(k in lo for k in ["simpl", "multicolor", "ursule", "inim", "прост", "мульти", "медв", "сердц"])
    is_photo_lamp = any(k in lo for k in ["poz", "foto", "poza", "по фото", "фото", "картин"])

    # 1) cerere generică de preț/asortiment fără dimensiuni -> cerem detalii
    w, _ = parse_dims(text_in)
    if (wants_price or asks_catalog) and not w:
        reply(sender_id, tpl_render("need_details", lang=lang))
        return

    # 2) lampă simplă
    if is_simple and not is_photo_lamp:
        reply(sender_id, tpl_render("simple_lamp_offer", lang=lang))
        reply(sender_id, tpl_render("features_info", lang=lang))
        reply(sender_id, tpl_render("warranty_info", lang=lang))
        reply(sender_id, tpl_render("ask_delivery", lang=lang))
        return

    # 3) lampă după poză
    if is_photo_lamp:
        reply(sender_id, tpl_render("photo_lamp_offer", lang=lang))
        reply(sender_id, tpl_render("features_info", lang=lang))
        reply(sender_id, tpl_render("warranty_info", lang=lang))
        reply(sender_id, tpl_render("ask_delivery", lang=lang))
        return

    # 4) fallback: prezintă pe scurt oferta de bază
    #    (modele simple + opțiune după poză)
    reply(sender_id, tpl_render("simple_models_pitch", lang=lang))

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

    lang = "ro"
    # nu avem text aici, dar putem defaulta la RO; dac
