import re
from datetime import datetime
from zoneinfo import ZoneInfo

# Regexuri pentru termene frecvente
RELATIVE_RX = re.compile(r"\b(azi|m[âa]ine|poim[âa]ine)\b", re.IGNORECASE)
WEEKDAY_RX = re.compile(r"\b(luni|mar[țt]i|miercuri|joi|vineri|s[âa]mb[ăa]t[ăa]|duminic[ăa])\b", re.IGNORECASE)
DATE_RX = re.compile(r"\b([0-3]?\d)[./-]([01]?\d)(?:[./-](\d{2,4}))?\b")

def detect_deadline(text: str) -> str | None:
    """
    Detectează termenul solicitat dintr-un text.
    Returnează expresia găsită (ex. 'mâine', '25/09') sau None.
    """
    if not text:
        return None

    if m := RELATIVE_RX.search(text):
        return m.group(0).lower()
    if m := WEEKDAY_RX.search(text):
        return m.group(0).lower()
    if m := DATE_RX.search(text):
        return m.group(0)
    return None


def evaluate_deadline_request(text: str) -> dict:
    """
    Primește un mesaj client și decide dacă putem răspunde automat sau facem handoff.
    Returnează un dict:
        {"deadline": <expresie>, "handoff": True/False, "reply": <mesaj sugerat>}
    """
    deadline = detect_deadline(text)
    if not deadline:
        return {"deadline": None, "handoff": False, "reply": ""}

    # logica simplificată: pentru toate cererile cu termen -> handoff
    # poți rafina mai târziu dacă vrei ca unele să fie auto-confirmate
    return {
        "deadline": deadline,
        "handoff": True,
        "reply": (
            f"Ați menționat termenul «{deadline}». "
            "Pentru a confirma dacă putem realiza comanda până atunci, "
            "un coleg din echipa noastră vă va contacta direct 📞."
        )
    }