import json, re, unicodedata
from typing import Optional, Dict, List, Any, Tuple
from openai import OpenAI
from tools.deadline_planner import evaluate_deadline, format_reply_ro
from datetime import datetime, timedelta
try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None
client = OpenAI()  # uses OPENAI_API_KEY from env

# --- price / offer control ----------------------------------------------------

GREETINGS = {
    "buna ziua", "bună ziua", "buna", "bună", "salut", "salutare", "hello", "hi"
}

def norm(text: str) -> str:
    return (text or "").strip()

def norm_low(text: str) -> str:
    return (text or "").strip().lower()

def looks_like_name(text: str) -> bool:
    t = norm(text)
    tl = norm_low(text)
    if not t or any(ch.isdigit() for ch in t):
        return False
    # respinge saluturi simple
    if tl in GREETINGS:
        return False
    # respinge texte foarte scurte / foarte lungi
    if len(t) < 2 or len(t) > 50:
        return False
    # doar litere, spațiu, -, '
    import re
    return bool(re.fullmatch(r"[A-Za-zĂÂÎȘȚăâîșț\-' ]{2,50}", t))

def extract_name_candidate(text: str) -> str | None:
    """
    Acceptă:
      - 'Igor'
      - 'Numele: Igor'
      - 'Numele este Igor'
      - 'Nume Igor'
    Respinge saluturi ('Bună ziua') sau texte cu cifre.
    """
    t = norm(text)
    tl = norm_low(text)
    # elimină prefixele uzuale
    for pref in ["numele este", "numele e", "numele:", "nume:", "nume "]:
        if tl.startswith(pref):
            t = t[len(pref):].strip()
            break
    if looks_like_name(t):
        return t
    return None

RO_TZ = ZoneInfo("Europe/Chisinau") if ZoneInfo else None

_GREET_PAT = re.compile(
    r"^\s*(salut(?:are)?|bun[ăa]\s+ziua|bun[ăa]\s+dimineața|bun[ăa]\s+seara|bun[ăa]|hei|hey|hi|hello)\b",
    flags=re.IGNORECASE | re.UNICODE,
)

def pre_greeting_guard(
    st: Dict[str, Any] | None,
    msg_text: str | None,
    now: datetime | None = None,
    ttl_hours: int = 6,
) -> Tuple[bool, str | None]:
    """
    Updatează starea (TTL, greeted) și decide dacă răspundem DOAR cu salut.
    Returnează (handled, reply_text).
    """
    st = st or {}
    now = now or _now_ro()

    last = st.get("last_seen_ts")
    if isinstance(last, (int, float)):
        last_dt = datetime.fromtimestamp(last, tz=RO_TZ) if RO_TZ else datetime.utcfromtimestamp(last)
        if now - last_dt > timedelta(hours=ttl_hours):
            st["greeted"] = False

    text_in = (msg_text or "").strip()
    has_greet, greet_only = detect_greeting(text_in)
    if has_greet:
        st["user_greeted"] = True 

    st["last_seen_ts"] = now.timestamp()

    if greet_only and not st.get("has_replied_greet"):
        st["has_replied_greet"] = True
        return True, "Salut! Cu ce te pot ajuta astăzi?"

    return False, None

def _now_ro():
    if RO_TZ:
        return datetime.now(RO_TZ)
    return datetime.utcnow()

def detect_greeting(user_text: str) -> tuple[bool, bool]:
    """
    Returnează (has_greeting, greeting_only).
    greeting_only = True dacă mesajul e practic doar salut (cu puțină punctuație/emoji).
    """
    if not user_text:
        return (False, False)
    txt = user_text.strip()
    m = _GREET_PAT.match(txt)
    if not m:
        return (False, False)
    # Eliminăm salutul inițial + spații/punctuație ușoară
    rest = re.sub(r"^\s*\W+|\W+\s*$", "", txt[m.end():]).strip()
    # Considerăm „doar salut” dacă nu mai rămâne conținut semnificativ
    greeting_only = (len(rest) == 0 or len(rest.split()) <= 2)
    return (True, greeting_only)


def time_based_greeting():
    h = _now_ro().hour
    if 5 <= h < 12: return "Bună dimineața"
    if 12 <= h < 18: return "Bună ziua"
    return "Bună seara"

DISABLE_INITIAL_OFFER = False 

PRICE_TRIGGERS = {
    "pret", "preț", "informatii", "informații", "detalii",
    "modele", "lampa", "lampă", "lampile", "după poză", "poza"
}

def in_active_flow(ctx: dict) -> bool:
    # adevărat dacă strângi date pentru comandă sau ești în photo-flow
    return ctx.get("flow") in {"order", "photo"}

def handle_greeting(ctx: dict) -> str:
    # greeting curat, fără ofertă
    return "Salut! Cu ce vă pot ajuta astăzi?"

def maybe_reply_with_prices(user_text: str, ctx: dict, cfg: dict) -> Optional[str]:
    # complet dezactivat ca fallback implicit
    if DISABLE_INITIAL_OFFER:
        return None
    if in_active_flow(ctx):
        return None

    lt = user_text.lower()
    if any(t in lt for t in PRICE_TRIGGERS):
        tmpl = cfg["global_templates"]["initial_multiline"]
        p1 = cfg["products"][0]["price"]  # 650
        p2 = cfg["products"][1]["price"]  # 780
        return tmpl.format(p1=p1, p2=p2)
    return None


# --- utils -------------------------------------------------------------------

def _norm(s: str) -> str:
    """
    Normalizează textul pentru matching robust:
    - strip + lower
    - elimină diacritice (NFKD)
    - compactează whitespace
    """
    s = (s or "").strip().lower()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return " ".join(s.split())

ORDER_PATTERNS = [
    # întrebări standard despre plasarea comenzii
    "cum pot plasa comanda", "cum se plaseaza comanda", "cum plasez comanda",
    "ce este nevoie pentru plasarea comenzii", "ce mai este nevoie pentru comanda",
    "care sunt pasii pentru comanda", "how do i place the order", "place order"
]

DELIVERY_TRIGGERS = [
    "livrare", "curier", "posta", "metode de livrare", "expediere",
    "chisinau", "balti", "comrat", "orhei", "cahul", "basarabeasca", "edinet", "briceni", "ocnita", "vulcanesti", "falesti", "ungheni", "nisporeni", "drochia", "hancesti", "criuleni", "taraclia", "donduseni"
]


CITY_ALIASES = {
    # cheia = forma canonică (cu diacritice), valorile = variante (fără/ cu diacritice)
    "chișinău": ["chisinau", "chișinău"],
    "bălți":    ["balti", "bălți"],
    # poți adăuga ușor: "comrat": ["comrat"]
}

def _extract_city(t_norm: str) -> Optional[str]:
    """
    Întoarce numele canonic al orașului (cu diacritice) dacă detectează unul în textul NORMALIZAT.
    """
    for canonical, variants in CITY_ALIASES.items():
        for v in variants:
            if re.search(rf"\b{re.escape(v)}\b", t_norm):
                # returnăm cu diacritice frumoase
                if canonical == "chișinău":
                    return "Chișinău"
                if canonical == "bălți":
                    return "Bălți"
                return canonical.title()
    return None


# --- tool JSON schema (kept simple; OpenAI uses it to structure output) ---
ROUTER_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "product_id": {"type": "string", "enum": ["P1","P2","P3","UNKNOWN"]},
        "intent": {"type": "string"},
        "language": {"type": "string", "enum": ["ro","ru","other"]},
        "neon_redirect": {"type": "boolean"},
        "confidence": {"type": "number"},
        "slots": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "quantity": {"type": "integer"},
                "city": {"type": "string"},
                "deadline_date": {"type": "string"},
                "phone": {"type": "string"},
                "name": {"type": "string"}
            }
        }
    },
    "required": ["product_id","intent","language","neon_redirect","confidence","slots"]
}

SYSTEM = (
    "Ești un router NLU pentru magazinul de lămpi.\n"
    "ÎNTOARCE STRICT arguments JSON pentru funcția route_message (fără text liber).\n"
    "Produse: P1=Lampă simplă, P2=Lampă după poză, P3=Neon.\n"
    "- Dacă userul cere neon → product_id=P3 și neon_redirect=true.\n"
    "- Dacă cere lampă după poză → product_id=P2, intent='send_photo' sau 'want_custom'.\n"
    "- Dacă cere preț/catalog → intent='ask_price' sau 'ask_catalog'.\n"
    "- Livrare/metode/curier/poștă/orase → intent='ask_delivery' și pune slots.city dacă este menționat.\n"
    "- \"în cât timp\"/\"termen\" → intent='ask_eta'.\n"
    "- \"cum pot plasa comanda\"/\"ce este nevoie pentru comanda\" → intent='ask_howto_order'.\n"
    "Returnează și language (ro/ru/other) + confidence [0..1]."
)

def classify_with_openai(message_text: str) -> Dict[str, Any]:
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": message_text.strip()}
            ],
            tools=[{
                "type": "function",
                "function": {
                    "name": "route_message",
                    "description": "Clasifică mesajul în intenție/slots/produs.",
                    "parameters": ROUTER_SCHEMA
                }
            }],
            tool_choice={"type": "function", "function": {"name": "route_message"}}
        )
        tool_call = resp.choices[0].message.tool_calls[0]
        data = json.loads(tool_call.function.arguments or "{}")
        # sanity defaults
        data.setdefault("product_id","UNKNOWN")
        data.setdefault("intent","other")
        data.setdefault("language","other")
        data.setdefault("neon_redirect", False)
        data.setdefault("confidence", 0.0)
        data.setdefault("slots", {})
        return data
    except Exception:
        return {"product_id":"UNKNOWN","intent":"other","language":"other",
                "neon_redirect": False, "confidence": 0.0, "slots": {}}

# --- keyword fallback (fast/robust) -----------------------------------

def keyword_fallback(message_text: str, classifier_tags: Dict[str, List[str]]) -> Dict[str, Any]:
    t = _norm(message_text)

    # CUM PLASEZ COMANDA
    if any(w in t for w in [
        "cum pot plasa comanda", "cum dau comanda", "cum se plasează comanda",
        "plasa comanda", "plasez comanda", "place order", "how do i order"
    ]):
        return {"product_id":"UNKNOWN","intent":"ask_howto_order","language":"ro",
        "neon_redirect":False,"confidence":0.7,"slots":{}}

    # PREȚ / COST
    if any(w in t for w in [
        "preț","pret","prețul","pretul","prețuri","preturi",
        "cât costă","cat costa","cost","costul","tarif","tarife"
    ]):
        return {"product_id":"UNKNOWN","intent":"ask_price","language":"ro",
                "neon_redirect":False,"confidence":0.6,"slots":{}}

    # CATALOG / ASORTIMENT
    if any(w in t for w in [
        "asortiment","catalog","modele","ce produse aveți","ce produse aveti","ce lampi aveti"
    ]):
        return {"product_id":"UNKNOWN","intent":"ask_catalog","language":"ro",
                "neon_redirect":False,"confidence":0.6,"slots":{}}

    # LIVRARE (+ oraș opțional)
    if any(w in t for w in [
        "livrare","curier","poștă","posta","metode de livrare","expediere",
        "oficiu","preluare","ridicare",      
        "comrat","chișinău","chisinau","bălți","balti"
    ]):
        city = None
        if "chișinău" in t or "chisinau" in t: city = "Chișinău"
        elif "bălți" in t or "balti" in t:      city = "Bălți"
        return {
            "product_id":"UNKNOWN","intent":"ask_delivery","language":"ro",
            "neon_redirect":False,"confidence":0.6,
            "slots": ({"city": city} if city else {})
        }

    # TERMEN / ETA
    if any(w in t for w in ["în cât timp","in cat timp","termen","gata comanda","când e gata","cand e gata","durata"]):
        return {"product_id":"UNKNOWN","intent":"ask_eta","language":"ro",
                "neon_redirect":False,"confidence":0.6,"slots":{}}

    # TAG-uri P1/P2/P3
    for pid, tags in classifier_tags.items():
        for tag in tags:
            if re.search(rf"\b{re.escape(tag.lower())}\b", t):
                return {"product_id": pid, "intent": "keyword_match", "language": "ro",
                        "neon_redirect": (pid == "P3"), "confidence": 0.5, "slots": {}}

    # SALUT
    if any(w in t for w in ["salut","bună","buna","привет","здравствуйте"]):
        return {"product_id":"UNKNOWN","intent":"greeting","language":"ro",
                "neon_redirect":False,"confidence":0.4,"slots":{}}

    # FALLBACK
    return {"product_id":"UNKNOWN","intent":"other","language":"other",
            "neon_redirect":False,"confidence":0.0,"slots":{}}


# --- merge strategy ----------------------------------------------------

def _merge_openai_and_keywords(ai: Dict[str,Any], kw: Dict[str,Any]) -> Dict[str,Any]:
    """Prefer OpenAI, but fix/upgrade with keywords when it spotted something concrete."""
    result = dict(ai or {})
    result.setdefault("slots", {})
    # If keyword found order how-to → force that (user intention is very clear)
    if kw.get("intent") == "ask_howto_order":
        result.update(kw)
        return result
    # If keyword found delivery and city, but AI missed city → add city
    if kw.get("intent") == "ask_delivery":
        result["intent"] = "ask_delivery"
        if kw.get("slots", {}).get("city") and not result.get("slots", {}).get("city"):
            result["slots"]["city"] = kw["slots"]["city"]
        # bump confidence
        result["confidence"] = max(result.get("confidence", 0.0), kw.get("confidence", 0.0))

    text_norm = (kw.get("t_norm") or ai.get("t_norm") or "").lower()
    tags_map  = kw.get("classifier_tags") or ai.get("classifier_tags") or {}
    concrete_tags = [t.lower() for tags in tags_map.values() for t in tags]

    if result.get("product_id") in {"P1", "P2"}:
        if not any(re.search(rf"\b{re.escape(tag)}\b", text_norm) for tag in concrete_tags):
            result["product_id"] = "UNKNOWN"

    # dacă intenția e de preț/catalog/how-to și nu suntem în flow order/photo, permite oferta inițială
    ctx = (kw.get("ctx") or ai.get("ctx") or {})  # dacă ai deja ctx în altă parte, poți renunța la această linie
    if result.get("intent") in {"ask_price", "ask_catalog", "ask_howto_order"} and ctx.get("flow") not in {"order", "photo"}:
        result["suppress_initial_offer"] = False

# --- main API ----------------------------------------------------------


def route_message(
    message_text: str,
    classifier_tags: Dict[str, List[str]],
    use_openai: bool = True,
    ctx: Optional[Dict[str, Any]] = None,
    cfg: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    # === Pre-procesare & reguli ușoare ===
    t_norm = _norm(message_text)
    result_extra: Dict[str, Any] = {
        "norm_text": t_norm,
        # plasă de siguranță pentru a NU mai trimite niciodată oferta inițială
        "suppress_initial_offer": False if not (ctx and ctx.get("flow") in {"order","photo"}) else True,
    }
    low = norm_low(message_text)
    txt = norm(message_text)
    if ctx is None:  # protecție dacă vin fără context
        ctx = {}
    order = ctx.setdefault("order", {})


# === name edit intent ===
    if "numele trebuie schimbat" in low or low in {"numele", "nume"}:
        order["_await_field"] = "name"
        return {
            "action": "ask_name_again",
            "reply": "Spuneți numele corect și actualizez imediat."
        }
    
    if order.get("_await_field") == "name":
        cand = extract_name_candidate(txt)
        if cand:
            order["name"] = cand
            order.pop("_await_field", None)
            return {
            "action": "recap",
            "reply": f"Am actualizat numele la: {cand}\n\nRecapitulare actualizată:\n"
        }
        else:
            return {
            "action": "ask_name_again",
            "reply": "Nu am putut valida numele. Scrieți doar numele și prenumele (fără cifre)."
        }

    # —— Heuristic: “vreau să cumpăr o lampă” => cerere generală de preț, nu P1
    # Evităm maparea agresivă pe P1 pentru cereri generice.
    if re.search(r"\bcump[ăa]r\b", t_norm) and "lamp" in t_norm:
        result_extra["intent"] = "ask_price"
        # explicităm că nu știm încă produsul concret
        result_extra["product_id"] = "UNKNOWN"
        result_extra["confidence"] = max(result_extra.get("confidence", 0.0), 0.7)

    # --- BUY INTENT HEURISTIC: "vreau să cumpăr o lampă" => ask_price / catalog ---
    BUY_WORDS   = ("cumpăr", "cumpar", "vreau", "aș vrea", "as vrea", "doresc",
                   "am nevoie", "nevoie", "îmi trebuie", "imi trebuie", "vreau să fac rost ")
    LAMP_WORDS  = ("lampă", "lampa", "lampi", "lampă după poză", "lampa dupa poza", "lampă simplă", "lampa simpla")

    if any(w in t_norm for w in BUY_WORDS) and any(w in t_norm for w in LAMP_WORDS):
        # Marcăm explicit intenția ca "ask_price" (catalog), fără să intrăm în livrare
        result_extra["intent"] = "ask_price"
        result_extra["delivery_intent"] = False
        # dacă avem cfg cu template-uri, pregătim și un răspuns direct
        if cfg and isinstance(cfg, dict):
            try:
                P = {p["id"]: p for p in cfg.get("products", [])}
                G = cfg.get("global_templates", {})
                result_extra["suggested_reply"] = (G.get("initial_multiline") or "").format(
                    p1=P.get("P1", {}).get("price", ""),
                    p2=P.get("P2", {}).get("price", ""),
                )
            except Exception:
                pass
        # Creștem puțin încrederea, ca să cântărească mai mult decât alte reguli
        result_extra["confidence"] = max(result_extra.get("confidence", 0.0), 0.75)

    # --- SUPRESIE LIVRARE ÎN ORDER FLOW CÂND CITY EXISTĂ ---
    if ctx and isinstance(ctx, dict) and ctx.get("flow") == "order":
        slots_in_ctx = ctx.get("slots") or {}
        if slots_in_ctx.get("city") or slots_in_ctx.get("raion"):
            # Dacă clasificatorul ar detecta "ask_delivery", îl anulăm aici
            result_extra["delivery_intent"] = False

    # Greeting (fără ofertă)
    GREET_TOKENS = {"salut", "noroc", "buna", "bună", "bună ziua", "hello", "hi"}
    if any(tok in t_norm for tok in GREET_TOKENS) and len(t_norm) <= 24:
        result_extra["greeting"] = True
        # editorul de mesaje poate folosi direct acest răspuns
        result_extra["suggested_reply"] = "Salut! Cu ce vă pot ajuta astăzi?"

    # City extraction când ești în flux activ (order/photo)
    if ctx and ctx.get("flow") in {"order", "photo"}:
        city = _extract_city(t_norm)
        if city and not ctx.get("order_city"):
            ctx["order_city"] = city
            result_extra["detected_city"] = city
            result_extra["suggested_reply"] = (
                f"Notat: {city}. Vă rog și strada și numărul, ca să finalizăm adresa."
            )

    # Trigger de livrare (poți face ramificație în renderer)
    if any(tok in t_norm for tok in DELIVERY_TRIGGERS):
        result_extra["delivery_intent"] = True

    # B) Clasificare ca înainte
    ai = classify_with_openai(message_text) if use_openai else {"confidence": 0}
    kw = keyword_fallback(message_text, classifier_tags or {})

    if not ai or ai.get("confidence", 0) < 0.35:
        merged = kw
    else:
        merged = _merge_openai_and_keywords(ai, kw)

    # Normalizează ieșirea: dacă e None sau non-dict, folosește un schelet sigur
    if not isinstance(merged, dict):
        merged = {}

    # Completează cu valori implicite astfel încât consumatorii să fie siguri
    if "product_id" not in merged: merged["product_id"] = "UNKNOWN"
    if "intent"     not in merged: merged["intent"]     = "other"
    if "slots"      not in merged: merged["slots"]      = {}
    if "confidence" not in merged: merged["confidence"] = (ai.get("confidence", 0) if isinstance(ai, dict) else 0)
    if "neon_redirect" not in merged: merged["neon_redirect"] = False

    # C) Atașează meta (greeting/city/suppress_offer/etc.)
    merged.update(result_extra)
    return merged