# agency_setup.py
from __future__ import annotations
import os, json, hashlib
from typing import Dict, List
from agency_swarm import Agent, Agency, set_openai_key
from agency_swarm.tools import BaseTool
from pydantic import Field

# Cheia OpenAI există deja în .env; nu schimbăm nimic
set_openai_key(os.getenv("OPENAI_API_KEY", ""))

# ---- Tool: citește context.json (prețuri, template-uri, politici) ------------
class GetBusinessInfo(BaseTool):
    """Returnează din context.json secțiuni precum 'prices', 'templates', 'policies'."""
    key: str = Field(..., description="Cheia dorită, ex: 'prices' sau 'templates'")

    def run(self):
        with open("context.json", "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get(self.key, {})

# ---- Agenți -------------------------------------------------------------------
sales = Agent(
    name="Sales",
    description="Răspunde la prețuri, livrare, termene; pasează la Orders când e comandă.",
    instructions=(
        "Răspunde concis în română/rusă. Pentru prețuri/texte, folosește tool-ul GetBusinessInfo. "
        "Dacă utilizatorul vrea să comande, pasează conversația la Orders cu sumarul ales."
    ),
    tools=[GetBusinessInfo],
    temperature=0.2,
)

orders = Agent(
    name="Orders",
    description="Colectează nume, telefon, localitate, adresă, model/dimensiuni; confirmă rezumat.",
    instructions=(
        "Colectează strict câmpurile lipsă. Fă un rezumat final clar. "
        "Dacă lipsesc informații comerciale, cere Sales să confirme."
    ),
    temperature=0.2,
)

agency = Agency(
    [
        sales,           # entry point
        [sales, orders], # Sales -> Orders
    ],
    shared_instructions="Agenții trebuie să folosească tool-urile pentru informații exacte.",
    temperature=0.2,
)

# ---- Persistență threads: Redis dacă există REDIS_URL, altfel memorie --------
try:
    import redis, json as _json
    _r = redis.from_url(os.getenv("REDIS_URL")) if os.getenv("REDIS_URL") else None
except Exception:
    _r = None

_THREADS_MEM: Dict[str, List[dict]] = {}

def _hash(chat_id: str) -> str:
    return hashlib.sha256(chat_id.encode()).hexdigest()

def load_threads(chat_id: str) -> List[dict]:
    if _r:
        raw = _r.get(f"threads:{_hash(chat_id)}")
        return _json.loads(raw) if raw else []
    return _THREADS_MEM.get(chat_id, [])

def save_threads(new_threads: List[dict], chat_id: str) -> None:
    if _r:
        _r.set(f"threads:{_hash(chat_id)}", _json.dumps(new_threads))
    else:
        _THREADS_MEM[chat_id] = new_threads

def attach_thread_callbacks(current_chat_id: str):
    # Agency Swarm recomandă threads callbacks pentru producție (persistența conversațiilor). :contentReference[oaicite:2]{index=2}
    agency.threads_callbacks = {
        "load": lambda: load_threads(current_chat_id),
        "save": lambda new_threads: save_threads(new_threads, current_chat_id),
    }
