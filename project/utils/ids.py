"""
Generare și validare ID-uri pentru comenzi, sesiuni și produse.
"""

import uuid
import time
from typing import Optional


def new_order_id() -> str:
    """
    Creează un ID unic pentru o comandă.
    Format: ORD-<timestamp>-<uuid4 short>
    """
    return f"ORD-{int(time.time())}-{uuid.uuid4().hex[:6].upper()}"


def new_session_id() -> str:
    """
    Creează un ID unic pentru o sesiune de conversație.
    """
    return f"SES-{uuid.uuid4().hex[:8].upper()}"


def validate_product_id(pid: str) -> Optional[str]:
    """
    Validează dacă product_id aparține catalogului.
    Returnează pid sau None.
    """
    valid_ids = {"P1", "P2", "P3"}
    return pid if pid in valid_ids else None
