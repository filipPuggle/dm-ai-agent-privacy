import json, re, unicodedata
from typing import Optional, Dict, List, Any, Tuple
from openai import OpenAI
from tools.deadline_planner import evaluate_deadline, format_reply_ro
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

try:
    from tools.catalog_pricing import get_global_template
except Exception:
    def get_global_template(name: str) -> Optional[str]:
        return ""
client = OpenAI()  # uses OPENAI_API_KEY from env

# --- price / offer control ----------------------------------------------------

GREETINGS = {
    "buna ziua","bună ziua","buna dimineata","bună dimineața","buna seara","bună seara",
    "buna","bună","salut","salutare","hello","hi"
}


RO_TZ = ZoneInfo("Europe/Chisinau")

def time_of_day_greeting(now: datetime | None = None) -> str:
    """Returnează salutul în funcție de ora locală Chișinău."""
    now = now or datetime.now(RO_TZ)
    hr = now.hour
    return "Bună seara!" if (hr >= 18 or hr < 6) else "Bună ziua!"

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
    st: Dict[str, Any] | None = None,
    msg_text: str | None = None,
    now: datetime | None = None,
    ttl_hours: int = 6,
) -> Tuple[bool, str | None]:
    """
    Actualizează starea (TTL, greeted) și decide dacă răspundem DOAR cu salut.
    Returnează (handled, reply_text sau None).
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
        return True, f"{time_of_day_greeting(now)} Ce te pot ajuta astăzi?"

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

def _normalize_text(s: str) -> str:
    s = (s or "").strip().lower()
    s = unicodedata.normalize("NFKD", s)
    s = re.sub(r"\s+", " ", s)
    return s

def _keyword_classify(text: str, tags: Dict[str, List[str]]) -> Tuple[Optional[str], float]:
    """
    Clasificator simplu pe pattern-uri/chei primite prin `classifier_tags`.
    Returnează (tag, score in [0..1]).
    """
    best_tag: Optional[str] = None
    best_score: float = 0.0
    text = (text or "").lower()

    for tag, patterns in (tags or {}).items():
        pats = [p.lower() for p in patterns if p]
        if not pats:
            continue
        hits = sum(1 for p in pats if p in text)
        score = hits / len(pats)
        if score > best_score:
            best_tag, best_score = tag, score

    return best_tag, best_score



def route_message(
    message_text: str,
    classifier_tags: Dict[str, List[str]],
    use_openai: bool = True,                # păstrat pt. compatibilitate, nu îl folosim aici
    ctx: Optional[Dict[str, Any]] = None,
    cfg: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Router robust:
      - normalizare text obligatorie
      - salut o singură dată (pre_greeting_guard)
      - gărzi anti 'off_topic' în flow-uri active
      - trigger explicit pentru PRELUARE DIN OFICIU
      - editare nume (intent 'numele trebuie schimbat')
      - heuristici de cumpărare generală (nu forțăm P1)
      - extragere oraș în flow activ; semnalizare intenție livrare
    Returnează: {'reply','ctx','tag','score','extra'}
    """

    # === Pre-procesare ===
    t_norm = _normalize_text(message_text)
    result: Dict[str, Any] = {
        "extra": {
            "norm_text": t_norm,
            # nu mai trimitem oferta inițială când suntem deja într-un flow
            "suppress_initial_offer": False if not (ctx and ctx.get("flow") in {"order", "photo"}) else True,
        }
    }

    # Context inițial
    if ctx is None:
        ctx = {}
    ctx.setdefault("order", {})
    ctx.setdefault("slots", {})
    order = ctx["order"]
    slots = ctx["slots"]

    # Salut o singură dată per conversație
    handled, greet_text = pre_greeting_guard(ctx, t_norm)
    if handled and greet_text:
        result["greeting"] = greet_text
        ctx["greeted"] = True



    # === Clasificare (keyword based) ===
    tag, score = _keyword_classify(t_norm, classifier_tags)
    result["tag"], result["score"] = tag, score

    # === Trigger: PRELUARE DIN OFICIU ===
    if any(k in t_norm for k in ("preluare", "ridicare", "oficiu")):
        ctx["stage"] = "collect_contacts_office"
        reply = (
            "Ați ales preluare din oficiu (Chișinău, Feredeului 4/4, 9:00–16:00).\n"
            "Pentru finalizare, trimiteți, vă rog:\n"
            "• Nume și prenume\n"
            "• Telefon\n"
            "• Zi/ora aproximativă a preluării"
        )
        result["reply"] = f"{result.get('greeting','')}\n{reply}".strip()
        result["ctx"] = ctx
        return result

    # === Etape active (nu întrerupem cu mesaje generice) ===
    ACTIVE_FLOW_STAGES = {
        "collect_contacts_office",
        "await_confirm_office",
        "choose_delivery",
        "confirm",
        "recap",
        "photo",
        "order",
    }
    stage = ctx.get("stage")

    # ——— Name edit intent (mutat din blocul gri) ———
    if ("numele trebuie schimbat" in t_norm) or (t_norm in {"numele", "nume"}):
        order["_await_field"] = "name"
        result["reply"] = "Spuneți numele corect și actualizez imediat."
        result["ctx"] = ctx
        return result

    if order.get("_await_field") == "name":
        cand = extract_name_candidate(message_text)
        if cand:
            slots["name"] = cand
            order.pop("_await_field", None)
            result["reply"] = f"Am actualizat numele la: {cand}\n\nRecapitulare actualizată:\n"
            result["ctx"] = ctx
            return result
        else:
            result["reply"] = "Nu am putut valida numele. Scrieți doar numele și prenumele (fără cifre)."
            result["ctx"] = ctx
            return result

    # ——— Heuristic: “vreau să cumpăr o lampă …” → cerere generală de preț (fără a forța P1) ———
    BUY_WORDS   = ("cumpăr", "cumpar", "vreau", "aș vrea", "as vrea", "doresc",
                   "am nevoie", "nevoie", "îmi trebuie", "imi trebuie", "vreau să fac rost")
    LAMP_WORDS  = ("lampă", "lampa", "lampi", "lampă după poză", "lampa dupa poza",
                   "lampă simplă", "lampa simpla")

    if any(w in t_norm for w in BUY_WORDS) and any(w in t_norm for w in LAMP_WORDS):
        # Marcăm explicit intenția ca "ask_price"/catalog, fără să intrăm în livrare
        result["extra"]["intent"] = "ask_price"
        result["extra"]["delivery_intent"] = False
        # dacă ai template în catalog, îl folosim prietenos
        tmpl = get_global_template("initial_multiline")
        if tmpl:
            result["reply"] = f"{result.get('greeting','')}\n{tmpl}".strip()
            result["ctx"] = ctx
            return result

    # ——— În flow activ: extrage orașul din mesaj și marchează dacă userul discută livrarea ———
    if stage in ACTIVE_FLOW_STAGES:
        city = _extract_city(t_norm)
        if city and not slots.get("city"):
            slots["city"] = city
            result["extra"]["detected_city"] = city
            result["extra"]["suggested_reply"] = (
                f"Notat: {city}. Vă rog și strada și numărul, ca să finalizăm adresa."
            )
        # semnal livrare când apar trigger-ele
        if any(tok in t_norm for tok in DELIVERY_TRIGGERS):
            result["extra"]["delivery_intent"] = True

        # router-ul nu trimite reply fix; webhook-ul gestionează pasul curent
        result["reply"] = ""
        result["ctx"] = ctx
        return result

    # === Fallback / ofertă inițială prietenoasă (fără get_price) ===
    if (not tag) or (score < 0.65):
        tmpl = get_global_template("initial_multiline")
        result["reply"] = f"{result.get('greeting','')}\n{tmpl}".strip()
        result["ctx"] = ctx
        return result

    # === Rute explicite pe tag-uri ===
    if tag in {"p2_photo_lamp", "lamp_after_photo", "photo"}:
        ctx["flow"] = "photo"
        ctx["stage"] = "photo"
        reply = get_global_template("ask_photo")
        result["reply"] = f"{result.get('greeting','')}\n{reply}".strip()
        result["ctx"] = ctx
        return result

    if tag in {"p1_simple_lamp", "generic_lamp_interest"}:
        ctx["flow"] = "order"
        ctx["stage"] = "order"
        reply = get_global_template("p1_offer")
        result["reply"] = f"{result.get('greeting','')}\n{reply}".strip()
        result["ctx"] = ctx
        return result

    if tag in {"delivery_options", "shipping_info"}:
        reply = get_global_template("delivery_options")
        result["reply"] = f"{result.get('greeting','')}\n{reply}".strip()
        result["ctx"] = ctx
        return result

    # === Implicit: răspuns informativ generic ===
    reply = get_global_template("faq_generic")
    result["reply"] = f"{result.get('greeting','')}\n{reply}".strip()
    result["ctx"] = ctx
    return result