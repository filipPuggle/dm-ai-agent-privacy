import os
import requests

GRAPH_VERSION = "v23.0"
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_VERSION}"

ACCESS_TOKEN = (os.getenv("PAGE_ACCESS_TOKEN") or "").strip()
IG_ID = (os.getenv("IG_ID") or "").strip()

# Debug token format
print(f"[DEBUG] Token length: {len(ACCESS_TOKEN)}")
print(f"[DEBUG] Token starts with: {ACCESS_TOKEN[:10]}...")
print(f"[DEBUG] IG_ID: {IG_ID}")

if not ACCESS_TOKEN or not IG_ID:
    raise RuntimeError("Lipsește PAGE_ACCESS_TOKEN sau IG_ID (Instagram Business Account ID) în variabilele de mediu.")

def send_instagram_message(recipient_igsid: str, text: str) -> dict:
    """Trimite un DM către utilizatorul cu IGSID (Instagram Scoped User ID)."""
    url = f"{GRAPH_BASE}/{IG_ID}/messages"
    payload = {
        "recipient": {"id": str(recipient_igsid)},
        "message": {"text": text},
    }
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}
    print(f"[DEBUG] Sending request to: {url}")
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
    Public reply la comentariu **Instagram**: POST /{ig-comment-id}/replies
    (același endpoint există și pentru FB comments, dar aici folosește IG comment id).
    """
    url = f"{GRAPH_BASE}/{comment_id}/replies"
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}
    payload = {"message": text}
    resp = requests.post(url, headers=headers, json=payload, timeout=20)
    try:
        resp.raise_for_status()
    except Exception:
        print("[DEBUG reply_public_to_comment]", resp.status_code, resp.text)
        raise
    return resp.json()

def send_private_reply_to_comment_ig(author_igsid: str, text: str) -> dict:
    """
    'Private reply' pentru **Instagram** = trimite DM către autorul comentariului.
    Folosește IGSID-ul autorului (îl primești din webhook-ul de comentarii: entry[..].changes[..].value.from.id).
    """
    return send_instagram_message(author_igsid, text)
