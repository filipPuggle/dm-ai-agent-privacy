"""
PII minimal pentru proiectul DM-AGENT:
- doar telefon (MD) este tratat ca PII pentru loguri / request-uri către terți.
- nume, adresă, localitate, deadline, tip produs, avans NU sunt redactate aici.

API:
- normalize_phone_md(text) -> "+373XXXXXXXX" sau None
- extract_phone(text) -> str|None
- redact_text_phones(text, allowlist_phones=()) -> text (înlocuiește telefoanele cu [PHONE])
- redact_payload_phones(obj, allowlist_phones=()) -> redactare recursivă în dict/list/str
"""

from __future__ import annotations
import re
from typing import Any, Iterable, Optional

# Acceptăm: +373XXXXXXXX sau 0XXXXXXXX (9 cifre după 0)
RE_PHONE_MD = re.compile(r"(?:\+?373\d{8}|0\d{8})")

def normalize_phone_md(raw: str) -> Optional[str]:
    """
    Normalizează la formatul canonic +373XXXXXXXX.
    Returnează None dacă nu pare un număr MD valid.
    """
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw)
    if digits.startswith("373") and len(digits) == 11:
        return f"+{digits}"
    if digits.startswith("0") and len(digits) == 9:
        return f"+373{digits[1:]}"
    return None

def extract_phone(text: str) -> Optional[str]:
    """
    Extrage primul număr MD din text și îl normalizează.
    """
    if not text:
        return None
    m = RE_PHONE_MD.search(text)
    if not m:
        return None
    return normalize_phone_md(m.group(0))

def redact_text_phones(text: str, allowlist_phones: Iterable[str] = ()) -> str:
    """
    Redactează telefoanele MD din text cu tokenul [PHONE], cu excepția celor din allowlist.
    Folosește asta DOAR pentru LOGURI sau payload-uri către terți.
    """
    if not text:
        return text

    # normalizăm allowlistul la formă canonică
    allow_norm = {normalize_phone_md(p) for p in (allowlist_phones or []) if p}
    allow_norm.discard(None)

    def _repl(m):
        raw = m.group(0)
        norm = normalize_phone_md(raw)
        if norm and norm in allow_norm:
            return raw  # nu redacționa numărul whitelisted (ex: numărul public al firmei)
        return "[PHONE]"

    return RE_PHONE_MD.sub(_repl, text)

def redact_payload_phones(obj: Any, allowlist_phones: Iterable[str] = ()):
    """
    Redactare recursivă doar pentru telefoane MD în structuri comune (dict/list/str).
    """
    if obj is None:
        return None
    if isinstance(obj, str):
        return redact_text_phones(obj, allowlist_phones=allowlist_phones)
    if isinstance(obj, (int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {k: redact_payload_phones(v, allowlist_phones) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact_payload_phones(v, allowlist_phones) for v in obj]
    # fallback – convertim în str și redactăm
    try:
        return redact_text_phones(str(obj), allowlist_phones=allowlist_phones)
    except Exception:
        return obj
