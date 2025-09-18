import os
import requests

GRAPH_VERSION = "v23.0"
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_VERSION}"

ACCESS_TOKEN = (os.getenv("PAGE_ACCESS_TOKEN") or "").strip()

# OBLIGATORIU: IG_ID trebuie să fie Instagram Business Account ID (1784...)
IG_ID = (os.getenv("IG_ID") or "").strip()

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
    resp = requests.post(url, headers=headers, json=payload, timeout=20)
    try:
        resp.raise_for_status()
    except Exception as e:
        print("[DEBUG send_instagram_message]", resp.status_code, resp.text)
        # Check for specific permission errors
        if resp.status_code == 400:
            error_data = resp.json()
            if "error" in error_data:
                error_code = error_data["error"].get("code")
                if error_code == 3:  # OAuthException - permission issue
                    print(f"[ERROR] Instagram messaging permission denied. Check your app permissions.")
                    print(f"[ERROR] Make sure your app has 'instagram_basic' and 'instagram_manage_messages' permissions.")
                elif error_code == 100:  # GraphMethodException
                    print(f"[ERROR] Instagram API method not supported or object not found.")
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
        # Instagram doesn't support public replies to comments via API
        # We'll just log this and continue with private message
        print(f"[INFO] Instagram public reply not supported for comment {comment_id}, continuing with private message only")
        return {"success": False, "reason": "Instagram public replies not supported"}
    return resp.json()

def send_private_reply_to_comment_ig(author_igsid: str, text: str) -> dict:
    """
    'Private reply' pentru **Instagram** = trimite DM către autorul comentariului.
    Folosește IGSID-ul autorului (îl primești din webhook-ul de comentarii: entry[..].changes[..].value.from.id).
    """
    return send_instagram_message(author_igsid, text)

# (OPȚIONAL) DOAR dacă vrei și suport pt. Facebook Page comments:
def send_private_reply_to_comment_fb(comment_id: str, text: str) -> dict:
    """
    Private reply pentru **Facebook Page comment** (NU Instagram).
    POST /me/messages cu recipient.comment_id
    """
    url = f"{GRAPH_BASE}/me/messages"
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "recipient": {"comment_id": str(comment_id)},
        "message": {"text": text}
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=20)
    try:
        resp.raise_for_status()
    except Exception:
        print("[DEBUG send_private_reply_to_comment_fb]", resp.status_code, resp.text)
        raise
    return resp.json()
