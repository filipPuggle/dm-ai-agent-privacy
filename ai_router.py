import json, re, unicodedata
from typing import Optional, Dict, List, Any
from openai import OpenAI
from tools.deadline_planner import evaluate_deadline, format_reply_ro
import re



client = OpenAI()  # uses OPENAI_API_KEY from env

# --- price / offer control ----------------------------------------------------

DISABLE_INITIAL_OFFER = True  # <- rămâne True ca să nu mai iasă NICIODATĂ

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
        "comrat","chișinău","chisinau","bălți","balti"
    ]):
        city = None
        if "chișinău" in t or "chisinau" in t: city = "Chișinău"
        elif "bălți" in t or "balti" in t:      city = "Bălți"
        return {"product_id":"UNKNOWN","intent":"ask_delivery","language":"ro",
                "neon_redirect":False,"confidence":0.6,"slots":({"city": city} if city else {})}

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
    return result

# --- main API ----------------------------------------------------------


def route_message(
    message_text: str,
    classifier_tags: Dict[str, List[str]],
    use_openai: bool = True,
    ctx: Optional[Dict[str, Any]] = None,
    cfg: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    # A) Pre-procesare & reguli ușoare
    t_norm = _norm(message_text)
    result_extra: Dict[str, Any] = {
        "norm_text": t_norm,
        # plasă de siguranță pentru a NU mai trimite niciodată oferta inițială
        "suppress_initial_offer": True,
    }

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

    # C) Atașează meta (greeting/city/suppress_offer/etc.)
    if isinstance(merged, dict):
        merged.update(result_extra)
    return merged