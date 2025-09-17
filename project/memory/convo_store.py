from __future__ import annotations
import time
import threading
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional

# Un mesaj din conversație (minimul necesar pentru context)
@dataclass
class Message:
    role: str           # "user" | "assistant" | "system" | "event"
    text: str
    ts: float           # epoch seconds
    meta: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        # mică curățenie: nu serializăm meta gol
        if not d.get("meta"):
            d.pop("meta", None)
        return d


class ConvoStore:
    """
    Memorie în RAM pentru conversații (per user_id).
    - cap la numărul de mesaje (max_messages)
    - TTL pentru conversație (ttl_seconds)
    - meta per user (ex: greeted, language, last_intent etc.)

    NOTĂ: e in-memory; la restart se golește. Pentru persistență, pune un adaptor Redis.
    """

    def __init__(self, max_messages: int = 40, ttl_seconds: int = 6 * 3600):
        self.max_messages = max_messages
        self.ttl_seconds = ttl_seconds
        self._store: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    # ----------------- intern -----------------

    def _now(self) -> float:
        return time.time()

    def _bucket(self, user_id: str) -> Dict[str, Any]:
        b = self._store.get(user_id)
        if not b:
            b = {"history": [], "meta": {}, "updated_at": self._now()}
            self._store[user_id] = b
        return b

    def _trim(self, history: List[Message]) -> List[Message]:
        if len(history) > self.max_messages:
            return history[-self.max_messages :]
        return history

    def _purge_expired_locked(self) -> None:
        now = self._now()
        to_del = []
        for uid, b in self._store.items():
            if now - float(b.get("updated_at", 0)) > self.ttl_seconds:
                to_del.append(uid)
        for uid in to_del:
            self._store.pop(uid, None)

    # ----------------- API public -----------------

    def purge_expired(self) -> None:
        """Șterge conversațiile vechi (TTL). Apelează periodic (ex. la fiecare webhook)."""
        with self._lock:
            self._purge_expired_locked()

    def append(self, user_id: str, role: str, text: str, *, meta: Optional[Dict[str, Any]] = None) -> None:
        """Adaugă un mesaj în istoric."""
        m = Message(role=role, text=(text or "").strip(), ts=self._now(), meta=meta or {})
        with self._lock:
            b = self._bucket(user_id)
            b["history"].append(m)
            b["history"] = self._trim(b["history"])
            b["updated_at"] = self._now()

    def add_user(self, user_id: str, text: str, **meta) -> None:
        self.append(user_id, "user", text, meta=meta)

    def add_bot(self, user_id: str, text: str, **meta) -> None:
        self.append(user_id, "assistant", text, meta=meta)

    def add_event(self, user_id: str, text: str, **meta) -> None:
        self.append(user_id, "event", text, meta=meta)

    def history(self, user_id: str, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Returnează istoria ca listă de dict (pentru LLM / debug)."""
        with self._lock:
            b = self._bucket(user_id)
            h = b["history"]
            if limit is not None and limit >= 0:
                h = h[-limit:]
            return [m.to_dict() for m in h]

    def last_user_text(self, user_id: str) -> str:
        """Ultimul mesaj user (sau '')."""
        with self._lock:
            for m in reversed(self._bucket(user_id)["history"]):
                if m.role == "user":
                    return m.text
        return ""

    # ---------- meta (flags / valori per user) ----------

    def get_meta(self, user_id: str, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._bucket(user_id)["meta"].get(key, default)

    def set_meta(self, user_id: str, key: str, value: Any) -> None:
        with self._lock:
            b = self._bucket(user_id)
            b["meta"][key] = value
            b["updated_at"] = self._now()

    def incr_meta(self, user_id: str, key: str, step: int = 1) -> int:
        with self._lock:
            b = self._bucket(user_id)
            val = int(b["meta"].get(key, 0)) + step
            b["meta"][key] = val
            b["updated_at"] = self._now()
            return val

    def clear(self, user_id: str) -> None:
        """Șterge complet conversația cu userul (util după handoff)."""
        with self._lock:
            self._store.pop(user_id, None)

# ------------- instanță globală simplă -------------
# Poți folosi direct 'CONVOS' în proiect.
CONVOS = ConvoStore()
