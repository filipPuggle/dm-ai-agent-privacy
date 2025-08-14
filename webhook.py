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

VERIFY_TOKEN = (os.getenv("IG_VERIFY_TOKEN") or "").strip()
APP_SECRET = (os.getenv("IG_APP_SECRET") or "").strip()

STATE: Dict[str, Dict[str, Any]] = {}     # stocăm starea simplă în memorie
PROCESSED_MIDS = set()                    # pentru a evita duplicatele IG

# --- Health & root ---
@app.get("/health")
def health():
    return "ok", 200

@app.get("/")
def root():
    return jsonify({"status": "ok"}), 200

# --- Webhook verify (GET) ---
@app.get("/webhook")
def webhook_verify():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge or "", 200
    return "forbidden", 403

# --- Signature check ---
def _verify_signature(req) -> bool:
    if not APP_SECRET:
        return True
    sig = req.headers.get("X-Hub-Signature-256", "")
    if not sig.startswith("sha256="):
        return False
    digest = hmac.new(APP_SECRET.encode("utf-8"), msg=req.data, digestmod=sha256).hexdigest()
    return hmac.compare_digest(sig.split("=", 1)[1], digest)

# --- Helpers pentru trimitere sigură ---
def safe_send(uid: str, text: str):
    try:
        if text and text.strip():
            send_text(uid, text)
    except Exception as e:
        log.error("❌ send failed: %s", e)

# --- Extractor robust de mesaje IG ---
def _extract_messages(payload: dict):
    """
    Yield {from_id, text, mid, is_echo} din:
      - entry[].messaging[]
      - entry[].changes[].value{messages[], from, text/message}
    """
    for entry in payload.get("entry", []):
        # 1) Variantă 'messaging' (ca la Messenger/IG webhook V16+)
        for m in (entry.get("messaging") or []):
            msg = m.get("message") or {}
            from_id = (m.get("sender") or {}).get("id")
            text = msg.get("text")
            mid = msg.get("mid") or m.get("id")
            is_echo = bool(msg.get("is_echo"))
            if from_id and (text or is_echo):
                yield {"from_id": from_id, "text": text, "mid": mid, "is_echo": is_echo}

        # 2) Variantă 'changes'
        for ch in (entry.get("changes") or []):
            val = ch.get("value") or {}
            # 2a) value.messages[]
            for mm in (val.get("messages") or []):
                _from = mm.get("from")
                from_id = (_from.get("id") if isinstance(_from, dict) else _from)
                text = mm.get("text") if isinstance(mm.get("text"), str) else (mm.get("message") or {}).get("text")
                mid = mm.get("id") or (mm.get("message") or {}).get("mid")
                is_echo = bool(mm.get("is_echo"))
                if from_id and (text or is_echo):
                    yield {"from_id": from_id, "text": text, "mid": mid, "is_echo": is_echo}
            # 2b) direct în value
            _from2 = val.get("from")
            from_id = (_from2.get("id") if isinstance(_from2, dict) else _from2)
            text = (val.get("text") if isinstance(val.get("text"), str)
                    else (val.get("message") or {}).get("text")
                    or (val.get("message") if isinstance(val.get("message"), str) else None))
            mid = val.get("id") or (val.get("message") or {}).get("mid")
            is_echo = bool(val.get("is_echo"))
            if from_id and (text or is_echo):
                yield {"from_id": from_id, "text": text, "mid": mid, "is_echo": is_echo}

# --- Webhook receive (POST) ---
@app.post("/webhook")
def webhook_receive():
    if not _verify_signature(request):
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

        # Ignorăm reply-urile proprii (Meta trimite 'echo' când pagina a trimis deja un mesaj)
        if msg.get("is_echo"):
            continue

        uid = msg["from_id"]
        text = (msg.get("text") or "").strip()
        log.info("➡️ INCOMING IG TEXT from=%s: %s", uid, text)
        handle_message(uid, text)

    if not had:
        log.info("ℹ️ Webhook fără mesaje text relevante.")
    return "ok", 200

# --- Dialog flow simplu, structurat RO/RU ---
def get_lang(user_text: str, state: Dict[str, Any]) -> str:
    if "lang" in state:
        return state["lang"]
    lang = detect_lang(user_text)
    state["lang"] = lang
    return lang

def handle_message(uid: str, user_text: str) -> None:
    st = STATE.setdefault(uid, {})
    lang = get_lang(user_text, st)
    txt = (user_text or "").strip().lower()
    order = st.setdefault("order", {})
    stage = st.get("stage")

    # Start / greeting
    if stage is None or any(x in txt for x in ["salut", "buna", "bună", "привет", "здравствуйте", "hello", "hi"]):
        STATE[uid] = {"lang": lang, "stage": "menu", "order": {}}
        safe_send(uid, t("greeting", lang))
        safe_send(uid, t("menu_products", lang))
        return

    # Meniu produse
    if stage == "menu":
        if any(k in txt for k in ["poz", "poza", "foto", "по фото"]):
            order["model"] = "Lampă după poză" if lang == "ro" else "Лампа по фото"
            st["stage"] = "details"
            safe_send(uid, t("ask_details", lang))
            return
        if any(k in txt for k in ["simpl", "прост"]):
            order["model"] = "Lampă simplă" if lang == "ro" else "Простая лампа"
            st["stage"] = "details"
            safe_send(uid, t("ask_details", lang))
            return
        if any(x in txt for x in ["livrare", "достав", "delivery"]):
            st["stage"] = "delivery"; send_delivery(uid, lang); return
        if any(x in txt for x in ["plată", "plata", "оплат", "payment"]):
            st["stage"] = "payment"; send_payment(uid, lang); return
        safe_send(uid, t("menu_products", lang))
        return

    # Colectare detalii (dimensiune, art)
    if stage == "details":
        size = parse_size(txt)
        if size: order["size"] = size
        if any(k in txt for k in ["logo", "text", "poz", "фото", "текст", "лого"]):
            order["has_art"] = True
        if order.get("model") and order.get("size"):
            price = quote_price(order["model"], order["size"]); order["price"] = price
            st["stage"] = "offer"
            safe_send(uid, t("offer", lang, model=order["model"], size=order["size"], price=price))
            return
        safe_send(uid, t("ask_details", lang))
        return

    # Ofertă -> livrare
    if stage == "offer":
        st["stage"] = "delivery"; send_delivery(uid, lang); return

    # Livrare -> plată
    if stage == "delivery":
        if "chiș" in txt or "chis" in txt or "кишин" in txt:
            order["delivery"] = "Chișinău" if lang == "ro" else "Кишинёв"
        elif "țară" in txt or "tara" in txt or "стране" in txt or "почт" in txt:
            order["delivery"] = "În țară (poștă)" if lang == "ro" else "По стране (почта)"
        elif "ridic" in txt or "самовыв" in txt:
            order["delivery"] = "Ridicare" if lang == "ro" else "Самовывоз"
        st["stage"] = "payment"; send_payment(uid, lang); return

    # Plată -> formulare
    if stage == "payment":
        st["stage"] = "order_fields"
        safe_send(uid, t("ask_order_fields", lang)); return

    # Colectare date -> confirmare
    if stage == "order_fields":
        st["stage"] = "confirm"
        summary = summarize_order(order, lang)
        delivery_h = order.get("delivery", "-")
        safe_send(uid, t("confirm", lang, summary=summary, delivery=delivery_h, deposit=policy("payments.deposit_mdl")))
        st["stage"] = "menu"
        return

    # Fallback
    safe_send(uid, t("fallback", lang))

# --- Mesaje auxiliare ---
def send_delivery(uid: str, lang: str):
    ch_note = policy("delivery.chisinau.time_note_ro" if lang == "ro" else "delivery.chisinau.time_note_ru")
    ct_note = policy("delivery.country.time_note_ro" if lang == "ro" else "delivery.country.time_note_ru")
    pickup = policy("delivery.pickup")
    msg = t("delivery", lang,
            chisinau_note=ch_note, country_note=ct_note,
            pickup_address=pickup["address"], pickup_hours=pickup["hours"],
            pickup_note=pickup["note_ro"] if lang == "ro" else pickup["note_ru"])
    safe_send(uid, msg)

def send_payment(uid: str, lang: str):
    pm = policy("payments")
    methods = pm["methods_ro"] if lang == "ro" else pm["methods_ru"]
    msg = t("payment", lang, m1=methods[0], m2=methods[1], m3=methods[2], m4=methods[3], deposit=pm["deposit_mdl"])
    safe_send(uid, msg)

# --- Utilities ---
def parse_size(text: str) -> Optional[str]:
    for sep in ("x", "×", "*"):
        if sep in text:
            p = text.replace(" ", "").split(sep)
            if len(p) == 2 and all(s.isdigit() for s in p):
                return f"{int(p[0])}×{int(p[1])} cm"
    return None

def quote_price(model: str, size: str) -> int:
    return 779 if ("foto" in model.lower() or "по фото" in model.lower()) else 649

def summarize_order(order: Dict[str, Any], lang: str) -> str:
    parts = []
    if order.get("model"): parts.append(order["model"])
    if order.get("size"): parts.append(order["size"])
    if order.get("price"): parts.append(f"{order['price']} MDL")
    return ", ".join(parts) if parts else ("Comandă" if lang == "ro" else "Заказ")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 3000)))
