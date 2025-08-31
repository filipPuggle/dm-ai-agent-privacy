import os
import json
import time
import hmac
import hashlib
import logging
from typing import Any, Dict, Iterable, Tuple
from collections import defaultdict  

from flask import Flask, request, abort
from dotenv import load_dotenv

from tools.catalog_pricing import (
    format_product_detail,
    search_product_by_text,
    get_global_template,
)
from send_message import send_instagram_message
from ai_router import route_message

load_dotenv() 

SESSIONS: Dict[str, Dict[str, Any]] = {}

def get_ctx(user_id: str) -> Dict[str, Any]:
    ctx = SESSIONS.setdefault(user_id, {})
    ctx.setdefault("flow", None)         # None | "order" | "photo"
    ctx.setdefault("order_city", None)   # completat automat din text
    return ctx

# Load your config once:
with open("shop_catalog.json", "r", encoding="utf-8") as f:
    SHOP = json.load(f)
CLASSIFIER_TAGS = SHOP["classifier_tags"]  # P1/P2/P3 tags
SESSION = {} 
SESSION_TTL = 6*3600

def get_session(uid: str):
    s = SESSION.get(uid)
    now = time.time()
    # curățare TTL
    for k,v in list(SESSION.items()):
        if now - v.get("updated_at",0) > SESSION_TTL:
            SESSION.pop(k, None)
    if not s:
        s = {"updated_at": now, "stage":"greeting", "slots":{}, "last_pid":"UNKNOWN"}
        SESSION[uid] = s
    return s

def save_session(uid: str, s: dict):
    s["updated_at"] = time.time()
    SESSION[uid] = s

def is_echo(msg: dict) -> bool:
    return bool(msg.get("is_echo"))


def choose_reply(nlu: dict, sess: dict) -> str:
    G = SHOP["global_templates"]
    P = {p["id"]: p for p in SHOP["products"]}
    pid = nlu.get("product_id", "UNKNOWN")
    intent = nlu.get("intent", "other")

    if intent == "greeting":
        return ""

    # P2 – lampă după poză
    elif pid == "P2" and intent in ("send_photo", "want_custom", "ask_price"):
        sess["stage"] = "awaiting_photo"
        base = P["P2"]["templates"]["detail_multiline"].format(price=P["P2"]["price"])
        return base + "\n\n" + (get_global_template("photo_request") or G.get("photo_request") or
                                "Trimiteți fotografia aici în chat.")

    # P1 – lampă simplă
    elif pid == "P1":
        sess["stage"] = "offer_done"
        return P["P1"]["templates"]["detail_multiline"].format(
            name=P["P1"]["name"], price=P["P1"]["price"]
        )

    # P3 – neon
    elif pid == "P3" or nlu.get("neon_redirect"):
        sess["stage"] = "neon_redirect"
        return G["neon_redirect"]

    # Preț / Catalog
    elif intent in ("ask_catalog", "ask_price"):
        sess["stage"] = "offer"
        return G["initial_multiline"].format(p1=P["P1"]["price"], p2=P["P2"]["price"])

    # CUM PLASEZ COMANDA
    elif intent in ("ask_order","how_to_order"):
        return G["order_howto_dm"]

    # Livrare (cu oraș)
    elif intent == "ask_delivery":
        city = (nlu.get("slots", {}) or {}).get("city", "").lower()
        if "chișinău" in city or "chisinau" in city:
            return G["delivery_chisinau"]
        elif "bălți" in city or "balti" in city:
            return G["delivery_balti"]
        else:
            return G["delivery_other"]

    # Termen realizare
    elif intent in ("ask_eta", "ask_timeline", "ask_leadtime"):
        return G["terms_delivery_intro"]

    # Off-topic
    elif intent in ("other", "ask_other", "off_topic"):
        return G["off_topic"]

    # Fallback final
    else:
        return SHOP["offer_text_templates"]["initial"].format(
            p1=P["P1"]["price"], p2=P["P2"]["price"]
        )


def handle_incoming_text(user_id: str, user_text: str) -> str:
    sess = get_session(user_id)
    try:
        nlu = route_message(user_text, CLASSIFIER_TAGS, use_openai=True)
    except Exception:
        nlu = {"product_id":"UNKNOWN","intent":"other","neon_redirect":False,"confidence":0}
    app.logger.info("NLU result: %s", json.dumps(nlu, ensure_ascii=False))

    reply = choose_reply(nlu, sess)

    # --- SYNC P2 flow when routed by NLU ---
    if sess.get("stage") == "awaiting_photo":
        st = USER_STATE[user_id]
        st["mode"]                   = "p2"
        st["awaiting_photo"]         = True
        st["awaiting_confirmation"]  = False
        st["photos"]                 = 0
        st["p2_started_ts"]          = time.time()
        st["last_photo_confirm_ts"]  = 0.0   


    save_session(user_id, sess)
    return reply



app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# ===== envs (do NOT rename per user's constraint) =====
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
VERIFY_TOKEN   = os.getenv("IG_VERIFY_TOKEN", "").strip()
APP_SECRET     = os.getenv("IG_APP_SECRET", "").strip()   # optional



# ===== greeting memory (per user, TTL 1h) =====
GREETED_AT: Dict[str, float] = defaultdict(float)   # sender_id -> epoch
GREET_TTL = 60 * 60

# ===== dedup for message IDs (5 minutes) =====
SEEN_MIDS: Dict[str, float] = {}

# ===== remember last product a user asked about =====
LAST_PRODUCT: Dict[str, str] = defaultdict(lambda: None)

# ===== P2 (lamp after photo) per-user state =====
USER_STATE: Dict[str, dict] = defaultdict(lambda: {
    "mode": None,                    # "p2" | None
    "awaiting_photo": False,         # waiting for FIRST photo after P2 chosen
    "awaiting_confirmation": False,  # waiting for "da/confirm/ok..." after first photo
    "photos": 0,                     # how many photos in this session
    "last_photo_confirm_ts": 0.0,    # anti-spam / anchor for guard
    "suppress_until_ts": 0.0,        # suppress burst of duplicate attachment events
    "p2_started_ts": 0.0,            # when P2 was activated (for recent-P2 fallback)
})

PHOTO_CONFIRM_COOLDOWN = 90   # sec between "photo fits" messages
P2_STATE_TTL           = 3600 # reset stale P2 state after 1h
RECENT_P2_WINDOW       = 600  # accept first photo if P2 chosen in last 10m

# ---------- helpers ----------
def _norm(s: str) -> str:
    return " ".join((s or "").lower().strip().split())

def _should_greet(sender_id: str, low_text: str) -> bool:
    last = GREETED_AT.get(sender_id, 0.0)
    return (time.time() - last) > GREET_TTL

def _maybe_greet(sender_id: str, low_text: str) -> None:
    if not low_text:
        return
    if any(w in low_text for w in ("salut", "bună", "buna", "hello", "hi")) and _should_greet(sender_id, low_text):
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

# Iterate incoming events (Messenger and IG styles; text OR attachments)
def _iter_incoming_events(payload: Dict) -> Iterable[Tuple[str, Dict]]:
    # Messenger-style
    for entry in payload.get("entry", []):
        for item in entry.get("messaging", []) or []:
            sender_id = (item.get("sender") or {}).get("id")
            msg = item.get("message") or {}
            if not sender_id or not isinstance(msg, dict):
                continue
            if ("text" in msg) or ("attachments" in msg) or ("quick_reply" in msg):
                yield sender_id, msg

    # Instagram Graph "changes" style
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

@app.get("/health")
def health():
    return {"ok": True}, 200

# ---------- routes ----------

# 1) Verification (GET /webhook)
@app.get("/webhook")
def verify():
    mode     = request.args.get("hub.mode")
    token    = request.args.get("hub.verify_token")
    challenge= request.args.get("hub.challenge")
    if mode == "subscribe" and token and token == VERIFY_TOKEN:
        return challenge, 200
    return "Forbidden", 403

# 2) Process events (POST /webhook)
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

            # context conversație (flow flags)
            ctx = get_ctx(sender_id)

            # text extras (nu facem early return)
            text_in = (msg.get("text") or "").strip()

            # ---- MID dedup (5 minutes) ----
            mid = msg.get("mid") or msg.get("id")
            now = time.time()
            if mid:
                ts = SEEN_MIDS.get(mid, 0)
                if now - ts < 300:
                    continue
                SEEN_MIDS[mid] = now

            # greeting pasiv (nu injectează ofertă)
            low = _norm(text_in)
            #_maybe_greet(sender_id, low)

            # ---- Tiny guard: reset stale P2 state (1h) ----
            st = USER_STATE[sender_id]
            last    = float(st.get("last_photo_confirm_ts", 0.0))
            started = float(st.get("p2_started_ts", 0.0))
            anchor  = max(last, started)
            if anchor and (time.time() - anchor) > P2_STATE_TTL:
                st.update({
                    "mode": None,
                    "awaiting_photo": False,
                    "awaiting_confirmation": False,
                    "photos": 0,
                    "suppress_until_ts": 0.0,
                    "p2_started_ts": 0.0,
                })
                # și ieșim din flow-ul foto
                ctx["flow"] = None
                ctx["order_city"] = None

            # ===== ATTACHMENTS (photos) — priority block =====
            
            
            attachments_raw = []
            path = "none"

            if isinstance(msg.get("attachments"), list):
                attachments_raw = msg["attachments"]
                path = "root.attachments"

            elif isinstance(msg.get("attachments"), dict):
                attachments_raw = [msg["attachments"]]
                path = "root.attachments(dict)"

            elif isinstance(msg.get("message"), dict) and isinstance(msg["message"].get("attachments"), list):
                attachments_raw = msg["message"]["attachments"]
                path = "message.attachments"

            elif isinstance(msg.get("message"), dict) and isinstance(msg["message"].get("attachments"), dict):
                attachments_raw = [msg["message"]["attachments"]]
                path = "message.attachments(dict)"

            attachments = [a for a in attachments_raw if isinstance(a, dict)]
            app.logger.info("ATTACHMENTS: path=%s count=%d", path, len(attachments))

            if attachments:
                get_ctx(sender_id)["flow"] = "photo"

                # defensive: face align cu state-ul vechi P2
                sess = get_session(sender_id)
                st = USER_STATE[sender_id]
                if sess.get("stage") == "awaiting_photo" and not st.get("awaiting_photo"):
                    st.update({
                        "mode": "p2",
                        "awaiting_photo": True,
                        "awaiting_confirmation": False,
                        "photos": 0,
                        "p2_started_ts": time.time(),
                    })

                recent_p2 = (st.get("mode") == "p2") and (
                    time.time() - float(st.get("p2_started_ts", 0.0)) < RECENT_P2_WINDOW
                )
                in_p2_photo_flow = bool(
                    st.get("awaiting_photo") or st.get("awaiting_confirmation") or recent_p2
                )
                if not in_p2_photo_flow:
                    st.update({
                        "mode": "p2",
                        "awaiting_photo": True,
                        "awaiting_confirmation": False,
                        "photos": 0,
                        "p2_started_ts": time.time(),
                    })
                    sess = get_session(sender_id)
                    sess["stage"] = "awaiting_photo"
                    save_session(sender_id, sess)
                    continue

                newly = len(attachments)
                st["photos"] = int(st.get("photos", 0)) + newly

                now_ts = time.time()
                suppress_until = float(st.get("suppress_until_ts", 0.0))

                if st.get("awaiting_photo") and (now_ts - float(st.get("last_photo_confirm_ts", 0.0))) > PHOTO_CONFIRM_COOLDOWN:
                    confirm = get_global_template("photo_received_confirm")
                    ask     = get_global_template("confirm_question") or "Confirmați comanda?"
                    if confirm:
                        send_instagram_message(sender_id, confirm[:900])
                    send_instagram_message(sender_id, ask[:900])

                    st["awaiting_photo"]        = False
                    st["awaiting_confirmation"] = True
                    st["last_photo_confirm_ts"] = now_ts
                    st["suppress_until_ts"]     = now_ts + 5.0
                    sess = get_session(sender_id)
                    sess["stage"] = "p2_photo_received"
                    save_session(sender_id, sess)
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

                # Fallback: ignore if not in any P2 sub-state
                continue

                # --- immediate ack on photo(s) ---
            newly = len(attachments)
            st["photos"] = int(st.get("photos", 0)) + newly

            now_ts = time.time()
            suppress_until = float(st.get("suppress_until_ts", 0.0))

            if st.get("awaiting_photo") and (now_ts - float(st.get("last_photo_confirm_ts", 0.0))) > PHOTO_CONFIRM_COOLDOWN:
                confirm = get_global_template("photo_received_confirm")
                ask     = get_global_template("confirm_question") or "Continuăm plasarea comenzii?"
                if confirm:
                    send_instagram_message(sender_id, confirm[:900])
                send_instagram_message(sender_id, ask[:900])

                st["awaiting_photo"]        = False
                st["awaiting_confirmation"] = True
                st["last_photo_confirm_ts"] = now_ts
                st["suppress_until_ts"]     = now_ts + 5.0

                sess = get_session(sender_id)
                sess["stage"] = "p2_photo_received"
                save_session(sender_id, sess)
                continue
   
            # ===== Confirmation after first photo =====
            st = USER_STATE[sender_id]
            if st.get("awaiting_confirmation") and any(
                w in low for w in ("da", "confirm", "confirmam", "confirmăm", "ok", "hai", "sigur", "yes")
            ):
                howto = get_global_template("order_howto_dm")
                if howto:
                    send_instagram_message(sender_id, howto[:900])
                st["awaiting_confirmation"] = False
                # intrăm oficial în fluxul de comandă
                get_ctx(sender_id)["flow"] = "order"
                continue

            # After handling attachments/confirm, we can skip non-text events
            if not text_in:
                continue

            # ===== 4) Explicit product mention (păstrat) =====
            prod = search_product_by_text(low)
            if prod:
                try:
                    # P3 (neon) => redirect
                    if prod.get("id") == "P3":
                        send_instagram_message(sender_id, (get_global_template("neon_redirect") or "")[:900])
                        continue

                    st = USER_STATE[sender_id]

                    # Dacă deja așteptăm foto pentru P2, doar reamintim
                    if prod.get("id") == "P2" and st.get("awaiting_photo"):
                        req = get_global_template("photo_request")
                        if req:
                            send_instagram_message(sender_id, req[:900])
                        # setăm și flow-ul foto în context
                        get_ctx(sender_id)["flow"] = "photo"
                        continue

                    LAST_PRODUCT[sender_id] = prod["id"]
                    send_instagram_message(sender_id, format_product_detail(prod["id"])[:900])

                    # Intrăm în fluxul P2: setăm state + cerem foto
                    if prod.get("id") == "P2":
                        st["mode"]                   = "p2"
                        st["awaiting_photo"]         = True
                        st["awaiting_confirmation"]  = False
                        st["photos"]                 = 0
                        st["p2_started_ts"]          = time.time()
                        # și marcăm flow-ul în context
                        get_ctx(sender_id)["flow"] = "photo"
                        req = get_global_template("photo_request")
                        if req:
                            send_instagram_message(sender_id, req[:900])

                except Exception as e:
                    app.logger.exception("send product detail failed: %s", e)
                continue

            # ===== Handle text messages using ai_router (NO initial offer) =====
            try:
                ctx = get_ctx(sender_id)  # idempotent

                result = route_message(
                    message_text=text_in,
                    classifier_tags=CLASSIFIER_TAGS,
                    use_openai=True,
                    ctx=ctx,
                    cfg=None,   # nu depindem de CATALOG aici
                )

                # --- NEW: dacă NLU spune P2 (lampă după poză) → intrăm în flow foto
                if result.get("product_id") == "P2" and result.get("intent") in {"send_photo", "want_custom", "keyword_match"}:
                    st = USER_STATE[sender_id]
                    ctx["flow"] = "photo"
                    if not st.get("awaiting_photo"):
                        st["mode"] = "p2"
                        st["awaiting_photo"] = True
                        st["awaiting_confirmation"] = False
                        st["photos"] = 0
                        st["p2_started_ts"] = time.time()
                        # mesajele tale standard
                        send_instagram_message(sender_id, format_product_detail("P2")[:900])
                        req = get_global_template("photo_request") or "Trimiteți fotografia aici în chat (portret / selfie)."
                        send_instagram_message(sender_id, req[:900])
                    continue

                # 1) suggested_reply (ex.: oraș detectat automat)
                sug = result.get("suggested_reply")
                if sug:
                    send_instagram_message(sender_id, sug[:900])
                    continue

                # 2) „Cum plasez comanda” ⇒ intrăm în fluxul ORDER
                if result.get("intent") == "ask_howto_order":
                    ctx["flow"] = "order"
                    order_prompt = (
                        get_global_template("order_start")
                        or "Putem prelua comanda aici în chat. Vă rugăm: • Nume complet • Telefon • Localitate și adresă • Metoda de livrare (curier/poștă/oficiu) • Metoda de plată (numerar/transfer)."
                    )
                    send_instagram_message(sender_id, order_prompt[:900])
                    continue

                # 3) Livrare: răspuns scurt, fără ofertă implicită
                if result.get("delivery_intent") or result.get("intent") == "ask_delivery":
                    delivery_short = (
                        get_global_template("delivery_short")
                        or "Putem livra prin curier în ~1 zi lucrătoare; livrarea costă ~65 lei. Spuneți-ne localitatea ca să confirmăm."
                    )
                    send_instagram_message(sender_id, delivery_short[:900])
                    continue

                # 4) Greeting scurt, fără ofertă (dacă ai dezactivat _maybe_greet)
                if result.get("greeting"):
                    send_instagram_message(sender_id, "Salut! Cu ce vă pot ajuta astăzi?")
                    continue

                # 5) Forțează eliminarea oricărei „oferte inițiale”
                force_no_offer = (ctx.get("flow") in {"order", "photo"}) or result.get("suppress_initial_offer", True)

                # 6) Pipeline-ul tău existent
                reply_text = handle_incoming_text(sender_id, text_in)

                # Gardă locală anti-ofertă inițială (peste blocklist din send_message)
                if force_no_offer and reply_text and reply_text.lstrip().startswith("Bună ziua! Avem modele simple la"):
                    reply_text = None

                if reply_text:
                    send_instagram_message(sender_id, reply_text[:900])

            except Exception as e:
                app.logger.exception("ai_router handling failed: %s", e)

        return "OK", 200
    except Exception as e:  # <- aliniat cu 'try:' de la linia 258
        app.logger.exception("Webhook handler failed: %s", e)
        return "Internal Server Error", 500



if __name__ == "__main__":
    # Keep default Railway port if provided; no env var renames
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8080")), debug=False)
