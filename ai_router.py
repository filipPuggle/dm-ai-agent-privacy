import json, re, unicodedata
from typing import Any, Dict, List
from openai import OpenAI

client = OpenAI()  # uses OPENAI_API_KEY from env

# --- utils -------------------------------------------------------------

def _norm(s: str) -> str:
    s = (s or "").strip().lower()
    # fold diacritics so "chișinău" == "chisinau", "bălți" == "balti"
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return " ".join(s.split())

ORDER_PATTERNS = [
    "cum pot plasa comanda", "cum se plaseaza comanda", "cum plasez comanda",
    "ce este nevoie pentru plasarea comenzii", "ce mai este nevoie pentru comanda",
    "care sunt pasii pentru comanda", "how do i place the order", "place order"
]

DELIVERY_TRIGGERS = [
    "livrare", "curier", "posta", "poștă", "metode de livrare", "expediere",
    "chișinău", "chisinau", "bălți", "balti", "comrat", "orhei"
]

CITY_ALIASES = {
    "chișinău": ["chisinau", "chișinău"],
    "bălți":    ["balti", "bălți"],
    # you can add more here (e.g., "comrat": ["comrat"])
}

def _extract_city(t_norm: str) -> str | None:
    for canonical, variants in CITY_ALIASES.items():
        for v in variants:
            if re.search(rf"\b{re.escape(v)}\b", t_norm):
                # return canonical with your preferred casing
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
    t = message_text.lower()

    # CUM PLASEZ COMANDA
    if any(w in t for w in [
        "cum pot plasa comanda", "cum dau comanda", "cum se plasează comanda",
        "plasa comanda", "plasez comanda", "place order", "how do i order"
    ]):
        return {"product_id":"UNKNOWN","intent":"ask_order","language":"ro",
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

def route_message(message_text: str,
                  classifier_tags: Dict[str, List[str]],
                  use_openai: bool = True) -> Dict[str, Any]:
    ai = classify_with_openai(message_text) if use_openai else {"confidence":0}
    kw = keyword_fallback(message_text, classifier_tags or {})
    # If AI is weak (<0.35), use keywords fully; otherwise merge/fix with keywords
    if not ai or ai.get("confidence", 0) < 0.35:
        return kw
    return _merge_openai_and_keywords(ai, kw)
