import os
import requests

GRAPH_VERSION = "v23.0"
GRAPH_BASE = f"https://graph.instagram.com/{GRAPH_VERSION}"


ACCESS_TOKEN = (os.getenv("PAGE_ACCESS_TOKEN") or "").strip()
IG_ID = (os.getenv("IG_ID") or os.getenv("PAGE_ID") or "").strip()

if not ACCESS_TOKEN or not IG_ID:
    raise RuntimeError("Lipsește PAGE_ACCESS_TOKEN sau IG_ID/PAGE_ID în variabilele de mediu.")

def send_instagram_message(recipient_igsid: str, text: str) -> dict:
    """
    Trimite un DM către utilizatorul cu IGSID.
    Endpoint Instagram Login:
      POST https://graph.instagram.com/v23.0/{IG_ID}/messages
      Authorization: Bearer <IG user/system user token>
      Body: { "recipient": {"id": "<IGSID>"}, "message": {"text": "<text>"} }
    """
    url = f"{GRAPH_BASE}/{IG_ID}/messages"
    payload = {
        "recipient": {"id": recipient_igsid},
        "message": {"text": text},
    }
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}
    resp = requests.post(url, headers=headers, json=payload, timeout=20)
    resp.raise_for_status()
    return resp.json()