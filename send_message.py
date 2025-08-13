# send_message.py
import os
import requests
import logging

GRAPH_API_VERSION = os.getenv("GRAPH_API_VERSION", "v23.0")
IG_BUSINESS_ID = os.getenv("INSTAGRAM_BUSINESS_ACCOUNT_ID")
ACCESS_TOKEN = os.getenv("GRAPH_API_ACCESS_TOKEN") or os.getenv("INSTAGRAM_ACCESS_TOKEN")

API_BASE = f"https://graph.facebook.com/{GRAPH_API_VERSION}"

log = logging.getLogger("send_message")

def _post_json(url: str, payload: dict) -> dict:
    params = {"access_token": ACCESS_TOKEN}
    r = requests.post(url, params=params, json=payload, timeout=20)
    try:
        r.raise_for_status()
    except Exception:
        log.error("❌ Instagram send error: %s %s", r.status_code, r.text)
        raise
    return r.json()

def send_text(recipient_id: str, text: str) -> dict:
    """
    Trimite un mesaj text către utilizatorul IG.
    Payload simplu compatibil cu IG Graph API /{IG_BUSINESS_ID}/messages.
    """
    url = f"{API_BASE}/{IG_BUSINESS_ID}/messages"
    payload = {
        "recipient": {"id": recipient_id},
        "messaging_type": "RESPONSE",
        "message": {"text": text}
    }
    return _post_json(url, payload)
