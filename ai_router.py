import json, re
from typing import Any, Dict, List
from openai import OpenAI

client = OpenAI() 

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
    "Ești un *router NLU* pentru un magazin de lămpi acrilice.\n"
    "ÎNTOARCE STRICT arguments JSON pentru funcția route_message (fără text liber).\n"
    "Produse: P1=Lampă simplă, P2=Lampă după poză, P3=Panou neon.\n"
    "Dacă userul cere neon → product_id=P3, neon_redirect=true.\n"
    "Dacă cere foto/machetă → product_id=P2, intent='send_photo' sau 'want_custom'.\n"
    "Dacă cere preț/tipuri în stoc → intent='ask_price' sau 'ask_catalog'.\n"
    "Detectează limba: ro/ru. confidence în [0,1]."
)

def classify_with_openai(message_text: str) -> Dict[str, Any]:
    
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
    try:
        tool_call = resp.choices[0].message.tool_calls[0]
        data = json.loads(tool_call.function.arguments or "{}")
    except Exception:
        data = {"product_id":"UNKNOWN","intent":"other","language":"other",
                "neon_redirect": False, "confidence": 0.0, "slots": {}}
    return data

def keyword_fallback(message_text: str, classifier_tags: Dict[str, List[str]]) -> Dict[str, Any]:
    t = message_text.lower()
    for pid, tags in classifier_tags.items():
        for tag in tags:
            if re.search(rf"\b{re.escape(tag.lower())}\b", t):
                return {"product_id": pid, "intent": "keyword_match",
                        "language": "ro", "neon_redirect": (pid=="P3"),
                        "confidence": 0.5, "slots": {}}
    if any(w in t for w in ["salut","bună","buna","привет","здравствуйте"]):
        return {"product_id":"UNKNOWN","intent":"greeting","language":"ro",
                "neon_redirect": False,"confidence":0.4,"slots":{}}
    return {"product_id":"UNKNOWN","intent":"other","language":"other",
            "neon_redirect": False,"confidence":0.0,"slots":{}}

def route_message(message_text: str,
                  classifier_tags: Dict[str, List[str]],
                  use_openai: bool = True) -> Dict[str, Any]:
    result = classify_with_openai(message_text) if use_openai else {"confidence":0}
    if (not result) or (result.get("confidence",0) < 0.35):
        result = keyword_fallback(message_text, classifier_tags)
    return result
