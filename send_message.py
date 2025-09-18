import os
import requests

GRAPH_VERSION = "v23.0"
GRAPH_BASE = f"https://graph.instagram.com/{GRAPH_VERSION}"


GRAPH_BASE_FB = f"https://graph.facebook.com/{GRAPH_VERSION}"

ACCESS_TOKEN = (os.getenv("PAGE_ACCESS_TOKEN") or "").strip()
IG_ID = (os.getenv("IG_ID") or os.getenv("PAGE_ID") or "").strip()

if not ACCESS_TOKEN or not IG_ID:
    raise RuntimeError("Lipsește PAGE_ACCESS_TOKEN sau IG_ID/PAGE_ID în variabilele de mediu.")

def send_instagram_message(recipient_igsid: str, text: str) -> dict:
    """
    Trimite un DM către utilizatorul cu IGSID (fluxul tău existent).
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


def reply_public_to_comment(comment_id: str, text: str) -> dict:
    url = f"{GRAPH_BASE_FB}/{comment_id}/replies"
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}
    payload = {"message": text}
    resp = requests.post(url, headers=headers, json=payload, timeout=20)
    try:
        resp.raise_for_status()
    except Exception:
        print("[DEBUG reply_public_to_comment]", resp.text)  
        raise
    return resp.json()


def send_private_reply_to_comment(comment_id: str, text: str) -> dict:
    """
    Trimite un mesaj privat către autorul comentariului (Private Reply).
    Reguli Meta:
      • se trimite prin /me/messages
      • recipient: { "comment_id": "<id>" }
      • permis o singură dată / comentariu, în 7 zile
    """
    url = f"{GRAPH_BASE_FB}/me/messages"
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "recipient": {"comment_id": str(comment_id)},
        "message": {"text": text}
    }

    resp = requests.post(url, headers=headers, json=payload, timeout=20)

    # DEBUG: loghează răspunsul dacă apare eroare
    try:
        resp.raise_for_status()
    except Exception:
        print("[DEBUG send_private_reply_to_comment]", resp.text)
        raise

    return resp.json()
