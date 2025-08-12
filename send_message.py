# send_message.py
import os, requests

GRAPH_VERSION = "v23.0"
GRAPH_BASE = f"https://graph.instagram.com/{GRAPH_VERSION}"

ACCESS_TOKEN = (os.getenv("PAGE_ACCESS_TOKEN") or "").strip()  # IGAA…
IG_ID = (os.getenv("IG_ID") or os.getenv("PAGE_ID") or "").strip()  # 1784…

if not ACCESS_TOKEN or not IG_ID:
    raise RuntimeError("Lipsește PAGE_ACCESS_TOKEN sau IG_ID/PAGE_ID.")

def send_instagram_message(recipient_igsid: str, text: str) -> dict:
    url = f"{GRAPH_BASE}/{IG_ID}/messages"
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}", "Content-Type": "application/json"}
    payload = {"recipient": {"id": recipient_igsid}, "message": {"text": text}}
    resp = requests.post(url, headers=headers, json=payload, timeout=20)
    resp.raise_for_status()
    return resp.json()
