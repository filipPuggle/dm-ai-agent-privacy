import os
import requests
import logging

log = logging.getLogger(__name__)


def _get_token() -> str:
    return (
        os.getenv("IG_PAGE_ACCESS_TOKEN", "").strip()
        or os.getenv("GRAPH_API_ACCESS_TOKEN", "").strip()
        or os.getenv("INSTAGRAM_ACCESS_TOKEN", "").strip()
    )

def _get_ig_business_id() -> str:
    return os.getenv("INSTAGRAM_BUSINESS_ACCOUNT_ID", "").strip()

API_BASE = "https://graph.facebook.com/v23.0"  

def send_instagram_text(recipient_igsid: str, text: str) -> dict:
    """
    Trimite un DM către un utilizator Instagram folosind Messenger API for Instagram.
    POST {API_BASE}/{IG_BUSINESS_ID}/messages
    Body: { "messaging_product":"instagram", "recipient":{"id":...}, "message":{"text":...} } :contentReference[oaicite:4]{index=4}
    """
    token = _get_token()
    ig_id = _get_ig_business_id()
    if not token or not ig_id:
        raise RuntimeError("Config lipsă: IG_PAGE_ACCESS_TOKEN/GRAPH_API_ACCESS_TOKEN/INSTAGRAM_ACCESS_TOKEN sau INSTAGRAM_BUSINESS_ACCOUNT_ID")

    url = f"{API_BASE}/{ig_id}/messages"
    payload = {
        "messaging_product": "instagram",
        "recipient": {"id": recipient_igsid},
        "message": {"text": text},
    }
    headers = {"Authorization": f"Bearer {token}"}
    r = requests.post(url, json=payload, headers=headers, timeout=20)
    try:
        r.raise_for_status()
    except Exception:
        log.error("IG send error %s %s", r.status_code, r.text)
        raise
    return r.json()
