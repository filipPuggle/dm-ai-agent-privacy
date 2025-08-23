import os, hmac, hashlib, json, logging, re, time
from flask import Flask, request, abort
from dotenv import load_dotenv
from send_message import send_instagram_message

load_dotenv()
app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")

VERIFY_TOKEN = (os.getenv("IG_VERIFY_TOKEN") or "").strip()
APP_SECRET   = (os.getenv("IG_APP_SECRET") or "").strip()

# ----------------- Context / Templates (din context.json) -------------------
try:
    with open("context.json", "r", encoding="utf-8") as f:
        CTX = json.load(f)
except Exception as e:
    CTX = {}
    app.logger.error("Nu pot încărca context.json: %s", e)

T = CTX.get("templates", {})
R = CTX.get("rules", {})
P = CTX.get("prices", {"lamp_simple": 650, "lamp_photo": 779})

# TTL memorie: din context, altfel 120 min
SESSION_TTL = int(R.get("memory", {}).get("thread_ttl_minutes", 120)) * 60
GREET_ONCE_MIN = int(R.get("greeting_once_minutes", 30))
GREET_SEQ      = R.get("greeting_sequence", ["greeting", "lamp_intro"])
SHOW_INTRO     = bool(R.get("show_lamp_intro_after_greeting", True))

# ---------------------- MEMORIE simplă per utilizator -----------------------
# sessions[user_id] = {
#   "state": greet|need|offer|confirm|handoff,
#   "history": [..ultimele 5..],
#   "human": False,
#   "slots": { produs, nume, telefon, localitate, localitate_key },
#   "ts": epoch_sec,
#   "last_greet_ts": epoch_sec
# }
sessions = {}

YES_WORDS = {"da","ok","okay","confirm","confirmare","vreau","hai","perfect","sigur","merge","dorim","doriți","dorit"}
PHONE_RE = re.compile(r'(?:\+?373|0)\s?\d{8}|(?:\+?\d[\d\s\-]{6,}\d)')
BENEFIT_WORDS = ("beneficii", "avantaje", "ce are", "ce include", "ce oferă")

# ---------- Aliases & routing pentru livrare/plată (din context.json) -------
ALIASES = CTX.get("aliases", {})
PROD_SYNS = ALIASES.get("product_synonyms_ro", {})
DELIVERY_WORDS = set(ALIASES.get("delivery_words_ro", []))
PAYMENT_WORDS  = set(ALIASES.get("payment_words_ro", []))
CITY_ALIASES   = ALIASES.get("cities", {})

DELIVERY_ROUTING = R.get("delivery_routing", {})
CITY_MAP = DELIVERY_ROUTING.get("city_map_ro", {})             # ex: {"Chișinău":"delivery_options_chisinau", ...}
DEFAULT_DELIVERY_TPL = DELIVERY_ROUTING.get("default_template","delivery_options_outside")

# ------------------------------ Helpers -------------------------------------
def _expired(s):
    return (time.time() - s.get("ts", 0)) > SESSION_TTL

def _get_session(uid: str):
    now = time.time()
    s = sessions.get(uid)
    if not s or _expired(s):
        s = {"state":"greet","history":[],"human":False,"slots":{}, "ts":now, "last_greet_ts":0}
    else:
        s["ts"] = now
    sessions[uid] = s
    return s

def _send(uid: str, text: str):
    if not text:
        return
    try:
        # IG are limită de lungime; tăiem defensiv
        send_instagram_message(uid, text[:900])
    except Exception as e:
        app.logger.exception("Instagram send error: %s", e)

def _send_tpl_lines(uid: str, tpl_lines):
    """Trimite un singur mesaj concatenat dintr-o listă de linii (evităm spam)."""
    if isinstance(tpl_lines, list):
        _send(uid, "\n".join([str(x) for x in tpl_lines if x]))
    elif isinstance(tpl_lines, str):
        _send(uid, tpl_lines)

def _lang(text: str) -> str:
    # Simplu: dacă are chirilice -> ru, altfel ro
    if re.search(r"[А-Яа-яЁё]", text):
        return "ru"
    return "ro"

def _tpl(name: str, lang: str):
    node = T.get(name, {})
    return node.get(lang) or node.get("ro") or node

def _detect_produs(text: str):
    t = text.lower()
    for key, variants in PROD_SYNS.items():
        for v in variants:
            if v in t:
                return key  # "lamp_simple" / "lamp_photo"
    # fallback rapid
    if "poz" in t or "foto" in t or "fotograf" in t:
        return "lamp_photo"
    if "simpl" in t:
        return "lamp_simple"
    return None

def _extract_contact(text: str):
    phone = None
    m = PHONE_RE.search(text)
    if m:
        phone = re.sub(r"\D+", "", m.group(0))
    name_candidate = text
    if m:
        name_candidate = (text[:m.start()] + " " + text[m.end():]).strip()
    name_candidate = re.sub(r"[\n\r\t]+", " ", name_candidate).strip()
    name = name_candidate if len(name_candidate) >= 3 else None
    return (name, phone)

def _city_from_text(text: str):
    t = text.lower()
    for key, variants in CITY_ALIASES.items():
        for v in variants:
            if v.lower() in t:
                return key  # ex: "chisinau", "balti"
    return None

def _faq_router(uid: str, text: str, s: dict, lang: str) -> bool:
    """Răspunsuri la livrare / termen / plată / cum comand — din ORICE stare."""
    low = text.lower()

    # 1) Livrare (curier, poștă, metode, ridicare...)
    if any(w in low for w in DELIVERY_WORDS):
        # oraș din slots sau text
        city_key = s["slots"].get("localitate_key") or _city_from_text(text)
        if city_key:
            s["slots"]["localitate_key"] = city_key

        # alege șablon în funcție de denumirea "frumoasă" din CITY_MAP, altfel default
        chosen_tpl = DEFAULT_DELIVERY_TPL
        for nice_city, tpl_key in CITY_MAP.items():
            if nice_city.lower() in low:
                chosen_tpl = tpl_key
                break
        _send_tpl_lines(uid, _tpl(chosen_tpl, lang))
        _send_tpl_lines(uid, _tpl("ask_delivery_method", lang))
        return True

    # 2) Termen/în cât timp
    if any(x in low for x in ["în cât timp","in cat timp","când e gata","cand e gata","termen","deadline","durata","cat dureaza","cât durează"]):
        _send_tpl_lines(uid, _tpl("lead_time_shipping_questions", lang))
        return True

    # 3) Plată / metode de plată
    if any(w in low for w in PAYMENT_WORDS):
        methods = CTX.get("policies", {}).get("payments", {}).get("methods_ro" if lang=="ro" else "methods_ru", [])
        if methods:
            _send(uid, "Metode de plată:\n- " + "\n- ".join(methods))
            return True

    # 4) „Cum se plasează comanda?”
    if "cum se placeaza" in low or "cum se plaseaza" in low or ("cum" in low and "comand" in low):
        _send_tpl_lines(uid, _tpl("ask_delivery_data", lang))
        return True

    return False

# -------------------------- Fluxul pe stări (FSM) ---------------------------
def handle(uid: str, text_in: str):
    s = _get_session(uid)
    s["history"] = (s["history"] + [text_in])[-5:]
    lang = _lang(text_in)
    low  = text_in.strip().lower()

    # comenzi rapide
    if low == "uman":
        s["human"] = True
        _send(uid, "Am predat conversația colegului meu. Veți fi contactat în scurt timp. ✅")
        return
    if low == "reset":
        sessions[uid] = {"state":"greet","history":[],"human":False,"slots":{}, "ts":time.time(), "last_greet_ts":0}
        _send(uid, "Am resetat conversația. Salut! Cu ce vă pot ajuta?")
        return

    if s["human"]:
        app.logger.info("User %s în handoff/human. Ignorăm auto-răspuns.", uid)
        return

    state = s["state"]
    slots = s["slots"]

    # -------- GREET (o dată per interval) --------
    now = time.time()
    should_greet = (state == "greet") and ((now - s.get("last_greet_ts", 0)) > GREET_ONCE_MIN * 60)
    if should_greet:
        for key in GREET_SEQ:  # ex: ["greeting","lamp_intro"]
            tpl = _tpl(key, lang)
            if tpl:
                _send_tpl_lines(uid, tpl)
        s["last_greet_ts"] = now
        s["state"] = "need"
        return  # IMPORTANT: nu continuăm în aceeași apelare

    # -------- NEED: alegere tip produs --------
    if state in ("greet","need"):
        produs = _detect_produs(text_in)
        if produs:
            slots["produs"] = produs
            s["state"] = "offer"
            if produs == "lamp_simple":
                _send_tpl_lines(uid, _tpl("lamp_simple_preset", lang))
            else:
                _send_tpl_lines(uid, _tpl("lamp_photo_preset", lang))
            _send(uid, "Continuăm?")
            return

        # întrebări generale (livrare/termene/plată) permise înainte de alegerea tipului
        if _faq_router(uid, text_in, s, lang):
            return

        # dacă nu înțelegem încă tipul, întrebare scurtă + preț
        _send(uid, f"Aveți în vedere o Lampă simplă ({P.get('lamp_simple')} lei) sau Lampă după poză ({P.get('lamp_photo')} lei)?")
        return

    # -------- OFFER: răspuns la beneficii / acceptare --------
    if state == "offer":
        if any(w in low for w in BENEFIT_WORDS):
            if slots.get("produs") == "lamp_simple":
                _send_tpl_lines(uid, _tpl("lamp_simple_preset", lang))
            else:
                _send_tpl_lines(uid, _tpl("lamp_photo_preset", lang))
            _send(uid, "Continuăm?")
            return

        if any(w in low for w in YES_WORDS):
            _send(uid, "Perfect. Pentru înregistrare am nevoie de Nume și Telefon (ex: Ion Popescu 060000000).")
            s["state"] = "confirm"
            return

        # schimbare de produs în timpul discuției
        new_prod = _detect_produs(text_in)
        if new_prod and new_prod != slots.get("produs"):
            slots["produs"] = new_prod
            if new_prod == "lamp_simple":
                _send_tpl_lines(uid, _tpl("lamp_simple_preset", lang))
            else:
                _send_tpl_lines(uid, _tpl("lamp_photo_preset", lang))
            _send(uid, "Continuăm?")
            return

        if _faq_router(uid, text_in, s, lang):
            return

        _send(uid, "Pot ajusta oferta. Doriți Lampă simplă sau Lampă după poză? Sau spuneți ce vă doriți exact.")
        return

    # -------- CONFIRM: colectăm nume + telefon, apoi handoff --------
    if state == "confirm":
        name, phone = _extract_contact(text_in)
        if phone and not slots.get("telefon"):
            slots["telefon"] = phone
        if name and not slots.get("nume"):
            slots["nume"] = name

        # răspunde și la întrebări în paralel
        if _faq_router(uid, text_in, s, lang):
            need_fields = [k for k in ("nume","telefon") if not slots.get(k)]
            if need_fields:
                _send(uid, "Între timp, pentru înregistrare mai am nevoie de: " + " și ".join(need_fields) + ".")
            return

        need_fields = [k for k in ("nume","telefon") if not slots.get(k)]
        if need_fields:
            _send(uid, "Mulțumesc. Mai am nevoie de: " + " și ".join(need_fields) + ".")
            return

        # avem nume + telefon => rezumat + handoff
        prod_label = CTX.get("product_names", {}).get(slots.get("produs"), "Lampă")
        price_label = P.get("lamp_simple") if slots.get("produs") == "lamp_simple" else P.get("lamp_photo")
        summary = f"Comanda: {prod_label} — {price_label} lei.\nNume: {slots['nume']}\nTelefon: {slots['telefon']}\nMulțumim!"
        _send(uid, summary)

        _send(uid, "Predau conversația colegului meu. Veți fi contactat în scurt timp pentru confirmare și livrare. ✅")
        s["state"] = "handoff"
        s["human"] = True
        return

    # -------- HANDOFF: nu mai auto-răspundem --------
    if state == "handoff":
        s["human"] = True
        return

# --------------------------- Infra Instagram webhook ------------------------
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

def _verify_signature() -> bool:
    if not APP_SECRET:
        return True  # în dev ignorăm semnătura
    sig = request.headers.get("X-Hub-Signature-256", "")
    if not sig.startswith("sha256="):
        return False
    digest = hmac.new(APP_SECRET.encode(), request.data, hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig[7:], digest)

@app.post("/webhook")
def webhook():
    if not _verify_signature():
        app.logger.error("Invalid X-Hub-Signature-256")
        abort(403)

    data = request.get_json(force=True, silent=True) or {}
    app.logger.info("Incoming webhook: %s", json.dumps(data, ensure_ascii=False))

    def _handle_msg(obj):
        sender_id = (obj.get("sender") or {}).get("id")
        message   = obj.get("message") or {}
        text_in   = (message.get("text") or "").strip()
        if sender_id and text_in:
            handle(sender_id, text_in)

    for entry in data.get("entry", []):
        # Format A: entry.messaging[]
        for m in entry.get("messaging", []):
            _handle_msg(m)
        # Format B: entry.changes[].value.{sender, message, messaging_product:"instagram"}
        for change in entry.get("changes", []):
            val = change.get("value", {})
            if val.get("messaging_product") == "instagram":
                _handle_msg(val)

    return "EVENT_RECEIVED", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
