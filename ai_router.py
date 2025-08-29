import json
import re
import unicodedata
from typing import Any, Dict, List

from openai import OpenAI

# --- Config ---
LLM_MODEL = "gpt-4o-mini"
OPENAI_TEMPERATURE = 0.0         # determinism mai mare
OPENAI_TOP_P = 1.0
CONF_THRESHOLD = 0.60            # sub acest prag preferăm fallback-ul

client = OpenAI()

# ---- util: normalizare text (fără diacritice, spații multiple, lower) ----
def norm(s: str) -> str:
    s = s or ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = " ".join(s.lower().strip().split())
    return s

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
                "name": {"type": "string"},
            },
        },
    },
    "required": ["product_id","intent","language","neon_redirect","confidence","slots"],
}

SYSTEM = (
    "Ești un router NLU strict. ÎNTOARCE DOAR JSON conform schemei date.\n"
    "Produse: P1=Lampă simplă, P2=Lampă după poză, P3=Panou neon.\n"
    "- Dacă utilizatorul cere neon → product_id=P3, neon_redirect=true.\n"
    "- Dacă cere lucrare după poză/machetă → product_id=P2 și intent='send_photo' sau 'want_custom'.\n"
    "- Întrebări despre preț/prețuri/cost/tarif → intent='ask_price'.\n"
    "- Întrebări despre tipuri/asortiment/catalog → intent='ask_catalog'.\n"
    "- Livrare/metode/curier/poștă + oraș → intent='ask_delivery' și setează slots.city dacă e clar (ex: Chișinău, Bălți, Comrat, Orhei).\n"
    "- Formulări de timp/termen/ETA ('în cât timp', 'când e gata') → intent='ask_eta'.\n"
    "- Întrebări despre cum se plasează comanda ('cum comand', 'plasa comanda', 'ce este nevoie') → intent='ask_order'.\n"
    "Detectează limba (ro/ru) aproximativ; dacă nu e clar → 'ro'. Pune un 'confidence' 0..1."
)

def classify_with_openai(message_text: str) -> Dict[str, Any]:
    """Clasificare cu tool-call (funcție) + temperature=0 pentru stabilitate."""
    resp = client.chat.completions.create(
        model=LLM_MODEL,
        temperature=OPENAI_TEMPERATURE,
        top_p=OPENAI_TOP_P,
        messages=[
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": message_text.strip()},
        ],
        tools=[{
            "type": "function",
            "function": {
                "name": "route_message",
                "description": "Clasifică mesajul în intent/slots/produs.",
                "parameters": ROUTER_SCHEMA,
            }
        }],
        tool_choice={"type": "function", "function": {"name": "route_message"}},
    )
    try:
        tool_call = resp.choices[0].message.tool_calls[0]
        data = json.loads(tool_call.function.arguments or "{}")
    except Exception:
        data = {}
    # fallback hard la schemă dacă ceva nu a venit
    return data or {
        "product_id": "UNKNOWN",
        "intent": "other",
        "language": "other",
        "neon_redirect": False,
        "confidence": 0.0,
        "slots": {},
    }

# ---- fallback pe cuvinte cheie (determinist) ----
def keyword_fallback(message_text: str, classifier_tags: Dict[str, List[str]]) -> Dict[str, Any]:
    t = norm(message_text)

    # 1) LIVRARE (city în slots)
    if any(w in t for w in [
        "livrare", "metode de livrare", "curier", "posta", "postă", "expediere",
        "comrat", "chișinău", "chisinau", "balti", "balti", "orhei"
    ]):
        city = None
        if "chisinau" in t or "chișinău" in t: city = "Chișinău"
        elif "balti" in t or "balți" in t:     city = "Bălți"
        elif "comrat" in t:                    city = "Comrat"
        elif "orhei" in t:                     city = "Orhei"
        return {
            "product_id": "UNKNOWN",
            "intent": "ask_delivery",
            "language": "ro",
            "neon_redirect": False,
            "confidence": 0.8 if city else 0.6,
            "slots": ({"city": city} if city else {})
        }

    # 2) ETA / termen
    if any(w in t for w in [
        "in cat timp", "în cat timp", "în cât timp", "cand e gata", "când e gata",
        "gata comanda", "termen", "durata", "lead time", "leadtime", "timeline"
    ]):
        return {
            "product_id": "UNKNOWN",
            "intent": "ask_eta",
            "language": "ro",
            "neon_redirect": False,
            "confidence": 0.7,
            "slots": {}
        }

    # 3) COMANDĂ / how-to
    if any(w in t for w in [
        "cum comand", "cum pot comanda", "cum se plaseaza comanda",
        "plasa comanda", "plasez comanda", "continua comanda",
        "ce este nevoie pentru comanda", "ce mai este nevoie", "confirm comanda"
    ]):
        return {
            "product_id": "UNKNOWN",
            "intent": "ask_order",
            "language": "ro",
            "neon_redirect": False,
            "confidence": 0.75,
            "slots": {}
        }

    # 4) PREȚ / COST
    price_trigs = [
        "pret", "pretul", "preturi", "preturile",
        "preț", "prețul", "prețuri", "prețurile",
        "cat costa", "cât costa", "cât ar costa", "cam cat ar costa", "cam cât ar costa",
        "la ce pret", "la ce preț", "cat ajunge", "cât ajunge",
        "cost", "costul", "tarif", "tarife",
        "ma intereseaza costul", "mă interesează costul"
    ]
    if any(w in t for w in price_trigs):
        return {
            "product_id": "UNKNOWN",
            "intent": "ask_price",
            "language": "ro",
            "neon_redirect": False,
            "confidence": 0.8,
            "slots": {}
        }

    # 5) IDENTIFICARE explicită produs după tag-uri din catalog (P1/P2/P3)
    for pid, tags in classifier_tags.items():
        for tag in tags:
            if re.search(rf"\b{re.escape(norm(tag))}\b", t):
                return {
                    "product_id": pid,
                    "intent": "keyword_match",
                    "language": "ro",
                    "neon_redirect": (pid == "P3"),
                    "confidence": 0.6,
                    "slots": {}
                }

    # 6) SALUTURI
    if any(w in t for w in ["salut", "buna", "bună", "hello", "hi", "привет", "здравствуйте"]):
        return {
            "product_id": "UNKNOWN",
            "intent": "greeting",
            "language": "ro",
            "neon_redirect": False,
            "confidence": 0.5,
            "slots": {}
        }

    # 7) fallback final
    return {
        "product_id": "UNKNOWN",
        "intent": "other",
        "language": "other",
        "neon_redirect": False,
        "confidence": 0.0,
        "slots": {}
    }

def route_message(message_text: str,
                  classifier_tags: Dict[str, List[str]],
                  use_openai: bool = True) -> Dict[str, Any]:
    # 1) LLM
    result = classify_with_openai(message_text) if use_openai else {"confidence": 0.0}
    # 2) Dacă încrederea e mică, folosim fallback determinist
    if (not result) or (float(result.get("confidence", 0.0)) < CONF_THRESHOLD):
        result = keyword_fallback(message_text, classifier_tags)
    return result
