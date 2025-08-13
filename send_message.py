import os
import requests
import logging

log = logging.getLogger("send_message")

GRAPH_API_VERSION = os.getenv("GRAPH_API_VERSION", "v23.0")
IG_BUSINESS_ID = os.getenv("INSTAGRAM_BUSINESS_ACCOUNT_ID")
ACCESS_TOKEN = os.getenv("GRAPH_API_ACCESS_TOKEN") or os.getenv("INSTAGRAM_ACCESS_TOKEN")

API_BASE = f"https://graph.facebook.com/{GRAPH_API_VERSION}"


def _post_json(url: str, payload: dict) -> dict:
    params = {"access_token": ACCESS_TOKEN}
    r = requests.post(url, params=params, json=payload, timeout=20)
    if not r.ok:
        log.error("❌ Instagram send error: %s %s", r.status_code, r.text)
        r.raise_for_status()
    log.info("✅ IG send ok: %s", r.text)
    return r.json()


def send_text(recipient_id: str, text: str) -> dict:
    """
    Trimite mesaj text pe IG Graph API: /{IG_BUSINESS_ID}/messages
    (fără `messaging_type` – nu e necesar pe Instagram).
    """
    if not IG_BUSINESS_ID or not ACCESS_TOKEN:
        raise RuntimeError("Missing INSTAGRAM_BUSINESS_ACCOUNT_ID or GRAPH_API_ACCESS_TOKEN")
    url = f"{API_BASE}/{IG_BUSINESS_ID}/messages"
    payload = {
        "recipient": {"id": recipient_id},
        "message": {"text": text}
    }
    return _post_json(url, payload)
