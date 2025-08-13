# send_message.py — folosește DOAR PAGE_ID și PAGE_ACCESS_TOKEN

import os
import requests
import logging

log = logging.getLogger("send_message")

# Nu cerem GRAPH_API_VERSION din env; fixăm v23.0 ca să nu ai alte variabile
API_BASE = "https://graph.facebook.com/v23.0"

PAGE_ID = (os.getenv("PAGE_ID") or "").strip()
PAGE_ACCESS_TOKEN = (os.getenv("PAGE_ACCESS_TOKEN") or "").strip()


def _post_json(url: str, payload: dict) -> dict:
    """POST cu tokenul din PAGE_ACCESS_TOKEN."""
    params = {"access_token": PAGE_ACCESS_TOKEN}
    r = requests.post(url, params=params, json=payload, timeout=20)
    if not r.ok:
        # Lăsăm exception pentru a fi prinsă în webhook (safe_send)
        log.error("❌ IG send error: %s %s", r.status_code, r.text)
        r.raise_for_status()
    log.info("✅ IG send ok: %s", r.text)
    return r.json()


def send_text(recipient_id: str, text: str) -> dict:
    """
    Trimite mesaj pe Instagram DM: POST /{PAGE_ID}/messages
    Cerințe Graph: PAGE_ID = IG Business ID; PAGE_ACCESS_TOKEN = *Page* token (EAA/EAAG).
    """
    if not PAGE_ID:
        raise RuntimeError("PAGE_ID nu este setat.")
    if not PAGE_ACCESS_TOKEN:
        raise RuntimeError("PAGE_ACCESS_TOKEN nu este setat.")
    url = f"{API_BASE}/{PAGE_ID}/messages"
    payload = {"recipient": {"id": recipient_id}, "message": {"text": text}}
    return _post_json(url, payload)
