"""
Filtru pentru limbaj nepotrivit.
- detect_profanity(text) -> bool
- clean_text(text) -> text cu cuvinte mascate
- handle_profanity(user_id, text, state) -> răspuns standard + flag în state
"""

import re
from typing import Dict

# Listă simplă de cuvinte vulgare (poți adăuga mai multe după caz)
BAD_WORDS = [
    "dracu", "dracului", "pizda", "pzd", "curva", "boală",
    "fut", "fute", "futut", "futu", "mortii", "morții", "morti",
    "pulă", "pula", "plm", "blea", "bl", "iaibu"
]

# regex pentru match parțial, insensibil la litere mari/mici
RE_BAD = re.compile(r"\b(" + "|".join(BAD_WORDS) + r")\b", re.IGNORECASE)

def detect_profanity(text: str) -> bool:
    """
    Returnează True dacă textul conține cuvinte interzise.
    """
    if not text:
        return False
    return bool(RE_BAD.search(text))

def clean_text(text: str) -> str:
    """
    Înlocuiește cuvintele vulgare cu *** pentru loguri sau afișare neutră.
    """
    if not text:
        return text
    return RE_BAD.sub("***", text)

def handle_profanity(user_id: str, text: str, state: Dict) -> str:
    """
    Marchează sesiunea și întoarce un răspuns politicos.
    """
    state["flagged_profanity"] = True
    # Poți decide: să ignori, să răspunzi neutru, sau să trimiți la operator
    return (
        "Vă rog să păstrăm conversația într-un limbaj respectuos 🙏\n"
        "Dacă doriți informații despre produse, sunt aici să vă ajut 💡."
    )
