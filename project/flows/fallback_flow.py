from typing import Dict
from app.sendmessage import send_instagram_message

FALLBACK_MESSAGES = [
    "Îmi cer scuze, nu am înțeles exact întrebarea 🥲",
    "Un coleg vă poate ajuta mai bine cu acest subiect.",
    "Ne puteți lăsa un număr de telefon pentru a fi contactat direct 📞?"
]


def handle_fallback(user_id: str, user_text: str, state: Dict) -> None:
    """
    Tratează situațiile când nu există o intenție clară.
    
    - trimite un mesaj generic
    - oferă opțiunea de handoff la om
    - poate salva mesajul pentru operator
    """
    # alegem un mesaj fallback
    reply = FALLBACK_MESSAGES[0]

    # logica: dacă utilizatorul a scris deja ceva de tip "operator" sau "vreau să vorbesc"
    low = (user_text or "").lower()
    if any(word in low for word in ["operator", "vreau să vorbesc", "vreau număr", "sună"]):
        reply = "Vă rog să ne lăsați un număr de telefon și un coleg vă contactează cât mai curând. 📲"

        # aici poți marca starea pentru handoff real
        state["handoff"] = True

    # trimite mesajul înapoi
    send_instagram_message(user_id, reply)
