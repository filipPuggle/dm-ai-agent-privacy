import os
import requests

GRAPH_VERSION = "v23.0"
# Facebook Graph API for public comment replies
GRAPH_BASE_FB = f"https://graph.facebook.com/{GRAPH_VERSION}"

# Facebook Page Access Token (for public comment replies)
ACCESS_TOKEN = (os.getenv("PAGE_ACCESS_TOKEN") or "").strip()

# Instagram Business Account ID
IG_ID = (os.getenv("IG_ID") or "").strip()

# Debug token format
print(f"[DEBUG] Facebook Token length: {len(ACCESS_TOKEN)}")
print(f"[DEBUG] Facebook Token starts with: {ACCESS_TOKEN[:10]}...")
print(f"[DEBUG] IG_ID: {IG_ID}")

if not ACCESS_TOKEN or not IG_ID:
    raise RuntimeError("Lipsește PAGE_ACCESS_TOKEN sau IG_ID în variabilele de mediu.")

def send_instagram_message(recipient_igsid: str, text: str) -> dict:
    """
    Trimite un DM către utilizatorul cu IGSID folosind Facebook Graph API.
    Folosește Facebook Page Access Token pentru Instagram messaging.
    """
    url = f"{GRAPH_BASE_FB}/{IG_ID}/messages"
    payload = {
        "recipient": {"id": str(recipient_igsid)},
        "message": {"text": text},
    }
    # Use Facebook Page Access Token for Instagram messaging
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}
    print(f"[DEBUG] Sending Instagram message to: {url}")
    print(f"[DEBUG] Authorization header: Bearer {ACCESS_TOKEN[:10]}...")
    resp = requests.post(url, headers=headers, json=payload, timeout=20)
    try:
        resp.raise_for_status()
    except Exception:
        print("[DEBUG send_instagram_message]", resp.status_code, resp.text)
        raise
    return resp.json()

def reply_public_to_comment(comment_id: str, text: str) -> dict:
    """
    Public reply la comentariu folosind Facebook Graph API.
    POST /{ig-comment-id}/replies cu Facebook Page Access Token.
    """
    url = f"{GRAPH_BASE_FB}/{comment_id}/replies"
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}
    payload = {"message": text}
    print(f"[DEBUG] Sending public reply to: {url}")
    print(f"[DEBUG] Authorization header: Bearer {ACCESS_TOKEN[:10]}...")
    resp = requests.post(url, headers=headers, json=payload, timeout=20)
    try:
        resp.raise_for_status()
    except Exception:
        print("[DEBUG reply_public_to_comment]", resp.status_code, resp.text)
        # Instagram doesn't support public replies via API
        print(f"[INFO] Instagram public reply not supported for comment {comment_id}, continuing with private message only")
        return {"success": False, "reason": "Instagram public replies not supported"}
    return resp.json()

def send_private_reply_to_comment_ig(author_igsid: str, text: str) -> dict:
    """
    'Private reply' pentru **Instagram** = trimite DM către autorul comentariului.
    Folosește IGSID-ul autorului (îl primești din webhook-ul de comentarii: entry[..].changes[..].value.from.id).
    """
    return send_instagram_message(author_igsid, text)
