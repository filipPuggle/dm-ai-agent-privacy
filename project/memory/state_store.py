"""
State store = sloturi și progresul conversației per user.
Diferență față de convo_store:
- aici păstrăm datele structurate (nume, telefon, produs, deadline, etc.)
- folosim pentru a decide ce pas urmează în flow.
"""

import time
import threading
from typing import Any, Dict, Optional


class StateStore:
    def __init__(self, ttl_seconds: int = 6 * 3600):
        self.ttl_seconds = ttl_seconds
        self._store: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def _now(self) -> float:
        return time.time()

    def _bucket(self, user_id: str) -> Dict[str, Any]:
        b = self._store.get(user_id)
        if not b:
            b = {"slots": {}, "updated_at": self._now()}
            self._store[user_id] = b
        return b

    def purge_expired(self) -> None:
        now = self._now()
        to_del = []
        with self._lock:
            for uid, b in self._store.items():
                if now - float(b.get("updated_at", 0)) > self.ttl_seconds:
                    to_del.append(uid)
            for uid in to_del:
                self._store.pop(uid, None)

    # ---------------- Slots API ----------------

    def get_slot(self, user_id: str, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._bucket(user_id)["slots"].get(key, default)

    def set_slot(self, user_id: str, key: str, value: Any) -> None:
        with self._lock:
            b = self._bucket(user_id)
            b["slots"][key] = value
            b["updated_at"] = self._now()

    def has_all_slots(self, user_id: str, required: list[str]) -> bool:
        with self._lock:
            slots = self._bucket(user_id)["slots"]
            return all(slots.get(k) for k in required)

    def all_slots(self, user_id: str) -> Dict[str, Any]:
        with self._lock:
            return dict(self._bucket(user_id)["slots"])

    def clear(self, user_id: str) -> None:
        with self._lock:
            self._store.pop(user_id, None)


# instanță globală
STATE = StateStore()
