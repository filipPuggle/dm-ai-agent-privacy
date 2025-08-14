import os
import requests
import logging

log = logging.getLogger("send_message")

# Instagram Messaging se face prin Facebook Graph API (nu graph.instagram.com)
API_BASE = "https://graph.facebook.com/v23.0"

PAGE_ID = (os.getenv("PAGE_ID") or "").strip()
PAGE_ACCESS_TOKEN = (os.getenv("PAGE_ACCESS_TOKEN") or "").strip()


def _post_json(url: str, payload: dict) -> dict:
    r = requests.post(url, params={"access_token": PAGE_ACCESS_TOKEN}, json=payload, timeout=20)
    if not r.ok:
        log.error("❌ IG send error: %s %s", r.status_code, r.text)
        r.raise_for_status()
    log.info("✅ IG send ok: %s", r.text)
    return r.json()


def send_text(recipient_id: str, text: str) -> dict:
    """
    Trimite DM pe Instagram prin: POST /{PAGE_ID}/messages
    """
    if not PAGE_ID:
        raise RuntimeError("PAGE_ID nu este setat.")
    if not PAGE_ACCESS_TOKEN:
        raise RuntimeError("PAGE_ACCESS_TOKEN nu este setat.")
    url = f"{API_BASE}/{PAGE_ID}/messages"
    payload = {"recipient": {"id": recipient_id}, "message": {"text": text}}
    return _post_json(url, payload)
