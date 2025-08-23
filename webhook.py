import os, hmac, hashlib, json, logging, re, time
from flask import Flask, request, abort
from dotenv import load_dotenv
from send_message import send_instagram_message  # folosește funcția existentă

load_dotenv()
app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

VERIFY_TOKEN = (os.getenv("IG_VERIFY_TOKEN") or "").strip()
APP_SECRET   = (os.getenv("IG_APP_SECRET") or "").strip()  # opțional
SESSION_TTL  = int(os.getenv("SESSION_TTL_SECONDS", "86400"))  # 24h default

# --- încărcăm contextul existent (prețuri/texte), dar fluxul e determinist ---
try:
    with open("context.json", "r", encoding="utf-8") as f:
        CTX = json.load(f)
except Exception:
    CTX = {}
PRICES = CTX.get("prices", {})
PRICE_SIMPLE = PRICES.get("lamp_simple", 650)
PRICE_PHOTO  = PRICES.get("lamp_photo", 780)

# ---------------------- MEMORIE simplă per utilizator -----------------------
# structura: sessions[user_id] = {
#   "state": "greet|need|offer|confirm|handoff",
#   "history": [ultimele 5 mesaje],
#   "human": False,        # după handoff -> nu mai răspundem automat
#   "slots": { "produs":..., "nume":..., "telefon":... },
#   "ts": epoch_sec        # pentru TTL
# }
sessions = {}

YES_WORDS = {"da","ok","okay","confirm","confirmare","vreau","hai","perfect","sigur","merge","dorim","doriți","dorit"}
PHONE_RE = re.compile(r'(?:\+?373|0)\s?\d{8}|(?:\+?\d[\d\s\-]{6,}\d)')

def _expired(s):
    return (time.time() - s.get("ts", 0)) > SESSION_TTL

def _get_session(uid: str):
    now = time.time()
    s = sessions.get(uid)
    if not s or _expired(s):
        s = {"state":"greet","history":[],"human":False,"slots":{}, "ts":now}
    else:
        s["ts"] = now
    sessions[uid] = s
    return s

def _detect_produs(text: str):
    t = text.lower()
    if "poz" in t or "foto" in t or "fotograf" in t:
        return "lamp_photo"
    if "simpl" in t:
        return "lamp_simple"
    return None

def _extract_contact(text: str):
    """încearcă să extragă nume și telefon dintr-un mesaj liber"""
    phone = None
    m = PHONE_RE.search(text)
    if m:
        phone = re.sub(r"\D+", "", m.group(0))
    # nume = restul textului fără telefon, curățat
    name_candidate = text
    if m:
        name_candidate = (text[:m.start()] + " " + text[m.end():]).strip()
    name_candidate = re.sub(r"[\n\r\t]+", " ", name_candidate).strip()
    # dacă e prea scurt/vid, lăsăm None
    name = name_candidate if len(name_candidate) >= 3 else None
    return (name, phone)

def _send(uid: str, text: str):
    if not text:
        return
    try:
        # Instagram limitează lungimea; tăiem defensiv la ~900 chars
        send_instagram_message(uid, text[:900])
    except Exception as e:
        app.logger.exception("Instagram send error: %s", e)

def _send_many(uid: str, msgs):
    for m in msgs:
        _send(uid, m)

# -------------------------- Fluxul pe stări (FSM) ---------------------------
def handle(uid: str, text_in: str):
    s = _get_session(uid)
    s["history"] = (s["history"] + [text_in])[-5:]

    # Comenzi rapide:
    low = text_in.strip().lower()
    if low == "uman":
        s["human"] = True
        _send(uid, "Am predat conversația colegului meu. Veți fi contactat în scurt timp. ✅")
        return
    if low == "reset":
        sessions[uid] = {"state":"greet","history":[],"human":False,"slots":{}, "ts":time.time()}
        _send(uid, "Am resetat conversația. Salut! Cu ce vă pot ajuta? (lampă simplă / lampă după poză)")
        return

    if s["human"]:
        # după handoff NU mai răspundem
        app.logger.info("User %s este în modul human/handoff. Ignorăm auto-răspunsul.", uid)
        return

    state = s["state"]
    slots = s["slots"]

    if state == "greet":
        # salut + întrebare de nevoie
        greet_text = "Bună ziua! 👋"
        need_q = f"Cu ce vă pot ajuta? Aveți în vedere o Lampă simplă ({PRICE_SIMPLE} lei) sau Lampă după poză ({PRICE_PHOTO} lei)?"
        _send_many(uid, [greet_text, need_q])
        s["state"] = "need"
        return

    if state == "need":
        produs = _detect_produs(text_in)
        if produs:
            slots["produs"] = produs
            # mergem la ofertă potrivită
            if produs == "lamp_simple":
                _send(uid, f"Oferta: Lampă simplă {PRICE_SIMPLE} lei. Are 16 culori și telecomandă. Continuăm?")
            else:
                _send(uid, f"Oferta: Lampă după poză {PRICE_PHOTO} lei. Facem machetă și o aprobăm cu dvs. Continuăm?")
            s["state"] = "offer"
            return
        # nu am înțeles produsul -> clarificare
        _send(uid, f"Vă rog să-mi spuneți tipul: Lampă simplă ({PRICE_SIMPLE} lei) sau Lampă după poză ({PRICE_PHOTO} lei)?")
        return

    if state == "offer":
        # acceptare oferte
        if any(w in low for w in YES_WORDS):
            _send(uid, "Perfect. Pentru înregistrare am nevoie de Nume și Telefon (de ex: Ion Popescu 060000000).")
            s["state"] = "confirm"
            return
        # altfel, încercăm să pivotăm
        _send(uid, "Pot ajusta oferta. Doriți Lampă simplă sau Lampă după poză? Sau spuneți ce vă doriți exact.")
        return

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

        # avem nume + telefon => rezumat + handoff
        produs_label = "Lampă simplă" if slots.get("produs") == "lamp_simple" else "Lampă după poză"
        price_label  = PRICE_SIMPLE if slots.get("produs") == "lamp_simple" else PRICE_PHOTO
        summary = f"Comanda: {produs_label} — {price_label} lei.\nNume: {slots['nume']}\nTelefon: {slots['telefon']}\nMulțumim!"
        handoff = "Predau conversația colegului meu. Veți fi contactat în scurt timp pentru confirmare și livrare. ✅"
        _send_many(uid, [summary, handoff])

        s["state"] = "handoff"
        s["human"] = True   # blocăm auto-răspunsul pentru acest user
        return

    if state == "handoff":
        # nu răspundem automat; lăsăm omul să preia
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
        return True  # în dev nu verificăm semnătura
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

    # Instagram Messaging: entry[].messaging[] ; user id în sender.id ; text în message.text
    for entry in data.get("entry", []):
        for item in entry.get("messaging", []):
            sender_id = item.get("sender", {}).get("id")
            msg = item.get("message", {}) or {}
            text_in = (msg.get("text") or "").strip()
            if not sender_id or not text_in:
                continue
            handle(sender_id, text_in)

    return "EVENT_RECEIVED", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
