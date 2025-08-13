# webhook.py — robust IG parsing + dialog flow + safe send (fără 500 la trimitere)

import os
import hmac
import json
import logging
from hashlib import sha256
from typing import Dict, Any, Optional

from flask import Flask, request, jsonify

from templates import detect_lang, t, policy
from send_message import send_text

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("webhook")

# ENV
VERIFY_TOKEN = (os.getenv("IG_VERIFY_TOKEN") or "").strip()
APP_SECRET = (os.getenv("IG_APP_SECRET") or "").strip()

_has_ig_id = bool(os.getenv("INSTAGRAM_BUSINESS_ACCOUNT_ID") or os.getenv("PAGE_ID"))
_has_token = bool(
    os.getenv("GRAPH_API_ACCESS_TOKEN") or os.getenv("INSTAGRAM_ACCESS_TOKEN") or os.getenv("PAGE_ACCESS_TOKEN")
)
log.info("ENV check: IG_ID=%s, TOKEN=%s, VERIFY=%s, SECRET=%s", _has_ig_id, _has_token, bool(VERIFY_TOKEN), bool(APP_SECRET))

# State (prod: Redis)
STATE: Dict[str, Dict[str, Any]] = {}
PROCESSED_MIDS = set()  # anti-duplicat

# Health / root
@app.get("/health")
def health():
    return "ok", 200

@app.get("/")
def root():
    return jsonify({"status": "ok"}), 200

# Verify
@app.get("/webhook")
def webhook_verify():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge or "", 200
    return "forbidden", 403

# Signature
def _verify_signature(req) -> bool:
    if not APP_SECRET:
        return True
    sig = req.headers.get("X-Hub-Signature-256", "")
    if not sig.startswith("sha256="):
        return False
    digest = hmac.new(APP_SECRET.encode("utf-8"), msg=req.data, digestmod=sha256).hexdigest()
    return hmac.compare_digest(sig.split("=", 1)[1], digest)

# Extractor
def _extract_messages(payload: dict):
    for entry in payload.get("entry", []):
        # Messenger-like
        for m in (entry.get("messaging") or []):
            from_id = (m.get("sender") or {}).get("id")
            text = (m.get("message") or {}).get("text")
            mid = (m.get("message") or {}).get("mid") or m.get("id")
            if from_id and text:
                yield {"from_id": from_id, "text": text, "mid": mid}
        # Instagram changes
        for ch in (entry.get("changes") or []):
            val = ch.get("value") or {}
            for mm in (val.get("messages") or []):
                _from = mm.get("from")
                from_id = (_from.get("id") if isinstance(_from, dict) else _from)
                text = (mm.get("text") if isinstance(mm.get("text"), str) else (mm.get("message") or {}).get("text"))
                mid = mm.get("id") or (mm.get("message") or {}).get("mid")
                if from_id and text:
                    yield {"from_id": from_id, "text": text, "mid": mid}
            _from2 = val.get("from")
            from_id = (_from2.get("id") if isinstance(_from2, dict) else _from2)
            text = (val.get("text") if isinstance(val.get("text"), str)
                    else (val.get("message") or {}).get("text")
                    or (val.get("message") if isinstance(val.get("message"), str) else None))
            mid = val.get("id") or (val.get("message") or {}).get("mid")
            if from_id and text:
                yield {"from_id": from_id, "text": text, "mid": mid}

# Safe send (nu mai aruncăm 500 spre IG dacă trimiterea eșuează)
def safe_send(uid: str, text: str):
    try:
        send_text(uid, text)
    except Exception as e:
        log.error("❌ send failed: %s", e)

# Webhook POST
@app.post("/webhook")
def webhook_receive():
    if not _verify_signature(request):
        log.warning("❌ invalid signature")
        return "invalid signature", 403

    payload = request.get_json(force=True, silent=True) or {}
    log.info("📩 IG webhook payload: %s", json.dumps(payload, ensure_ascii=False))

    had = False
    for msg in _extract_messages(payload):
        had = True
        mid = msg.get("mid")
        if mid and mid in PROCESSED_MIDS:
            continue
        if mid:
            PROCESSED_MIDS.add(mid)
        from_id = msg["from_id"]
        text = (msg["text"] or "").strip()
        log.info("➡️ INCOMING IG TEXT from=%s: %s", from_id, text)
        handle_message(from_id, text)

    if not had:
        log.info("ℹ️ Webhook fără mesaje text relevante.")
    return "ok", 200

# Dialog
def get_lang(user_text: str, state: Dict[str, Any]) -> str:
    if "lang" in state:
        return state["lang"]
    lang = detect_lang(user_text)
    state["lang"] = lang
    return lang

def handle_message(uid: str, user_text: str) -> None:
    user_state = STATE.setdefault(uid, {})
    lang = get_lang(user_text, user_state)
    text_norm = user_text.strip().lower()
    order = user_state.setdefault("order", {})
    stage = user_state.get("stage")

    if stage is None or any(x in text_norm for x in ["salut", "привет", "здравствуйте", "buna", "bună", "hello", "hi"]):
        STATE[uid] = {"lang": lang, "stage": "menu", "order": {}}
        safe_send(uid, t("greeting", lang))
        safe_send(uid, t("menu_products", lang))
        return

    if stage == "menu":
        if "poz" in text_norm or "poza" in text_norm or "по фото" in text_norm or "foto" in text_norm:
            order["model"] = "Lampă după poză" if lang == "ro" else "Лампа по фото"
            user_state["stage"] = "details"
            safe_send(uid, t("ask_details", lang))
            return
        if "simpl" in text_norm or "прост" in text_norm:
            order["model"] = "Lampă simplă" if lang == "ro" else "Простая лампа"
            user_state["stage"] = "details"
            safe_send(uid, t("ask_details", lang))
            return
        if any(x in text_norm for x in ["livrare", "достав", "delivery"]):
            user_state["stage"] = "delivery"
            send_delivery(uid, lang)
            return
        if any(x in text_norm for x in ["plată", "plata", "оплат", "payment"]):
            user_state["stage"] = "payment"
            send_payment(uid, lang)
            return
        safe_send(uid, t("menu_products", lang))
        return

    if stage == "details":
        size = parse_size(text_norm)
        if size:
            order["size"] = size
        if any(k in text_norm for k in ["logo", "text", "poz", "фото", "текст", "лого"]):
            order["has_art"] = True
        if order.get("model") and order.get("size"):
            price = quote_price(order["model"], order["size"])
            order["price"] = price
            user_state["stage"] = "offer"
            safe_send(uid, t("offer", lang, model=order["model"], size=order["size"], price=price))
            return
        safe_send(uid, t("ask_details", lang))
        return

    if stage == "offer":
        user_state["stage"] = "delivery"
        send_delivery(uid, lang)
        return

    if stage == "delivery":
        if "chiș" in text_norm or "chis" in text_norm or "кишин" in text_norm:
            order["delivery"] = "Chișinău" if lang == "ro" else "Кишинёв"
        elif "țară" in text_norm or "tara" in text_norm or "стране" in text_norm or "почт" in text_norm:
            order["delivery"] = "În țară (poștă)" if lang == "ro" else "По стране (почта)"
        elif "ridic" in text_norm or "самовыв" in text_norm:
            order["delivery"] = "Ridicare" if lang == "ro" else "Самовывоз"
        user_state["stage"] = "payment"
        send_payment(uid, lang)
        return

    if stage == "payment":
        user_state["stage"] = "order_fields"
        safe_send(uid, t("ask_order_fields", lang))
        return

    if stage == "order_fields":
        user_state["stage"] = "confirm"
        order_summary = summarize_order(order, lang)
        delivery_human = order.get("delivery", "-")
        safe_send(uid, t("confirm", lang, summary=order_summary, delivery=delivery_human, deposit=policy("payments.deposit_mdl")))
        user_state["stage"] = "menu"
        return

    safe_send(uid, t("fallback", lang))

# Helpers
def send_delivery(uid: str, lang: str):
    ch_note = policy("delivery.chisinau.time_note_ro" if lang == "ro" else "delivery.chisinau.time_note_ru")
    ct_note = policy("delivery.country.time_note_ro" if lang == "ro" else "delivery.country.time_note_ru")
    pickup = policy("delivery.pickup")
    msg = t("delivery", lang, chisinau_note=ch_note, country_note=ct_note,
            pickup_address=pickup["address"], pickup_hours=pickup["hours"],
            pickup_note=pickup["note_ro"] if lang == "ro" else pickup["note_ru"])
    safe_send(uid, msg)

def send_payment(uid: str, lang: str):
    pm = policy("payments")
    methods = pm["methods_ro"] if lang == "ro" else pm["methods_ru"]
    msg = t("payment", lang, m1=methods[0], m2=methods[1], m3=methods[2], m4=methods[3], deposit=pm["deposit_mdl"])
    safe_send(uid, msg)

def parse_size(text: str) -> Optional[str]:
    for sep in ("x", "×", "*"):
        if sep in text:
            parts = text.replace(" ", "").split(sep)
            if len(parts) == 2 and all(p.isdigit() for p in parts):
                return f"{int(parts[0])}×{int(parts[1])} cm"
    return None

def quote_price(model: str, size: str) -> int:
    if "foto" in model.lower() or "по фото" in model.lower():
        return 779
    return 649

def summarize_order(order: Dict[str, Any], lang: str) -> str:
    parts = []
    if order.get("model"): parts.append(order["model"])
    if order.get("size"): parts.append(order["size"])
    if order.get("price"): parts.append(f"{order['price']} MDL")
    return ", ".join(parts) if parts else ("Comandă" if lang == "ro" else "Заказ")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 3000)))
