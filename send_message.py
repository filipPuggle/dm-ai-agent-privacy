import os
import logging
import requests

PAGE_ACCESS_TOKEN = (os.getenv("PAGE_ACCESS_TOKEN") or "").strip()
GRAPH_API = "https://graph.facebook.com/v23.0/me/messages"

def send_instagram_message(recipient_id: str, text: str):
    """
    Trimite DM pe Instagram folosind Graph API.
    Necesită PAGE_ACCESS_TOKEN cu permisiuni de IG messaging.
    """
    if not PAGE_ACCESS_TOKEN:
        raise RuntimeError("PAGE_ACCESS_TOKEN lipsește")

    payload = {
        "messaging_product": "instagram",
        "recipient": {"id": recipient_id},
        "message": {"text": text},
    }
    params = {"access_token": PAGE_ACCESS_TOKEN}

    resp = requests.post(GRAPH_API, params=params, json=payload, timeout=20)
    try:
        resp.raise_for_status()
    except Exception as e:
        logging.error("IG send error: %s | %s", e, resp.text)
        raise
    return resp.json()
