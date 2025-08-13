import hmac
import json
import logging
import os
from hashlib import sha256
from typing import Dict, Any, Tuple

from flask import Flask, request, jsonify

from templates import detect_lang, t, policy
from send_message import send_text

app = Flask(__name__)
log = logging.getLogger("webhook")
logging.basicConfig(level=logging.INFO)

VERIFY_TOKEN = os.getenv("IG_VERIFY_TOKEN", "")
APP_SECRET = os.getenv("IG_APP_SECRET")

# stări simple în memorie (pentru producție: persistă în DB/cache)
STATE: Dict[str, Dict[str, Any]] = {}
# schema flux:
# greeting -> menu -> details -> offer -> delivery -> payment -> order_fields -> confirm

def verify_signature(req) -> bool:
    if not APP_SECRET:
        return True
    sig = req.headers.get("X-Hub-Signature-256", "")
    if not sig.startswith("sha256="):
        return False
    digest = hmac.new(APP_SECRET.encode("utf-8"), msg=req.data, digestmod=sha256).hexdigest()
    return hmac.compare_digest(sig.split("=", 1)[1], digest)

@app.get("/health")
def health():
    return "ok", 200

@app.get("/")
def root():
    return jsonify({"status": "ok"}), 200

@app.get("/webhook")
def webhook_verify():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge, 200
    return "forbidden", 403

@app.post("/webhook")
def webhook_receive():
    if not verify_signature(request):
        return "invalid signature", 403

    payload = request.get_json(force=True, silent=True) or {}
    # extragem evenimente IG (generic)
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            # IG messages: value["messages"] list with {from,id,text}
            for msg in value.get("messages", []):
                if msg.get("from") and msg.get("text"):
                    user_id = msg["from"]
                    text = msg["text"]
                    handle_message(user_id, text)
    return "ok", 200

def get_lang(user_text: str, state: Dict[str, Any]) -> str:
    if "lang" in state:
        return state["lang"]
    lang = detect_lang(user_text)
    state["lang"] = lang
    return lang

def start_if_needed(uid: str, lang: str) -> None:
    if "stage" not in STATE[uid]:
        STATE[uid]["stage"] = "greeting"
        send_text(uid, t("greeting", lang))
        STATE[uid]["stage"] = "menu"
        send_text(uid, t("menu_products", lang))

def handle_message(uid: str, user_text: str) -> None:
    user_state = STATE.setdefault(uid, {})
    lang = get_lang(user_text, user_state)
    text_norm = user_text.strip().lower()

    # pornire/greeting
    if any(x in text_norm for x in ["salut", "привет", "здравствуйте", "buna", "bună", "hello", "hi"]):
        STATE[uid] = {"lang": lang, "stage": "menu", "order": {}}
        send_text(uid, t("greeting", lang))
        send_text(uid, t("menu_products", lang))
        return

    stage = user_state.get("stage", "menu")
    order = user_state.setdefault("order", {})

    # ————— MENIU PRODUSE —————
    if stage == "menu":
        # alegere produs
        if "foto" in text_norm or "poză" in text_norm or "poza" in text_norm or "по фото" in text_norm:
            order["model"] = "Lampă după poză" if lang == "ro" else "Лампа по фото"
            user_state["stage"] = "details"
            send_text(uid, t("ask_details", lang))
            return
        if "simpl" in text_norm or "прост" in text_norm:
            order["model"] = "Lampă simplă" if lang == "ro" else "Простая лампа"
            user_state["stage"] = "details"
            send_text(uid, t("ask_details", lang))
            return
        # comenzi rapide „livrare/plată”
        if any(x in text_norm for x in ["livrare", "достав", "delivery"]):
            user_state["stage"] = "delivery"
            send_delivery(uid, lang)
            return
        if any(x in text_norm for x in ["plată", "plata", "оплат", "payment"]):
            user_state["stage"] = "payment"
            send_payment(uid, lang)
            return
        # fallback: reafișăm meniul
        send_text(uid, t("menu_products", lang))
        return

    # ————— DETALII PRODUS —————
    if stage == "details":
        # extrage dimensiunea LxH simplu (ex: "15x20", "15×20")
        size = parse_size(text_norm)
        if size:
            order["size"] = size
        if any(k in text_norm for k in ["logo", "text", "poz", "фото", "текст", "лого"]):
            order["has_art"] = True

        # avem suficiente date pentru ofertă dacă există size + model
        if order.get("model") and order.get("size"):
            price = quote_price(order["model"], order["size"])
            order["price"] = price
            user_state["stage"] = "offer"
            send_text(uid, t("offer", lang, model=order["model"], size=order["size"], price=price))
            return
        # cerem ce lipsește
        send_text(uid, t("ask_details", lang))
        return

    # ————— OFERTĂ → LIVRARE —————
    if stage == "offer":
        user_state["stage"] = "delivery"
        send_delivery(uid, lang)
        return

    # ————— LIVRARE —————
    if stage == "delivery":
        # salvează opțiunea simplu
        if "chiș" in text_norm or "chis" in text_norm or "кишин" in text_norm:
            order["delivery"] = "Chișinău" if lang == "ro" else "Кишинёв"
        elif "țară" in text_norm or "tara" in text_norm or "стране" in text_norm or "почт" in text_norm:
            order["delivery"] = "În țară (poștă)" if lang == "ro" else "По стране (почта)"
        elif "ridic" in text_norm or "самовыв" in text_norm:
            order["delivery"] = "Ridicare" if lang == "ro" else "Самовывоз"

        user_state["stage"] = "payment"
        send_payment(uid, lang)
        return

    # ————— PLATĂ —————
    if stage == "payment":
        # nu validăm tipul exact; cerem câmpurile comenzii
        user_state["stage"] = "order_fields"
        send_text(uid, t("ask_order_fields", lang))
        return

    # ————— COLECTARE DATE —————
    if stage == "order_fields":
        # aici poți parsa nume/tel/adresă dacă vrei; pentru simplitate, trecem la confirmare
        user_state["stage"] = "confirm"
        order_summary = summarize_order(order, lang)
        delivery_human = order.get("delivery", "-")
        send_text(uid, t("confirm", lang, summary=order_summary, delivery=delivery_human,
                         deposit=policy("payments.deposit_mdl")))
        # reset sau rămâne pe confirm
        user_state["stage"] = "menu"
        return

    # ————— FALLBACK —————
    send_text(uid, t("fallback", lang))

def send_delivery(uid: str, lang: str):
    ch_note = policy("delivery.chisinau.time_note_ro" if lang == "ro" else "delivery.chisinau.time_note_ru")
    ct_note = policy("delivery.country.time_note_ro" if lang == "ro" else "delivery.country.time_note_ru")
    pickup = policy("delivery.pickup")
    msg = t(
        "delivery", lang,
        chisinau_note=ch_note,
        country_note=ct_note,
        pickup_address=pickup["address"],
        pickup_hours=pickup["hours"],
        pickup_note=pickup["note_ro"] if lang == "ro" else pickup["note_ru"]
    )
    send_text(uid, msg)

def send_payment(uid: str, lang: str):
    pm = policy("payments")
    methods = pm["methods_ro"] if lang == "ro" else pm["methods_ru"]
    msg = t("payment", lang, m1=methods[0], m2=methods[1], m3=methods[2], m4=methods[3], deposit=pm["deposit_mdl"])
    send_text(uid, msg)

def parse_size(text: str) -> str | None:
    seps = ["x", "×", "*"]
    for sep in seps:
        if sep in text:
            parts = text.replace(" ", "").split(sep)
            if len(parts) == 2 and all(p.isdigit() for p in parts):
                return f"{int(parts[0])}×{int(parts[1])} cm"
    return None

def quote_price(model: str, size: str) -> int:
    # prețuri de bază conform meniului standard
    if "foto" in model.lower() or "по фото" in model.lower():
        return 779
    return 649

def summarize_order(order: Dict[str, Any], lang: str) -> str:
    parts = []
    if order.get("model"):
        parts.append(order["model"])
    if order.get("size"):
        parts.append(order["size"])
    if order.get("price"):
        parts.append(f"{order['price']} MDL")
    return ", ".join(parts) if parts else ("Comandă" if lang == "ro" else "Заказ")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 3000)))
