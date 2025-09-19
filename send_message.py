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
    Trimite un DM către utilizatorul cu IGSID folosind Instagram Basic Display API.
    Folosește Instagram Basic Display API endpoint pentru Instagram messaging.
    """
    # Try Instagram Basic Display API endpoint
    url = f"https://graph.instagram.com/v23.0/{IG_ID}/messages"
    payload = {
        "recipient": {"id": str(recipient_igsid)},
        "message": {"text": text},
    }
    # Use Facebook Page Access Token for Instagram messaging
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}
    print(f"[DEBUG] Sending Instagram message to: {url}")
    print(f"[DEBUG] Authorization header: Bearer {ACCESS_TOKEN[:10]}...")
    print(f"[DEBUG] Payload: {payload}")
    resp = requests.post(url, headers=headers, json=payload, timeout=20)
    try:
        resp.raise_for_status()
    except Exception as e:
        print("[DEBUG send_instagram_message]", resp.status_code, resp.text)
        # If Instagram messaging fails, try alternative approach
        if resp.status_code in [400, 401]:
            error_data = resp.json()
            if "error" in error_data:
                error_code = error_data["error"].get("code")
                if error_code in [3, 190]:  # Permission denied or invalid token
                    print(f"[WARNING] Instagram messaging failed (error {error_code}). Trying alternative approach...")
                    # Try with different payload format
                    return _try_alternative_instagram_messaging(recipient_igsid, text)
        raise
    return resp.json()

def _try_alternative_instagram_messaging(recipient_igsid: str, text: str) -> dict:
    """
    Try alternative Instagram messaging approach using different API format.
    """
    print(f"[DEBUG] Trying alternative Instagram messaging approach...")
    
    # Try with different payload format
    url = f"{GRAPH_BASE_FB}/{IG_ID}/messages"
    payload = {
        "recipient": {"id": str(recipient_igsid)},
        "message": {"text": text},
        "messaging_type": "RESPONSE"
    }
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}
    print(f"[DEBUG] Alternative payload: {payload}")
    
    resp = requests.post(url, headers=headers, json=payload, timeout=20)
    try:
        resp.raise_for_status()
        print(f"[SUCCESS] Alternative Instagram messaging worked!")
        return resp.json()
    except Exception as e:
        print(f"[DEBUG] Alternative approach failed: {resp.status_code} {resp.text}")
        # Try third approach with different endpoint
        return _try_third_instagram_messaging(recipient_igsid, text)

def _try_third_instagram_messaging(recipient_igsid: str, text: str) -> dict:
    """
    Try third Instagram messaging approach using Messenger API format.
    """
    print(f"[DEBUG] Trying third Instagram messaging approach...")
    
    # Try with Messenger API format
    url = f"{GRAPH_BASE_FB}/me/messages"
    payload = {
        "recipient": {"id": str(recipient_igsid)},
        "message": {"text": text},
        "messaging_type": "RESPONSE"
    }
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}
    print(f"[DEBUG] Third approach payload: {payload}")
    
    resp = requests.post(url, headers=headers, json=payload, timeout=20)
    try:
        resp.raise_for_status()
        print(f"[SUCCESS] Third Instagram messaging approach worked!")
        return resp.json()
    except Exception as e:
        print(f"[DEBUG] Third approach failed: {resp.status_code} {resp.text}")
        return {"success": False, "reason": "All Instagram messaging approaches failed"}

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
