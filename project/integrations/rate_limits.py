"""
Rate limit simplu în memorie (dict).
Folosit pentru a preveni flood-ul de mesaje sau pentru a respecta limitele API.
"""

import time
from typing import Dict, Tuple

# cheie: user_id, valoare: (last_ts, count)
_RATE_BUCKET: Dict[str, Tuple[float, int]] = {}

# Config (poți muta în .env dacă vrei)
MAX_MSG_PER_MIN = 10      # maxim 10 mesaje / minut per user
COOLDOWN_SECONDS = 3      # minim 3 secunde între mesaje trimise de bot

# pentru control global
_LAST_SENT: float = 0.0


def allow_incoming(user_id: str) -> bool:
    """
    Verifică dacă mai permitem procesarea unui mesaj de la user_id (anti-flood).
    """
    now = time.time()
    last_ts, count = _RATE_BUCKET.get(user_id, (0, 0))

    # reset counter dacă a trecut mai mult de 60s
    if now - last_ts > 60:
        _RATE_BUCKET[user_id] = (now, 1)
        return True

    # increment
    if count < MAX_MSG_PER_MIN:
        _RATE_BUCKET[user_id] = (last_ts, count + 1)
        return True

    return False


def allow_outgoing() -> bool:
    """
    Verifică dacă botul are voie să trimită acum un mesaj (cooldown global).
    """
    global _LAST_SENT
    now = time.time()
    if now - _LAST_SENT >= COOLDOWN_SECONDS:
        _LAST_SENT = now
        return True
    return False