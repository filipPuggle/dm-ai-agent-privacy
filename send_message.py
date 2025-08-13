import os
import requests
import logging

log = logging.getLogger("send_message")

GRAPH_API_VERSION = (os.getenv("GRAPH_API_VERSION") or "v23.0").strip()
IG_BUSINESS_ID = ((os.getenv("INSTAGRAM_BUSINESS_ACCOUNT_ID") or "").strip())
ACCESS_TOKEN = (((os.getenv("GRAPH_API_ACCESS_TOKEN") or os.getenv("INSTAGRAM_ACCESS_TOKEN")) or "").strip())

API_BASE = f"https://graph.facebook.com/{GRAPH_API_VERSION}"

def _post_json(url: str, payload: dict) -> dict:
    r = requests.post(url, params={"access_token": ACCESS_TOKEN}, json=payload, timeout=20)
    if not r.ok:
        log.error("❌ Instagram send error: %s %s", r.status_code, r.text)
        r.raise_for_status()
    log.info("✅ IG send ok: %s", r.text)
    return r.json()

def send_text(recipient_id: str, text: str) -> dict:
    if not IG_BUSINESS_ID:
        raise RuntimeError("INSTAGRAM_BUSINESS_ACCOUNT_ID is not set.")
    if not ACCESS_TOKEN:
        raise RuntimeError("No token set. Provide GRAPH_API_ACCESS_TOKEN or INSTAGRAM_ACCESS_TOKEN.")
    url = f"{API_BASE}/{IG_BUSINESS_ID}/messages"
    payload = {"recipient": {"id": recipient_id}, "message": {"text": text}}
    return _post_json(url, payload)
