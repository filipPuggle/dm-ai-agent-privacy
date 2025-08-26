import os, hmac, hashlib, json, logging, time, unicodedata
from collections import defaultdict
from typing import Dict, Iterable, Optional, Tuple

from flask import Flask, request, abort
from dotenv import load_dotenv
load_dotenv()

from openai import OpenAI  # păstrat ca să nu schimbăm nimic la env
from tools.catalog_pricing import (
    format_initial_offer_multiline,
    format_product_detail,
    format_catalog_overview,
    search_product_by_text,
    get_global_template,
)
from send_message import send_instagram_message

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# ---- envs (do NOT rename per user's constraint) ----
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
VERIFY_TOKEN   = os.getenv("IG_VERIFY_TOKEN", "").strip()
APP_SECRET     = os.getenv("IG_APP_SECRET", "").strip()  # optional

client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

# Greeting memory (o singură dată pe utilizator, TTL 1 oră)
GREETED_AT: Dict[str, float] = defaultdict(float)     # sender_id -> epoch
GREET_TTL = 60 * 60

# Dedup for message IDs (5 minutes)
SEEN_MIDS: Dict[str, float] = {}

# Remember last product a user asked about
LAST_PRODUCT: Dict[str, Optional[str]] = defaultdict(lambda: None)
USER_STATE: Dict[str, dict] = defaultdict(lambda: {
    "mode": None,                    # "p2" | None
    "awaiting_photo": False,         # așteptăm prima poză după alegerea P2
    "awaiting_confirmation": False,  # așteptăm "da/confirm" după prima poză
    "photos": 0,                     # câte poze primite în sesiune
    "last_photo_confirm_ts": 0.0,    # anti-spam pe confirmare
})
PHOTO_CONFIRM_COOLDOWN = 90 

# ---------- helpers ----------

def _norm(s: str) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    return s.lower().strip()

def _should_greet(sender_id: str, low_text: str) -> bool:
    if any(tok in low_text for tok in ("salut", "bună", "buna", "hello", "hi", "buna ziua", "bună ziua")):
        last = GREETED_AT[sender_id]
        return (time.time() - last) > GREET_TTL
    return False

def _maybe_greet(sender_id: str, low_text: str) -> None:
    if _should_greet(sender_id, low_text):
        try:
            send_instagram_message(sender_id, "Salut! Cu ce vă pot ajuta astăzi?")
            GREETED_AT[sender_id] = time.time()
        except Exception as e:
            app.logger.exception("Failed to greet: %s", e)

def _verify_signature() -> bool:
    """Optional: verify X-Hub-Signature-256 when IG_APP_SECRET is present."""
    if not APP_SECRET:
        return True  # in dev we don't verify
    sig = request.headers.get("X-Hub-Signature-256", "")
    if not sig.startswith("sha256="):
        return False
    digest = hmac.new(APP_SECRET.encode(), request.data, hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig[7:], digest)

def _iter_incoming_events(payload: Dict) -> Iterable[Tuple[str, Dict]]:
    """Yield (sender_id, message_dict) for both Messenger- and IG-style events.
    Works for messages that have text OR attachments (images, etc.)."""
    for entry in payload.get("entry", []):
        # Messenger-style
        for item in entry.get("messaging", []) or []:
            sender_id = (item.get("sender") or {}).get("id")
            msg = item.get("message") or {}
            if not sender_id or not isinstance(msg, dict):
                continue
            if ("text" in msg) or ("attachments" in msg) or ("quick_reply" in msg):
                yield sender_id, msg
        # Instagram Graph style
        for entry in payload.get("entry", []):
            for ch in entry.get("changes", []) or []:
                val = ch.get("value") or {}
                for msg in val.get("messages", []) or []:
                    if not isinstance(msg, dict):
                        continue
                from_field = msg.get("from") or val.get("from") or {}
                sender_id = from_field.get("id") if isinstance(from_field, dict) else from_field
                if not sender_id:
                    continue
                if ("text" in msg) or ("attachments" in msg) or ("quick_reply" in msg):
                    yield sender_id, msg

# ---------- routes ----------

@app.get("/health")
def health():
    return {"ok": True}, 200

@app.get("/")
def root_ok():
    return {"ok": True}, 200

# 1) Verify webhook (GET)
@app.get("/webhook")
def verify():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token and token == VERIFY_TOKEN:
        return challenge, 200
    return "Forbidden", 403

# 2) Process events (POST)
@app.post("/webhook")
def webhook():
    try:
        if not _verify_signature():
            app.logger.error("Invalid X-Hub-Signature-256")
            abort(403)

        data = request.get_json(force=True, silent=True) or {}
        app.logger.info("Incoming webhook: %s", json.dumps(data, ensure_ascii=False))

        for sender_id, msg in _iter_incoming_events(data):
            # ignore echoes
            if msg.get("is_echo"):
                continue

            text_in = (msg.get("text") or msg.get("message") or "").strip()

# Mid dedup (păstrează exact cum e la tine)
            mid = msg.get("mid") or msg.get("id")
            now = time.time()
            if mid:
                ts = SEEN_MIDS.get(mid, 0)
                if now - ts < 300:
                    continue
                SEEN_MIDS[mid] = now

            low = _norm(text_in)
            _maybe_greet(sender_id, low)
            P2_STATE_TTL = 3600  # 1h of inactivity

            st = USER_STATE[sender_id]
            last = float(st.get("last_photo_confirm_ts", 0.0))
            started = float(st.get("p2_started_ts", 0.0))  # may be 0 if not set
            anchor = max(last, started)

            if anchor and (time.time() - anchor) > P2_STATE_TTL:
                st.update({
                    "mode": None,
                    "awaiting_photo": False,
                    "awaiting_confirmation": False,
                    "photos": 0,
                    "suppress_until_ts": 0.0,
                    "p2_started_ts": 0.0,
                })
                continue

# === ATAȘAMENTE (foto) pentru fluxul P2 — prioritar ===
            attachments = (
                (msg.get("attachments") or []) or
                (msg.get("message", {}) or {}).get("attachments") or
                []
            )
            if attachments:
                st = USER_STATE[sender_id]
                in_p2_photo_flow = bool(st.get("awaiting_photo") or st.get("awaiting_confirmation"))
                if not in_p2_photo_flow:
                    continue
                
                newly = len(attachments) if isinstance(attachments, list) else 1
                st["photos"] = int(st.get("photos", 0)) + newly
                now_ts = time.time()
                suppress_until = float(st.get("suppress_until_ts", 0.0))
                if st.get("awaiting_photo") and (time.time() - st.get("last_photo_confirm_ts", 0)) > PHOTO_CONFIRM_COOLDOWN:
                        confirm = get_global_template("photo_received_confirm")
                        ask = get_global_template("confirm_question") or "Confirmați comanda?"
                        if confirm:
                            send_instagram_message(sender_id, confirm[:900])
                        send_instagram_message(sender_id, ask[:900])
                        st["awaiting_photo"] = False
                        st["awaiting_confirmation"] = True
                        st["last_photo_confirm_ts"] = now_ts
                        st["suppress_until_ts"] = now_ts + 5.0
                        continue
                if st.get("awaiting_confirmation"):
                        if now_ts < suppress_until:
                            continue
                        extra = get_global_template("photo_added")
                        if extra:
                            
                            msg_extra = (extra
                                        .replace("{count}", str(newly))
                                        .replace("{total}", str(st["photos"])))
                            send_instagram_message(sender_id, msg_extra[:900])
                        continue

                continue
     
            if not text_in:
                continue

            st = USER_STATE[sender_id]
            if st.get("awaiting_confirmation") and any(
                w in low for w in ("da", "confirm", "confirmam", "confirmăm", "ok", "hai", "sigur")
            ):
                howto = get_global_template("order_howto_dm")
                if howto:
                    send_instagram_message(sender_id, howto[:900])
                st["awaiting_confirmation"] = False
                continue    
        

            # 1) Price / offer
            if any(t in low for t in ("ce pret", "ce pret?", "pret", "pretul", "cat costa", "cât costa", "preț", "prețul", "ce preț")):
                try:
                    send_instagram_message(sender_id, format_initial_offer_multiline()[:900])
                except Exception as e:
                    app.logger.exception("send price failed: %s", e)
                continue

            # 2) Product list / catalog
            if any(x in low for x in ("ce produse ave", "vindeti", "vindeți", "lista produse", "catalog")):
                try:
                    send_instagram_message(sender_id, format_catalog_overview()[:900])
                except Exception as e:
                    app.logger.exception("send catalog failed: %s", e)
                continue

            # 3) Delivery by city / pickup
            if any(s in low for s in ("chisinau", "chișinău", "balti", "bălți", "post", "poșt", "preluare", "oficiu", "ridicare")):
                if any(s in low for s in ("chisinau", "chișinău", "preluare", "oficiu", "ridicare")):
                    reply = get_global_template("delivery_chisinau") or ""
                elif any(s in low for s in ("balti", "bălți")):
                    reply = get_global_template("delivery_balti") or ""
                else:
                    reply = get_global_template("delivery_other") or ""
                try:
                    if reply:
                        send_instagram_message(sender_id, reply[:900])
                        if any(x in low for x in ("comand", "plasa", "plasez", "finalizez")):
                            send_instagram_message(sender_id, (get_global_template("order_howto_dm") or "")[:900])
                except Exception as e:
                    app.logger.exception("send delivery failed: %s", e)
                continue

            # 4) Explicit product mention
            prod = search_product_by_text(low)
            if prod:
                try:
                    if prod.get("id") == "P3":
                        send_instagram_message(sender_id, (get_global_template("neon_redirect") or "")[:900])
                        continue
                    st = USER_STATE[sender_id]
                    if prod.get("id") == "P2" and st.get("awaiting_photo"):
                        req = get_global_template("photo_request")
                        if req:
                            send_instagram_message(sender_id, req[:900])
                        continue
                    LAST_PRODUCT[sender_id] = prod["id"]
                    send_instagram_message(sender_id, format_product_detail(prod["id"])[:900])
                    if prod.get("id") == "P2":
                        st = USER_STATE[sender_id]
                        st["mode"] = "p2"
                        st["awaiting_photo"] = True
                        st["awaiting_confirmation"] = False
                        st["photos"] = 0
                        req = get_global_template("photo_request")
                        if req:
                            send_instagram_message(sender_id, req[:900])
                except Exception as e:
                    app.logger.exception("send product detail failed: %s", e)
                continue

            # 5) Terms & delivery intro
            if any(k in low for k in ("termen", "realizare", "livrare")):
                intro = get_global_template("terms_delivery_intro")
                if intro:
                    try:
                        send_instagram_message(sender_id, intro[:900])
                    except Exception as e:
                        app.logger.exception("send terms failed: %s", e)
                continue

            # 6) How to order
            if any(x in low for x in ("comand", "plasa", "plasez", "finalizez")):
                reply = get_global_template("order_howto_dm") or (
                    "Putem prelua comanda aici în chat. Vă rog:\n\n"
                    "• Produs ales + cantitate\n• Nume complet\n• Telefon\n• Localitate + adresă\n"
                    "• Metoda de livrare (curier/poștă/oficiu)\n• Metoda de plată (numerar/transfer)"
                )
                try:
                    send_instagram_message(sender_id, reply[:900])
                except Exception as e:
                    app.logger.exception("send order howto failed: %s", e)
                continue

            # 7) More details
            if "detalii" in low:
                pid = LAST_PRODUCT.get(sender_id)
                if not pid:
                    pid = "P2" if any(k in low for k in ("poz", "foto", "fotograf")) else "P1"
                try:
                    send_instagram_message(sender_id, format_product_detail(pid)[:900])
                except Exception as e:
                    app.logger.exception("send details failed: %s", e)
                continue

            # 8) Off-topic: ignore politely
            # (No auto-reply; simply acknowledge with 200)

        return "EVENT_RECEIVED", 200
    except Exception as e:
        # Never 500 to Meta; log and ack to avoid retries loops
        app.logger.exception("Webhook handler failed: %s", e)
        return "EVENT_RECEIVED", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)