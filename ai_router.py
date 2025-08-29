import os
import json
import re
from typing import Any, Dict, List
from openai import OpenAI

# Inițializează clientul doar dacă există cheia în env.
_OPENAI_KEY = os.getenv("OPENAI_API_KEY", "").strip()
client = OpenAI() if _OPENAI_KEY else None

# JSON Schema pentru arguments ale funcției route_message
ROUTER_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "product_id": {"type": "string", "enum": ["P1", "P2", "P3", "UNKNOWN"]},
        "intent": {"type": "string"},
        "language": {"type": "string", "enum": ["ro", "ru", "other"]},
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
    "required": ["product_id", "intent", "language", "neon_redirect", "confidence", "slots"],
}

SYSTEM = (
    "Ești un *router NLU* pentru un magazin de lămpi acrilice.\n"
    "ÎNTOARCE STRICT arguments JSON pentru funcția route_message (fără text liber).\n"
    "Produse: P1=Lampă simplă, P2=Lampă după poză, P3=Panou neon.\n"
    "- Dacă userul cere neon → product_id=P3, neon_redirect=true.\n"
    "- Dacă cere foto/machetă → product_id=P2, intent='send_photo' sau 'want_custom'.\n"
    "- Dacă cere preț/tipuri în stoc → intent='ask_price' sau 'ask_catalog'.\n"
    "- Dacă întreabă despre livrare/metode/curier/poștă/oras → intent='ask_delivery' și pune slots.city (dacă se deduce).\n"
    "- Dacă întreabă 'în cât timp', 'termen', 'când e gata' → intent='ask_eta'.\n"
    "Detectează limba (ro/ru/other). Setează confidence în [0,1]."
)

DEFAULT_NLU = {
    "product_id": "UNKNOWN",
    "intent": "other",
    "language": "other",
    "neon_redirect": False,
    "confidence": 0.0,
    "slots": {},
}


def classify_with_openai(message_text: str) -> Dict[str, Any]:
    """Rulează clasificarea cu LLM. Returnează strict dict NLU; fail-fast la erori."""
    if not client:
        return DEFAULT_NLU.copy()

    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0.2,  # clasificare mai deterministă
            max_tokens=1,     # nu generăm conținut liber
            messages=[
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": message_text.strip()},
            ],
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "route_message",
                        "description": "Clasifică mesajul în intenție/slots/produs.",
                        "parameters": ROUTER_SCHEMA,
                    },
                }
            ],
            tool_choice={"type": "function", "function": {"name": "route_message"}},
        )

        tool_call = resp.choices[0].message.tool_calls[0]
        data = json.loads(tool_call.function.arguments or "{}")

        # Normalizează lipsuri/forme neașteptate
        if "slots" not in data or not isinstance(data["slots"], dict):
            data["slots"] = {}
        data.setdefault("product_id", "UNKNOWN")
        data.setdefault("intent", "other")
        data.setdefault("language", "other")
        data.setdefault("neon_redirect", False)
        data.setdefault("confidence", 0.0)
        return data

    except Exception:
        return DEFAULT_NLU.copy()


def keyword_fallback(message_text: str, classifier_tags: Dict[str, List[str]]) -> Dict[str, Any]:
    """Fallback local: intenții de bază + match pe tag-uri pentru P1/P2/P3."""
    t = (message_text or "").lower()

    # 1) LIVRARE (city în slots dacă îl prindem)
    if any(w in t for w in ["livrare", "curier", "poștă", "posta", "metode de livrare", "expediere", "comrat", "chișinău", "chisinau", "bălți", "balti"]):
        city = None
        if "chișinău" in t or "chisinau" in t:
            city = "Chișinău"
        elif "bălți" in t or "balti" in t:
            city = "Bălți"
        return {
            "product_id": "UNKNOWN",
            "intent": "ask_delivery",
            "language": "ro",
            "neon_redirect": False,
            "confidence": 0.6,
            "slots": ({"city": city} if city else {}),
        }

    # 2) TERMEN / ETA
    if any(w in t for w in ["în cât timp", "in cat timp", "termen", "gata comanda", "când e gata", "cand e gata", "durata"]):
        return {
            "product_id": "UNKNOWN",
            "intent": "ask_eta",
            "language": "ro",
            "neon_redirect": False,
            "confidence": 0.6,
            "slots": {},
        }

    # 3) Match explicit pe "neon" sau "poză/foto" (în caz că tags nu le acoperă)
    if "neon" in t:
        return {
            "product_id": "P3",
            "intent": "keyword_match",
            "language": "ro",
            "neon_redirect": True,
            "confidence": 0.55,
            "slots": {},
        }

    if any(w in t for w in ["poză", "poza", "poze", "foto", "fotografie", "imagine", "machetă", "macheta", "personalizat"]):
        return {
            "product_id": "P2",
            "intent": "send_photo",
            "language": "ro",
            "neon_redirect": False,
            "confidence": 0.55,
            "slots": {},
        }

    # 4) MATCH după tag-uri P1/P2/P3 definite în catalog
    for pid, tags in classifier_tags.items():
        for tag in tags:
            if re.search(rf"\b{re.escape(tag.lower())}\b", t):
                return {
                    "product_id": pid,
                    "intent": "keyword_match",
                    "language": "ro",
                    "neon_redirect": (pid == "P3"),
                    "confidence": 0.5,
                    "slots": {},
                }

    # 5) SALUTURI
    if any(w in t for w in ["salut", "bună", "buna", "привет", "здравствуйте", "hello", "hi"]):
        return {
            "product_id": "UNKNOWN",
            "intent": "greeting",
            "language": "ro",
            "neon_redirect": False,
            "confidence": 0.4,
            "slots": {},
        }

    # 6) FALLBACK FINAL
    return DEFAULT_NLU.copy()


def route_message(
    message_text: str,
    classifier_tags: Dict[str, List[str]],
    use_openai: bool = True,
) -> Dict[str, Any]:
    """Returnează dict NLU. Preferă LLM; cade pe fallback dacă încrederea e mică."""
    result = classify_with_openai(message_text) if use_openai else {"confidence": 0}
    if (not result) or (result.get("confidence", 0.0) < 0.35):
        result = keyword_fallback(message_text, classifier_tags)
    return result