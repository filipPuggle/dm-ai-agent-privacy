import os
import requests

GRAPH_VERSION = "v23.0"
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_VERSION}"

PAGE_ACCESS_TOKEN = os.getenv("PAGE_ACCESS_TOKEN")
IG_ID = os.getenv("IG_ID")

if not PAGE_ACCESS_TOKEN or not IG_ID:
    raise RuntimeError("Setează PAGE_ACCESS_TOKEN și IG_ID în .env")

def send_instagram_message(recipient_igsid: str, text: str) -> dict:
    """
    Trimite un DM pe Instagram către utilizatorul cu IGSID (Instagram-Scoped ID).
    Endpoint: POST /{IG_ID}/messages cu:
      {
        "recipient": {"id": "<IGSID>"},
        "message": {"text": "<răspuns>"}
      }
    """
    url = f"{GRAPH_BASE}/{IG_ID}/messages"
    payload = {
        "recipient": {"id": recipient_igsid},
        "message": {"text": text},
    }
    params = {"access_token": PAGE_ACCESS_TOKEN}
    resp = requests.post(url, params=params, json=payload, timeout=20)
    resp.raise_for_status()
    return resp.json()
