"""
Classifier simplu pentru intenții.
Poate fi extins ulterior cu embeddings sau LLM, dar acum e rules-based.
"""

import re
from app.app.intents import Intents


def classify_text(text: str) -> str:
    """
    Primește un mesaj text și returnează intenția (din Intents).
    """
    if not text:
        return Intents.OTHER

    low = text.lower().strip()

    # -------------------------
    # Order intent
    # -------------------------
    if any(k in low for k in ["vreau", "comand", "cumpăr", "as dori", "preț", "costă"]):
        return Intents.ORDER

    # -------------------------
    # FAQ intents
    # -------------------------
    if "livrare" in low or "cât durează" in low:
        return Intents.FAQ_DELIVERY
    if "preț" in low or "cost" in low:
        return Intents.FAQ_PRICING
    if "condiții" in low or "termeni" in low or "garanție" in low:
        return Intents.FAQ_TERMS

    # -------------------------
    # Media intent
    # -------------------------
    if re.search(r"(jpg|jpeg|png|poza|fotografie|imagine)", low):
        return Intents.MEDIA

    return Intents.OTHER


def classify_message(message: dict) -> str:
    """
    Decide intenția pe baza tipului de mesaj.
    message = {
        "type": "text"|"image"|"video"|"audio",
        "text": "...",
        ...
    }
    """
    mtype = message.get("type")
    if mtype == "image":
        return Intents.MEDIA
    if mtype == "text":
        return classify_text(message.get("text", ""))

    return Intents.OTHER
