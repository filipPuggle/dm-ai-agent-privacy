"""
Politici globale pentru comportamentul botului.
Aceste reguli sunt folosite în router și în flows pentru a asigura consistența.
"""

from typing import Dict

# ------------------------------------------------
# Config de politici
# ------------------------------------------------
POLICY = {
    "greet_once": True,          # salut doar o dată / conversație
    "max_bot_turns": 5,          # max. mesaje consecutive fără input user
    "require_handoff_p2": True,  # la Lampă după poză => obligatoriu handoff
    "require_handoff_p3": True,  # la Neon => obligatoriu handoff
}

# ------------------------------------------------
# Helpers
# ------------------------------------------------

def can_greet(state: Dict) -> bool:
    """
    Verifică dacă botul poate da salut în conversația curentă.
    """
    if not POLICY.get("greet_once"):
        return True
    return not state.get("greeted", False)

def mark_greeted(state: Dict) -> None:
    """
    Marchează conversația ca având deja un salut.
    """
    state["greeted"] = True

def should_handoff(product_id: str) -> bool:
    """
    Determină dacă produsul necesită handoff la operator.
    """
    if product_id == "P2":
        return POLICY.get("require_handoff_p2", False)
    if product_id == "P3":
        return POLICY.get("require_handoff_p3", False)
    return False

def exceeded_bot_turns(state: Dict) -> bool:
    """
    Verifică dacă botul a depășit limita de mesaje consecutive fără input de la client.
    """
    turns = state.get("bot_turns", 0)
    return turns >= POLICY.get("max_bot_turns", 5)

def register_bot_turn(state: Dict) -> None:
    """
    Incrementează counterul de mesaje consecutive trimise de bot.
    """
    state["bot_turns"] = state.get("bot_turns", 0) + 1

def reset_bot_turns(state: Dict) -> None:
    """
    Resetează counterul când userul trimite ceva.
    """
    state["bot_turns"] = 0
