import os, hmac, hashlib, json, logging, re, time
from flask import Flask, request, abort
from dotenv import load_dotenv
from send_message import send_instagram_message  # rămâne neschimbat

load_dotenv()
app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

VERIFY_TOKEN = (os.getenv("IG_VERIFY_TOKEN") or "").strip()
APP_SECRET   = (os.getenv("IG_APP_SECRET") or "").strip()
SESSION_TTL  = int(os.getenv("SESSION_TTL_SECONDS", "7200"))  # 2h default

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

GREET_ONCE_MIN = int(R.get("greeting_once_minutes", 30))
GREET_SEQ      = R.get("greeting_sequence", ["greeting", "lamp_intro"])
SHOW_INTRO     = bool(R.get("show_lamp_intro_after_greeting", True))

# ---------------------- MEMORIE simplă per utilizator -----------------------
# sessions[user_id] = {
#   "state": greet|need|offer|confirm|handoff,
#   "history": [..ultimele 5..],
#   "human": False,
#   "slots": { produs, nume, telefon },
#   "ts": epoch_sec,
#   "last_greet_ts": epoch_sec
# }
sessions = {}

YES_WORDS = {"da","ok","okay","confirm","confirmare","vreau","hai","perfect","sigur","merge","dorim","doriți","dorit"}
PHONE_RE = re.compile(r'(?:\+?373|0)\s?\d{8}|(?:\+?\d[\d\s\-]{6,}\d)')
BENEFIT_WORDS = ("beneficii", "avantaje", "ce are", "ce include", "ce oferă")

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
        send_instagram_message(uid, text[:900])  # ig limit defensiv
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
    # sinonime din context.json (dacă există)
    for syn in CTX.get("aliases", {}).get("product_synonyms_ro", {}).get("lamp_simple", []):
        if syn in t:
            return "lamp_simple"
    for syn in CTX.get("aliases", {}).get("product_synonyms_ro", {}).get("lamp_photo", []):
        if syn in t:
            return "lamp_photo"
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
        for key in GREET_SEQ:
            tpl = _tpl(key, lang)
            if tpl:
                _send_tpl_lines(uid, tpl)
        s["last_greet_ts"] = now
        s["state"] = "need"
        if not SHOW_INTRO:
            return
        # dacă avem intro, a fost deja trimis în GREET_SEQ

    # -------- NEED: alegere tip produs --------
    if state in ("greet","need"):
        produs = _detect_produs(text_in)
        if produs:
            slots["produs"] = produs
            s["state"] = "offer"
            # trimitem presetul corect (beneficii + preț) din context
            if produs == "lamp_simple":
                _send_tpl_lines(uid, _tpl("lamp_simple_preset", lang))
            else:
                _send_tpl_lines(uid, _tpl("lamp_photo_preset", lang))
            _send(uid, "Continuăm?")
            return
        # dacă userul cere „beneficii” înainte să aleagă tipul -> dăm intro
        if any(w in low for w in BENEFIT_WORDS):
            _send_tpl_lines(uid, _tpl("lamp_intro", lang))
            return
        # dacă nu înțelegem încă tipul, repetăm întrebarea cu prețurile din context
        _send(uid, f"Aveți în vedere o Lampă simplă ({P.get('lamp_simple')} lei) sau Lampă după poză ({P.get('lamp_photo')} lei)?")
        return

    # -------- OFFER: răspuns la beneficii / acceptare --------
    if state == "offer":
        # întrebări de beneficii -> presetul aferent tipului ales
        if any(w in low for w in BENEFIT_WORDS):
            if slots.get("produs") == "lamp_simple":
                _send_tpl_lines(uid, _tpl("lamp_simple_preset", lang))
            else:
                _send_tpl_lines(uid, _tpl("lamp_photo_preset", lang))
            _send(uid, "Continuăm?")
            return

        # accept ofertă?
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

        _send(uid, "Pot ajusta oferta. Doriți Lampă simplă sau Lampă după poză? Sau spuneți ce vă doriți exact.")
        return

    # -------- CONFIRM: colectăm nume + telefon, apoi handoff --------
    if state == "confirm":
        name, phone = _extract_contact(text_in)
        if phone and not slots.get("telefon"):
            slots["telefon"] = phone
        if name and not slots.get("nume"):
            slots["nume"] = name

        need_fields = [k for k in ("nume","telefon") if not slots.get(k)]
        if need_fields:
            missing = " și ".join(need_fields)
            _send(uid, f"Mulțumesc. Mai am nevoie de: {missing}.")
            return

        produs_label = "Lampă simplă" if slots.get("produs") == "lamp_simple" else "Lampă după poză"
        price_label  = P.get("lamp_simple") if slots.get("produs") == "lamp_simple" else P.get("lamp_photo")
        summary = f"Comanda: {produs_label} — {price_label} lei.\nNume: {slots['nume']}\nTelefon: {slots['telefon']}\nMulțumim!"
        _send(summary)

        # handoff
        _send("Predau conversația colegului meu. Veți fi contactat în scurt timp pentru confirmare și livrare. ✅")
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
        # Format A (ce ai tu în log): entry.messaging[]
        for m in entry.get("messaging", []):
            _handle_msg(m)
        # Format B (alt tip IG): entry.changes[].value.{sender, message, messaging_product:"instagram"}
        for change in entry.get("changes", []):
            val = change.get("value", {})
            if val.get("messaging_product") == "instagram":
                _handle_msg(val)

    return "EVENT_RECEIVED", 200
