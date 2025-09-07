import os
import json
import time
import hmac
import hashlib
import logging
import re
import gspread
from google.oauth2.service_account import Credentials
from typing import Any, Dict, Iterable, Tuple
from gspread.exceptions import WorksheetNotFound 
from collections import defaultdict
from tools.deadline_planner import evaluate_deadline, format_reply_ro
from tools.urgent_handoff import detect_urgent_and_wants_phone, evaluate_urgent_handoff, format_urgent_reply_ro
from datetime import datetime
from zoneinfo import ZoneInfo
from tools.deadline_planner import parse_deadline
from ai_router import pre_greeting_guard, route_message
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

# Romanian weekday names
DOW_RO_FULL = ["luni","marți","miercuri","joi","vineri","sâmbătă","duminică"]

# explicit '10 septembrie' fallback
MONTHS_RO = {
    "ianuarie":1,"februarie":2,"martie":3,"aprilie":4,"mai":5,"iunie":6,
    "iulie":7,"august":8,"septembrie":9,"octombrie":10,"noiembrie":11,"decembrie":12
}

MONTH_RX = re.compile(
    r"\b(\d{1,2})\s+(ianuarie|februarie|martie|aprilie|mai|iunie|iulie|august|septembrie|octombrie|noiembrie|decembrie)(?:\s+(\d{4}))?\b",
    re.IGNORECASE
)
DEADLINE_RX = re.compile(
    r"(\bazi\b|\bm[âa]ine\b|\bpoim[âa]ine\b|\b(luni|mar[țt]i|miercuri|joi|vineri|s[âa]mb[ăa]t[ăa]|duminic[ăa])\b|"
    r"\b(?:[0-3]?\d)[./-](?:[01]?\d)(?:[./-](?:\d{2}|\d{4}))?\b|\b(?:în|peste)\s+\d{1,2}\s+zile?)",
    re.IGNORECASE
)

CITY_CANON = {
    "chișinău":"Chișinău","chisinau":"Chișinău","bălți":"Bălți","balti":"Bălți",
    "cahul":"Cahul","orhei":"Orhei","glodeni":"Glodeni","comrat":"Comrat",
    "soroca":"Soroca","ungheni":"Ungheni","cimișlia":"Cimișlia","cimislia":"Cimișlia",
}
CITY_RX = re.compile(r"\b(" + "|".join(map(re.escape, CITY_CANON.keys())) + r")\b", re.IGNORECASE)

# dd.mm / dd-mm / dd/mm
DM_RX = re.compile(r"\b([0-3]?\d)[./-]([01]?\d)(?:[./-](\d{2,4}))?\b")
# cuvinte cheie (azi, mâine, etc.) – doar pentru decizie, nu pentru fallback textual
KW_RX = re.compile(r"\b(azi|m[âa]ine|poim[âa]ine|s[ăa]pt[ăa]m[âa]na viitoare|în\s+\d+\s+zile?)\b", re.IGNORECASE)

def extract_deadline_for_sheet(text: str) -> str:
    if not text:
        return ""
    # 1) parserul tău (manevrează „miercuri 10 septembrie”, „în 3 zile”, etc.)
    dt = None
    try:
        dt = parse_deadline(text)
    except Exception:
        dt = None
    if dt:
        return f"{DOW_RO_FULL[dt.weekday()]}, {dt.day:02d}.{dt.month:02d}"
    # 2) "10 septembrie"
    m = MONTH_RX.search(text)
    if m:
        d = int(m.group(1)); mo = MONTHS_RO[m.group(2).lower()]
        year = int(m.group(3)) if m.group(3) else datetime.now(ZoneInfo("Europe/Chisinau")).year
        cand = datetime(year, mo, d, tzinfo=ZoneInfo("Europe/Chisinau"))
        if cand < datetime.now(ZoneInfo("Europe/Chisinau")):
            cand = cand.replace(year=year+1)
        return f"{DOW_RO_FULL[cand.weekday()]}, {cand.day:02d}.{cand.month:02d}"
    # 3) dd.mm / dd-mm / dd/mm
    m2 = DM_RX.search(text)
    if m2:
        d = int(m2.group(1)); mo = int(m2.group(2)); yy = m2.group(3)
        year = int(yy) + 2000 if (yy and len(yy)==2) else (int(yy) if yy else datetime.now(ZoneInfo("Europe/Chisinau")).year)
        cand = datetime(year, mo, d, tzinfo=ZoneInfo("Europe/Chisinau"))
        return f"{DOW_RO_FULL[cand.weekday()]}, {cand.day:02d}.{cand.month:02d}"
    # 4) cuvinte relative – dacă există keyword, măcar marchează „azi/mâine/…”
    if KW_RX.search(text):
        return KW_RX.search(text).group(0).lower()
    # altfel nu salva nimic
    return ""

def _attachment_url(a: dict) -> str | None:
    p = a.get("payload") or {}
    return (
        p.get("url")
        or a.get("url")
        or (a.get("image_data") or {}).get("url")
        or (a.get("video_data") or {}).get("url")
        or a.get("file_url")
        or a.get("image_url")
    )

def extract_city_from_text(text: str) -> str | None:
    if not text: 
        return None
    m = CITY_RX.search(text)
    if not m: 
        return None
    return CITY_CANON.get(m.group(1).lower())


def extract_deadline_phrase(text: str) -> str | None:
    m = DEADLINE_RX.search(text or "")
    return m.group(0) if m else None

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
SHOP_CFG = SHOP  
# --- MD locations (fallback minimal; poți extinde dintr-un fișier JSON) ---
MD_CITIES_FALLBACK = {
    "chișinău","chisinau","bălți","balti","cahul","orhei","ungheni","comrat","edineț","soroca",
    "hîncești","ialoveni","cimișlia","căușeni","florești","fălești","strășeni","rezina","rîșcani",
    "sîngerei","nisporeni","telenesti","telenești","ștefan vodă","soldanesti","șoldănești","drochia",
    "glodeni","anenii noi","călărași","dondușeni","ocnița"
}
MD_RAIONS_FALLBACK = {
    "cahul","orhei","ungheni","comrat","edineț","soroca","hîncești","ialoveni","cimișlia","căușeni",
    "florești","fălești","strășeni","rezina","rîșcani","sîngerei","nisporeni","telenești","ștefan vodă",
    "șoldănești","drochia","glodeni","anenii noi","călărași","dondușeni","ocnița","taraclia","leova",
    "basarabeasca"
}
try:
    import pathlib, json as _json
    p = pathlib.Path("data/md_locations.json")
    if p.exists():
        _loc = _json.loads(p.read_text(encoding="utf-8"))
        MD_CITIES = {c.lower() for c in _loc.get("cities", [])} or MD_CITIES_FALLBACK
        MD_RAIONS = {r.lower() for r in _loc.get("raions", [])} or MD_RAIONS_FALLBACK
    else:
        MD_CITIES, MD_RAIONS = MD_CITIES_FALLBACK, MD_RAIONS_FALLBACK
except Exception:
    MD_CITIES, MD_RAIONS = MD_CITIES_FALLBACK, MD_RAIONS_FALLBACK

def _cap(s: str) -> str:
    return re.sub(r"\s+"," ", (s or "").strip()).title()

NAME_STOPWORDS = (
    {"curier","poștă","posta","oficiu","transfer","numerar","cash","plata","livrare",
     "chișinău","chisinau","bălți","balti"}
    | MD_CITIES | MD_RAIONS
)

RE_FULLNAME = re.compile(
    r"^[a-zA-Zăâîșț\-]{2,30}(?:\s+[a-zA-Zăâîșț\-]{2,30})?$",
    re.IGNORECASE
)


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

def handle_instagram_message(user_id: str, msg: dict, st: dict):
    msg_text = (
        (msg.get("text"))
        or ((msg.get("message") or {}).get("text"))
        or ""
    ).strip()

    # 1) Salut o singură dată per conversație
    handled, reply = pre_greeting_guard(st, msg_text)
    if handled:
        send_instagram_message(user_id, reply)
        return "", 200

    # 2) Continuăm flow-ul normal
    clf = route_message(
        message_text=msg_text,
        classifier_tags=CLASSIFIER_TAGS,
        use_openai=True,
        ctx=st,
        cfg=SHOP_CFG,
    )

    # ...renderer & trimitere răspuns bazat pe clf
    return "", 200


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
    "p2_started_ts": 0.0,
    "p2_step": None,                 # None | "terms" | "delivery_choice" | "collect" | "confirm_order" | "handoff"
    "slots": {},
    "prepay_proof_urls": [],
    "photo_urls": [],
    "last_prompt": None,
    "last_prompt_ts": 0.0,                                           # name, phone, city, address, delivery, payment
})

PHOTO_CONFIRM_COOLDOWN = 90   # sec between "photo fits" messages
P2_STATE_TTL           = 3600 # reset stale P2 state after 1h
RECENT_P2_WINDOW       = 600  # accept first photo if P2 chosen in last 10m

# ---------- helpers ----------

AFFIRM = {
    "da","ok","okey","sigur","confirm","confirmam","confirmăm",
    "continuam","continuăm","continua","hai","mergem","start","yes",
    "ma aranjeaza","mă aranjează","imi convine","îmi convine","e ok","este bine","perfect","super","bine"}
NEGATE = {"nu", "nu acum", "mai tarziu", "mai târziu", "later", "stop", "anuleaza", "anulează"}

def _get_gs_client():
    """Returnează clientul gspread sau None dacă nu e configurat."""
    sa_json = os.getenv("GCP_SA_JSON")
    if not sa_json:
        app.logger.warning("No GCP_SA_JSON set; skipping Google Sheets export.")
        return None
    try:
        info = json.loads(sa_json)
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        creds = Credentials.from_service_account_info(info, scopes=scopes)
        return gspread.authorize(creds)
    except Exception as e:
        app.logger.exception ("GS_CLIENT_ERROR: %s", e)
        return None

def _ensure_avans_header(ws):
    # asigură că prima linie conține coloana "avans"
    hdr = [(h or "").strip().lower() for h in ws.row_values(1)]
    if "avans" not in hdr:
        ws.update_cell(1, len(hdr) + 1, "avans")

def export_order_to_sheets(sender_id: str, st: dict) -> bool:
    client = _get_gs_client()
    if not client:
        return False
    spreadsheet_id = os.getenv("SPREADSHEET_ID")
    sheet_name = os.getenv("SHEET_NAME") or "Orders"
    if not spreadsheet_id:
        app.logger.error("No SPREADSHEET_ID set; skipping Google Sheets export.")
        return False
    try:
        sh = client.open_by_key(spreadsheet_id)
        try:
            ws = sh.worksheet(sheet_name)
        except WorksheetNotFound:
            ws = sh.add_worksheet(title=sheet_name, rows=200, cols=20)
            ws.append_row(
                ["timestamp","platform","user_id","product","price",
                 "name","phone","city","address","delivery","payment","photo_urls","prepay_proof_urls","deadline_client","avans"],
            value_input_option="USER_ENTERED"
            )
        _ensure_avans_header(ws)
        
        
        slots = st.get("slots") or {}
        photo_urls = "; ".join(st.get("photo_urls", []))
        product = "P2"
        try:
            price = next((p.get("price") for p in SHOP.get("products", []) if p.get("id") == "P2"), "")
        except Exception:
            price = ""
        prepay_urls = "; ".join(st.get("prepay_proof_urls", []))

        deadline_cell = st.get("deadline_client") or extract_deadline_for_sheet(slots.get("raw_last_message","") or "")
        advance = st.get("advance_amount") or ""
        row = [
            datetime.now(ZoneInfo("Europe/Chisinau")).strftime("%Y-%m-%d %H:%M:%S"),
            "instagram",
            sender_id,
            product,
            price,
            slots.get("name",""),
            slots.get("phone",""),
            slots.get("city",""),
            slots.get("address",""),
            slots.get("delivery",""),
            slots.get("payment",""),
            photo_urls,
            prepay_urls,
            deadline_cell,
            advance,
        ]
        app.logger.info("ORDER_EXPORTED_TO_SHEETS deadline_client=%r", deadline_cell)
        ws.append_row(row, value_input_option="USER_ENTERED")
        app.logger.info("ORDER_EXPORTED_TO_SHEETS %s", row)
        return True
    except Exception as e:
        app.logger.exception("SHEETS_EXPORT_FAILED: %s", e)
        return False

def is_affirm(txt: str) -> bool:
    t = (txt or "").strip().lower()
    return any(w in t for w in AFFIRM)


def is_negate(txt: str) -> bool:
    t = (txt or "").strip().lower()
    return any(w in t for w in NEGATE)

# === helpers pentru checkout (vizibile peste tot) ===
def _norm(s):
    return (s or "").strip().lower()

def _city_kind(city: str) -> str:
    c = _norm(city)
    if c in {"chișinău", "chisinau"}: return "chisinau"
    if c in {"bălți", "balti"}: return "balti"
    return "other"

def _set_slot(st, key, value):
    st.setdefault("slots", {})
    if value is not None and value != "":
        st["slots"][key] = value

def _lock_payment_if_needed(st: dict):
    slots = st.setdefault("slots", {})
    city = slots.get("city")
    method = _norm(slots.get("delivery_method") or slots.get("delivery"))
    if city and method and _city_kind(city) == "other" and method == "curier":
        # Curier + localitate „other” => DOAR transfer
        slots["payment"] = "transfer"     # <- IMPORTANT: setăm payment
        slots["payment_lock"] = True
    else:
        slots.pop("payment_lock", None)

def _build_collect_prompt(st: dict) -> str:
    """Returnează mesajul MINIM de colectare.
       Pentru 'oficiu' în Chișinău -> doar Nume + Telefon + notă informativă în ACELAȘI mesaj."""
    slots = st.get("slots") or {}
    dm = (slots.get("delivery_method") or slots.get("delivery") or "").strip().lower()
    city_norm = (slots.get("city") or "").strip().lower()
    office_pickup = (dm == "oficiu" and city_norm in {"chișinău", "chisinau"})

    # --- OFICIU (Chișinău): doar nume + telefon + notă ---
    if office_pickup:
        ask = []
        if not (slots.get("name")):
            ask.append("• Nume complet")
        if not (slots.get("phone")):
            ask.append("• Telefon")
        note = get_global_template("office_pickup_info") or \
               "Notă: preluare din oficiu (Chișinău). Vă rugăm să apelați în prealabil înainte de a veni, pentru confirmare și disponibilitate."

        if not ask:
            return note
        return "Pentru preluarea din oficiu mai avem nevoie de:\n" + "\n".join(ask) + "\n\n" + note

    # --- Flux standard (curier/poștă) ---
    ask = []
    if not (slots.get("client_name") or slots.get("name")):
        ask.append("• Nume complet")
    if not (slots.get("client_phone") or slots.get("phone")):
        ask.append("• Telefon")
    if not slots.get("address"):
        ask.append("• Adresa exactă")
    if not slots.get("city"):
        ask.append("• Localitatea")
    if not dm:
        ask.append("• Metoda de livrare (curier/poștă/oficiu)")
    if not slots.get("payment") and not slots.get("payment_lock"):
        ask.append("• Metoda de plată (numerar/transfer)")

    if not ask:
        return "Toate datele sunt complete. Confirmăm?"
    return "Pentru expedierea comenzii mai avem nevoie de:\n" + "\n".join(ask)


# --- locality parser (cities/raions) ---

def _norm_ro(s: str) -> str:
    """lower + normalize diacritics (â→î, ş→ș, ţ→ț) and collapse spaces"""
    if not s:
        return ""
    t = s.lower().translate(str.maketrans({"ş": "ș", "ţ": "ț", "â": "î"}))
    return " ".join(t.split())


def parse_locality(text: str) -> tuple[str | None, str | None]:
    """
    Returnează (city, raion) dacă găsește ceva util în text.
    Acceptă:  Chișinău / Bălți,  'orașul X', 'satul X', 'comuna X',
              nume de oraș din listă, sau doar un raion din listă.
    """
    low = _norm_ro(text)

    if "chișinău" in low or "chisinau" in low:
        return "Chișinău", None
    if "bălți" in low or "balti" in low:
        return "Bălți", None
    # "orașul/satul/comuna X"
    m = re.search(r"(orașul|orasul|satul|comuna)\s+([a-zăâîșț\- ]{2,40})", low)
    if m:
        loc = _cap(m.group(2))
        return loc, None
    
    m = re.search(r"(.+?)[,\-]\s*(raionul|r\.|raion)\s+(.+)$", low)
    if m:
        loc = _cap(m.group(1).strip())
        raion = _cap(m.group(3).strip())
        return (loc or None), (raion or None)
    extra_syn = {"sângerei", "sîngerei", "singerei"}

    for c in (MD_CITIES | extra_syn):
        if c in low:
            return _cap(c), None

    for r in (MD_RAIONS | extra_syn):
        if r in low:
            return None, _cap(r)

    return None, None    
           

RE_NAME_WORD = re.compile(r"^[a-zA-Zăâîșț\-]{3,40}$", re.IGNORECASE)
RE_NAME_FROM_SENTENCE = re.compile(
    r"(?:mă|ma)\s+numesc\s+([a-zA-Zăâîșț\-\s]{3,40})|"
    r"numele\s+meu\s+este\s+([a-zA-Zăâîșț\-\s]{3,40})|"
    r"sunt\s+([a-zA-Zăâîșț\-\s]{3,40})",
    re.IGNORECASE
)

def _extract_phone(raw: str) -> str | None:
    digits = re.sub(r"\D", "", raw or "")
    if not digits:
        return None
    if digits.startswith("373") and 10 <= len(digits) <= 12:
        return "+373" + digits[3:]
    if digits.startswith("0") and 9 <= len(digits) <= 10:
        return digits
    if 8 <= len(digits) <= 9:
        return digits
    return None

def _fill_one_line(slots: dict, text: str):
    text = (text or "").strip()
    low  = text.lower()

    # phone
    if not slots.get("phone"):
        ph = _extract_phone(text)
        if ph:
            slots["phone"] = ph
            

    # name (accept 1-2 cuvinte; excludem cuvinte cheie de livrare/orase/raioane)
    if not slots.get("name") and text and not any(ch.isdigit() for ch in text):
        m = RE_NAME_FROM_SENTENCE.search(text)
        if m:
            cand = next(g for g in m.groups() if g)
            cand = _cap(cand)
            if cand and cand.lower() not in NAME_STOPWORDS:
                slots["name"] = cand
        elif RE_FULLNAME.match(text):
            toks = {t for t in low.split() if t}
            if not (toks & NAME_STOPWORDS):
                slots["name"] = _cap(text)


    # delivery
    if not slots.get("delivery"):
        if "curier" in low: slots["delivery"] = "curier"
        elif "poșt" in low or "post" in low: slots["delivery"] = "poștă"
        elif "oficiu" in low or "pick" in low or "preluare" in low: slots["delivery"] = "oficiu"

    # payment
    if not slots.get("payment"):
        if any(k in low for k in ["numerar", "cash", "ramburs", "la livrare"]):
            slots["payment"] = "numerar"
        elif any(k in low for k in ["transfer", "card", "bancar", "iban", "preplată", "preplata", "prepay"]):
            slots["payment"] = "transfer"

    # city
    if (not slots.get("city")) or (not slots.get("raion")):
        c, r = parse_locality(text)
        if c and not slots.get("city"):
            slots["city"] = c
        if r and not slots.get("raion"):
            slots["raion"] = r

    # address: detect on a per-line basis (ignore lines that look like phone)
    if not slots.get("address"):
        has_addr_tokens = any(k in low for k in ("str", "str.", "bd", "bd.", "bloc", "ap", "ap.", "nr", "scara", "sc."))
        has_digits = any(ch.isdigit() for ch in text)
        if (has_addr_tokens or has_digits) and not _extract_phone(text):
            slots["address"] = text

def fill_slots_from_text(slots: dict, txt: str):
    """
    NEW: splits multi-line / bulleted messages, filling slots line-by-line.
    Prevents re-asking for name/address when user sends all details in one bubble.
    """
    if not txt:
        return
    parts = [p.strip() for p in re.split(r"[\n•;,|]+", txt) if p.strip()]
    if len(parts) > 1:
        for p in parts:
            _fill_one_line(slots, p)
    else:
        _fill_one_line(slots, txt.strip())

SLOT_ORDER = ["name", "phone", "city", "address", "delivery", "payment"]

def next_missing(slots: dict):
    dm = (slots.get("delivery_method") or slots.get("delivery") or "").strip().lower()
    city_norm = (slots.get("city") or "").strip().lower()
    office_pickup = (dm == "oficiu" and city_norm in {"chișinău", "chisinau"})

    # pentru oficiu: cerem DOAR nume și telefon
    for k in ("name", "phone"):
        if not slots.get(k):
            return k

    if office_pickup:
        return None  # nu mai cerem adresă / plată / etc.

    # restul fluxului standard
    if not (slots.get("city") or slots.get("raion")):
        return "locality"
    for k in ("address", "delivery", "payment"):
        if k == "payment" and slots.get("payment_lock"):
            continue
        if not slots.get(k):
            return k
    return None




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


GREET_TOKENS = ("bună ziua", "buna ziua", "bună", "buna", "salut", "hello", "hi")

def _should_prefix_greeting(low_text: str) -> bool:
    if not low_text:
        return False
    if any(tok in low_text for tok in GREET_TOKENS):
        return True
    # „mesaj lung” = probabil prima solicitare completă -> vrem salut politicos în răspuns
    return len(low_text) >= 60

def _prefix_greeting_if_needed(sender_id: str, low_text: str, body: str) -> str:
    """Prefixează 'Bună ziua!' o singură dată / 1h, la primul răspuns relevant."""
    if not body:
        return body
    if _should_greet(sender_id, low_text) and _should_prefix_greeting(low_text):
        GREETED_AT[sender_id] = time.time()
        return "Bună ziua!\n\n" + body
    return body


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
                if isinstance(msg.get("attachments"), dict) and isinstance(msg["attachments"].get("data"), list):
                    msg = dict(msg)  # shallow copy
                msg["attachments"] = msg["attachments"]["data"]
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
            if len(attachments) == 1 and isinstance(attachments[0].get("data"), list):
                attachments = [a for a in attachments[0]["data"] if isinstance(a, dict)]
            app.logger.info("ATTACHMENTS: path=%s count=%d", path, len(attachments))
            for i, a in enumerate(attachments[:3]):  # log primele 3 pt. debug
                try:
                    app.logger.info("ATTACHMENT_OBJ[%d]: %s", i, json.dumps(a)[:600])
                except Exception:
                    pass

            if attachments:
                # --- PROOF după transfer: finalizează comanda și handoff ---
                st = USER_STATE[sender_id]
                if st.get("p2_step") == "awaiting_prepay_proof":
                    st.setdefault("prepay_proof_urls", [])
                    for a in attachments:
                        u = _attachment_url(a)
                        if not u and (a.get("payload") or {}).get("attachment_id"):
                            u = f"attachment:{(a.get('payload') or {}).get('attachment_id')}"
                        if u and u not in st["prepay_proof_urls"]:
                            st["prepay_proof_urls"].append(u) 
                    st.setdefault("advance_amount", 200)
                    export_order_to_sheets(sender_id, st)
                    send_instagram_message(
                        sender_id,
                        "Mulțumim! Am primit dovada plății. Un coleg vă contactează în scurt timp pentru a confirma definitiv comanda. 💜"
                        )
                    st["p2_step"] = "handoff"
                    continue

                get_ctx(sender_id)["flow"] = "photo"

                # --- accept photos ONLY if we're already in the P2 flow ---
                sess = get_session(sender_id)

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
                    st.get("awaiting_photo") or
                    st.get("awaiting_confirmation") or
                    recent_p2 or
                    (sess.get("stage") == "awaiting_photo")
                )

                if not in_p2_photo_flow:
                    app.logger.info("ATTACHMENT_IGNORED: not in P2 flow")
                    continue  # ignore random photos outside P2; no messages sent

                

                get_ctx(sender_id)["flow"] = "photo"

                st.setdefault("photo_urls", [])
                for a in attachments:
                    u = _attachment_url(a)
                    if u and u not in st["photo_urls"]:
                        st["photo_urls"].append(u)
 

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

   
            # ===== Confirmation after first photo =====
            st = USER_STATE[sender_id]
            if st.get("awaiting_confirmation") and any(
               w in low for w in ("da", "confirm", "confirmam", "confirmăm", "ok", "hai", "sigur", "yes", "continuam", "continuăm", "continua")
            ):
                send_instagram_message(sender_id, (get_global_template("terms_delivery_intro") or "Pentru realizare și livrare am nevoie de localitate și termenul dorit.")[:900])
                st["awaiting_confirmation"] = False
                st["p2_step"] = "terms"
                get_ctx(sender_id)["flow"] = "order"
                continue

            # ===== P2 ORDER FLOW 
            st = USER_STATE[sender_id]
            ctx = get_ctx(sender_id)

            if text_in:
                dc = extract_deadline_for_sheet(text_in)
                if dc:  # salvează DOAR dacă am detectat o dată/expresie
                    st["deadline_client"] = dc

                city = extract_city_from_text(text_in)
                if city:
                    st.setdefault("slots", {})["city"] = city
            
                st.setdefault("slots", {})["raw_last_message"] = text_in

            # === URGENT HANDOFF INTERCEPTOR (telefon) ===
            if text_in and detect_urgent_and_wants_phone(text_in):
    # evităm dublarea mesajului dacă deja am escaladat în acest thread
                if not st.get("handoff_urgent_done"):
                    decision = evaluate_urgent_handoff(text_in)

        # dacă userul a scris un număr, îl salvăm pentru operator
                    if decision.phone_found:
                        (st.setdefault("lead", {}))["phone"] = decision.phone_found

                    reply = format_urgent_reply_ro(decision)
                    send_instagram_message(sender_id, reply[:900])

                    st["handoff_urgent_done"] = True
                    continue  # nu mai coborâm în flow-ul P2 pe acest mesaj

       
            # --- DEADLINE EVALUATOR (L-V, 09–18) ---
            if text_in:
                t_lower = (text_in or "").lower()

                deadline_keywords = {
                    "azi", "mâine", "maine", "poimâine", "poimaine",
                    "luni", "marți", "marti", "miercuri", "joi", "vineri",
                    "sâmbătă", "sambata", "duminică", "duminica",
                    "săptămâna viitoare", "saptamana viitoare"
                }

                triggers_deadline = (
                    any(re.search(rf"\b{re.escape(kw)}\b", t_lower) for kw in deadline_keywords)
                    or re.search(r"\b\d{1,2}[./-]\d{1,2}\b", t_lower)
                    or re.search(r"\b(?:în|in|peste)\s+\d{1,2}\s+zile?\b", t_lower) 
                    or MONTH_RX.search(text_in or "") 
                )

                if any(kw in t_lower for kw in deadline_keywords) or re.search(r"\b\d{1,2}[./-]\d{1,2}", t_lower):
                    product_key = "lamp_dupa_poză"   # mapare simplă; păstrează dacă așa ai SLA

                    # 1) Extrage localitatea din ACELAȘI mesaj
                    city_in_msg, raion_in_msg = parse_locality(text_in or "")

                    # fallback pe regex/dicționar (ex. „orașul Cahul”)
                    try:
                        if not city_in_msg:
                            m_city = CITY_RX.search(text_in or "")
                            if m_city:
                                city_key = (m_city.group(1) or "").lower()
                                city_in_msg = CITY_CANON.get(city_key, city_key.title())
                    except Exception:
                        # nu blocăm fluxul dacă regex/dicționarul dau eroare
                        pass

                    # 2) IMPORTANT: de aici în jos este ÎN AFARA blocului except
                    delivery_city_hint = (
                        city_in_msg
                        or (st.get("slots") or {}).get("city")
                        or (ctx.get("delivery_city") if isinstance(ctx, dict) else None)
                    )
                    rush_requested = any(w in t_lower for w in ["urgent","urgență","urgentă","rapid"])

                    res = evaluate_deadline(
                        user_text=text_in,
                        product_key=product_key,
                        delivery_city_hint=delivery_city_hint,
                        rush_requested=rush_requested,
                    )

                    # 3) Cazul fericit: ne încadrăm + avem localitate -> răspuns scurt + opțiuni livrare
                    if getattr(res, "ok", False) and delivery_city_hint:
                        st.setdefault("slots", {})
                        if city_in_msg:
                            st["slots"]["city"] = city_in_msg
                        if raion_in_msg:
                            st["slots"]["raion"] = raion_in_msg

                        send_instagram_message(sender_id, "Da, ne încadrăm în termen.")

                        key = (delivery_city_hint or "").lower()
                        if key in {"chișinău", "chisinau"}:
                            send_instagram_message(sender_id, get_global_template("delivery_chisinau")[:900])
                        elif key in {"bălți", "balti"}:
                            send_instagram_message(sender_id, get_global_template("delivery_balti")[:900])
                        else:
                            send_instagram_message(sender_id, get_global_template("delivery_other")[:900])

                        st["p2_step"] = "delivery_choice"
                        continue

                    # 4) Altfel: formatăm răspunsul detaliat existent
                    reply_text = format_reply_ro(res)
                    send_instagram_message(sender_id, reply_text[:900])
                    continue

            # --- GREETING FIRST (short, greeting-only messages) ---
            if text_in:
                _low = (text_in or "").strip().lower()
                # saluturi scurte, fără alt conținut
                if re.fullmatch(r'(bun[ăa]\s+ziua|bun[ăa]|salut|hello|hi)[\s\.\!\?]*', _low):
                    send_instagram_message(sender_id, "Salut! Cu ce vă pot ajuta astăzi?")
                    continue


            # 3.1 Pas: terms -> trimite opțiuni de livrare după ce aflăm localitatea
            if st.get("p2_step") == "terms":
                city, raion = parse_locality(text_in or "")
                if city or raion:
                    st.setdefault("slots", {})
                    if city:  st["slots"]["city"]  = city
                    if raion: st["slots"]["raion"] = raion

                    if city and city.lower() in {"chișinău","chisinau"}:
                        send_instagram_message(sender_id, get_global_template("delivery_chisinau")[:900])
                    elif city and city.lower() in {"bălți","balti"}:
                        send_instagram_message(sender_id, get_global_template("delivery_balti")[:900])
                    else:
                        send_instagram_message(sender_id, get_global_template("delivery_other")[:900])

                    st["p2_step"] = "delivery_choice"
                    continue
                send_instagram_message(
                    sender_id,
                    "Spuneți vă rog localitatea (ex: «orașul» sau «Numele satului și raionului»)."
                )
                continue

            
            if st.get("p2_step") == "delivery_choice":
                t = (text_in or "").lower()

                def _start_collect(choice: str):
                    _set_slot(st, "delivery_method", choice)
                    _set_slot(st, "delivery", choice)  # compatibilitate cu codul vechi
                    _lock_payment_if_needed(st)        # curier + other => transfer
                    st["p2_step"] = "collect"          # sau "order_collect", după cum ai
                    send_instagram_message(sender_id, _build_collect_prompt(st)[:900])

                accept_words = {"mă aranjează","ok","bine","merge","sunt de acord","da","de acord"}

               
                if "oficiu" in t or "pick" in t or "preluare" in t:
                    _set_slot(st, "delivery_method", "oficiu")
                    _set_slot(st, "delivery", "oficiu")
                    st["p2_step"] = "collect"
                    get_ctx(sender_id)["flow"] = "order"   # <— adaugă linia asta
                    send_instagram_message(sender_id, _build_collect_prompt(st)[:900])
                    continue
                if "curier" in t:
                    _start_collect("curier"); continue
                if "poșt" in t or "post" in t:
                    _start_collect("poștă"); continue

                # 2) fallback – tratăm “ok/da/bine” ca „curier”
                if any(w in t for w in accept_words):
                    _start_collect("curier"); continue
                

            
            # 3.3 Pas: collect (slot-filling)
            if st.get("p2_step") == "collect":
                slots = st.get("slots") or {}
                fill_slots_from_text(slots, text_in or "")
                st["slots"] = slots

                # IMPORTANT: aplică regula după ce s-au putut completa city/delivery
                _lock_payment_if_needed(st)

                missing = next_missing(slots)
                if missing:
                    send_instagram_message(sender_id, _build_collect_prompt(st)[:900])
                    continue

                office_pickup = ((slots.get("delivery_method") or slots.get("delivery")) == "oficiu" and
                 (slots.get("city") or "").lower() in {"chișinău","chisinau"})
                

                office_pickup = ((slots.get("delivery_method") or slots.get("delivery")) == "oficiu" and
                                (slots.get("city") or "").lower() in {"chișinău","chisinau"})

                if office_pickup:
                    recap = (
                        f"Recapitulare comandă:\n"
                        f"• Nume: {slots['name']}\n"
                        f"• Telefon: {slots['phone']}\n"
                        f"• Preluare: oficiu (Chișinău)\n\n"
                        f"Totul este corect?"
                    )
                else:
                    locality = slots.get("city") or ""
                    if slots.get("raion"):
                        locality = (locality + (", raion " if locality else "Raion ") + slots["raion"]).strip()
                    recap = (
                        f"Recapitulare comandă:\n"
                        f"• Nume: {slots['name']}\n"
                        f"• Telefon: {slots['phone']}\n"
                        f"• Localitate: {locality}\n"
                        f"• Adresă: {slots['address']}\n"
                        f"• Livrare: {slots['delivery']}\n"
                        f"• Plată: {slots['payment']}\n\n"
                        f"Totul este corect?"
                    )

                send_instagram_message(sender_id, recap[:900])
                st["p2_step"] = "confirm_order"
                continue

            # 3.4 Pas: confirm_order (confirmare comandă)

            if st.get("p2_step") == "confirm_order":
                if is_affirm(text_in):
                    if (st.get("slots") or {}).get("payment_lock"):
                        pay_msg = (
                            "Perfect! Pentru confirmarea comenzii este necesar un avans de 200 lei.\n\n"
                            "Plata se face prin transfer pe card (integral sau avans + restul prin transfer).\n\n"
                            "5397 0200 6122 9082 cont MAIB\n"
                            "062176586 MIA plăți instant\n\n"
                            "După transfer, expediați o poză a chitanței, pentru confirmare."
                        )
                    else:
                        pay_msg = (
                            "Perfect! Pentru confirmarea comenzii, întrucât comanda este personalizată, este necesar un avans în sumă de 200 lei.\n\n"
                            "Restul sumei se poate achita la livrare.\n\n"
                            "Avansul se poate plăti prin transfer pe card.\n\n"
                            "5397 0200 6122 9082 cont MAIB \n\n"
                            "062176586 MIA plăți instant \n\n"
                            "După transfer, expediați o poză a chitanței, pentru confirmarea transferului."
                        )
                    send_instagram_message(sender_id, pay_msg[:900])
                    st["advance_amount"] = 200
                    st["p2_step"] = "awaiting_prepay_proof"
                    continue

                if is_negate(text_in):
                    send_instagram_message(sender_id, "Spuneți-mi ce ar trebui corectat și ajustăm imediat.")
                    st["p2_step"] = "collect"
                    continue

                send_instagram_message(sender_id, "Confirmăm comanda? (da/nu)")
                continue


            if st.get("p2_step") == "handoff":
                ok = export_order_to_sheets(sender_id, st)
                if not ok:
                    # fallback local CSV ca să nu pierdem comanda
                    try:
                        import csv, time as _t
                        fn = "/mnt/data/orders.csv"
                        slots = st.get("slots") or {}
                        row = [
                             time.strftime("%Y-%m-%d %H:%M:%S"),
                             "instagram",
                             sender_id,
                             "P2",
                            next((p.get("price") for p in SHOP.get("products", []) if p.get("id") == "P2"), ""),
                            slots.get("name",""), slots.get("phone",""), slots.get("city",""),
                            slots.get("address",""), slots.get("delivery",""), slots.get("payment",""),
                            "; ".join(st.get("photo_urls", [])),
                            "; ".join(st.get("prepay_proof_urls", [])),
                            st.get("advance_amount",""),
                        ]
                        with open(fn, "a", newline="", encoding="utf-8") as f:
                            csv.writer(f).writerow(row)
                        app.logger.info("ORDER_EXPORTED_TO_CSV %s", row)
                    except Exception as e:
                        app.logger.exception("EXPORT_CSV_FAILED: %s", e)
                send_instagram_message(sender_id, "Gata! Un coleg preia comanda și vă contactează cât de curând. Mulțumim! 💜")
                st["p2_step"] = None
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

                st = USER_STATE[sender_id]
                in_structured_p2 = (st.get("p2_step") in {"terms","delivery_choice","collect","confirm_order","awaiting_prepay_proof"}) or (get_ctx(sender_id).get("flow") == "order")
                
                sug = result.get("suggested_reply")
                if sug and not in_structured_p2:
                    send_instagram_message(sender_id, sug[:900])
                    continue

                if (result.get("delivery_intent") or result.get("intent") == "ask_delivery") and not in_structured_p2:
                    delivery_short = (
                        get_global_template("delivery_short")
                        or "Putem livra prin curier în ~1 zi lucrătoare; livrarea costă ~65 lei. Spuneți-ne localitatea ca să confirmăm."
                    )
                    delivery_short = _prefix_greeting_if_needed(sender_id, low, delivery_short)
                    send_instagram_message(sender_id, delivery_short[:900])
                    continue
                

                

                # --- NEW: dacă NLU spune P2 (lampă după poză) → intrăm în flow foto
                if (result.get("product_id") == "P2"
                    and result.get("intent") in {"send_photo","want_custom","keyword_match"}
                    and not in_structured_p2):
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


                # 2) „Cum plasez comanda” ⇒ intrăm în fluxul ORDER
                if (result.get("intent") == "ask_howto_order") and not in_structured_p2:
                    ctx["flow"] = "order"
                    order_prompt = (
                        get_global_template("order_start")
                        or "Putem prelua comanda aici în chat. Vă rugăm: • Nume complet • Telefon • Localitate și adresă • Metoda de livrare (curier/poștă/oficiu) • Metoda de plată (numerar/transfer)."
                    )
                    order_prompt = _prefix_greeting_if_needed(sender_id, low, order_prompt)
                    send_instagram_message(sender_id, order_prompt[:900])
                    continue


                # 3) Livrare: răspuns scurt, fără ofertă implicită
                if result.get("delivery_intent") or result.get("intent") == "ask_delivery":
                    delivery_short = (
                        get_global_template("delivery_short")
                        or "Putem livra prin curier în ~1 zi lucrătoare; livrarea costă ~65 lei. Spuneți-ne localitatea ca să confirmăm."
                    )
                    delivery_short = _prefix_greeting_if_needed(sender_id, low, delivery_short)
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
                    reply_text = _prefix_greeting_if_needed(sender_id, low, reply_text)
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
