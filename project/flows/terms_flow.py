# app/flows/terms_flow.py

from typing import Dict, Optional, Tuple
import json
import os
import re

from app.business.shipping import get_shipping_message, get_shipping_by_city

# --- încărcăm lista de localități/raioane MD (pentru extragere din text) ---
_LOC_PATH = os.path.join("data", "md_locations.json")
try:
    with open(_LOC_PATH, "r", encoding="utf-8") as f:
        _LOC = json.load(f)
        _CITIES = {c.lower() for c in _LOC.get("cities", [])}
        _RAIONS = {r.lower() for r in _LOC.get("raions", [])}
except Exception:
    _CITIES, _RAIONS = set(), set()

# sinónime/normalizări minime
def _norm_ro(s: str) -> str:
    if not s:
        return ""
    return s.lower().translate(str.maketrans({"ş": "ș", "ţ": "ț", "â": "î"})).strip()

def _title(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip()).title()

def _extract_city_raion(text: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Caută heurisitic localitatea/raionul în text (Chișinău/Bălți au prioritate).
    Returnează (city, raion).
    """
    low = _norm_ro(text)

    if "chișinău" in low or "chisinau" in low:
        return "Chișinău", None
    if "bălți" in low or "balti" in low:
        return "Bălți", None

    # "orașul/satul/comuna X"
    m = re.search(r"(orașul|orasul|satul|comuna)\s+([a-zăâîșț\- ]{2,40})", low)
    if m:
        return _title(m.group(2)), None

    # "X, raionul/comuna/raion Y"
    m = re.search(r"(.+?)[,\-]\s*(raionul|r\.|raion)\s+(.+)$", low)
    if m:
        return _title(m.group(1)), _title(m.group(3))

    # match direct din liste
    for c in _CITIES:
        if c and c in low:
            return _title(c), None
    for r in _RAIONS:
        if r and r in low:
            return None, _title(r)

    return None, None


# ----------------------------
# API public (folosit din router/flow)
# ----------------------------

def start_terms_intro() -> str:
    """
    Primul mesaj din pasul 'terms': timpi execuție + cerere localitate.
    """
    return get_shipping_message("terms_delivery_intro") or ""


def handle_terms_message(user_text: str, slots: Dict) -> Tuple[str, str]:
    """
    Procesează răspunsul userului în pasul 'terms'.
    - încearcă să extragă localitatea/raionul
    - dacă găsește -> returnează mesajul corect de livrare și next_step='delivery_choice'
    - dacă nu -> cere explicit localitatea și next_step='terms'
    Returnează: (mesaj_către_user, next_step)
    """
    city, raion = _extract_city_raion(user_text or "")
    slots.setdefault("city", None)
    slots.setdefault("raion", None)

    if city:
        slots["city"] = city
    if raion:
        slots["raion"] = raion

    if slots.get("city") or slots.get("raion"):
        # avem cel puțin o localitate/raion → dăm opțiunile de livrare potrivite
        msg = get_shipping_by_city(slots.get("city") or "")
        return msg, "delivery_choice"

    # altfel cerem explicit localitatea
    ask = (
        "Spuneți-ne vă rog localitatea\n"
        "(ex: «Chișinău», «Bălți», sau «Numele satului, raionul ...»)."
    )
    return ask, "terms"
