import re
import json
import os
from typing import Optional

# Regex pentru telefon și nume
PHONE_REGEX = re.compile(r"^(\+373\d{8}|0\d{8})$")
NAME_REGEX = re.compile(r"^[a-zA-ZăâîșțĂÂÎȘȚ\-]{2,30}(\s+[a-zA-ZăâîșțĂÂÎȘȚ\-]{2,30})?$")

# Încarcă orașele și raioanele din fișier JSON
LOCATIONS_PATH = os.path.join("data", "md_locations.json")
try:
    with open(LOCATIONS_PATH, "r", encoding="utf-8") as f:
        LOCATIONS = json.load(f)
        KNOWN_CITIES = {c.lower() for c in LOCATIONS.get("cities", [])}
        KNOWN_RAIONS = {r.lower() for r in LOCATIONS.get("raions", [])}
except FileNotFoundError:
    KNOWN_CITIES, KNOWN_RAIONS = set(), set()


def validate_phone(phone: str) -> bool:
    if not phone:
        return False
    return bool(PHONE_REGEX.match(phone.strip()))


def normalize_phone(phone: str) -> Optional[str]:
    if not phone:
        return None
    digits = re.sub(r"\D", "", phone)
    if digits.startswith("373") and len(digits) == 11:
        return f"+{digits}"
    if digits.startswith("0") and len(digits) == 9:
        return f"+373{digits[1:]}"
    return None


def validate_name(name: str) -> bool:
    if not name:
        return False
    return bool(NAME_REGEX.match(name.strip()))


def validate_city_or_raion(text: str) -> bool:
    """
    Verifică dacă textul este un oraș sau un raion valid din MD.
    """
    if not text:
        return False
    low = text.strip().lower()
    return low in KNOWN_CITIES or low in KNOWN_RAIONS


def validate_payment_method(payment: str) -> bool:
    if not payment:
        return False
    return payment.lower() in {"numerar", "cash", "transfer", "card", "prepay"}


def validate_delivery_method(delivery: str) -> bool:
    if not delivery:
        return False
    return delivery.lower() in {"curier", "poștă", "posta", "oficiu"}
