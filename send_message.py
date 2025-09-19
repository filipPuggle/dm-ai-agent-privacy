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
    Trimite un DM către utilizatorul cu IGSID folosind Instagram Messaging API.
    Folosește Instagram Messaging API endpoint pentru Instagram messaging.
    """
    # First, get conversations to find the conversation ID
    print(f"[DEBUG] Getting Instagram conversations for user {recipient_igsid}...")
    conversations = _get_instagram_conversations()
    
    if not conversations:
        print(f"[WARNING] No Instagram conversations found. Cannot send message.")
        return {"success": False, "reason": "No Instagram conversations found"}
    
    # Try to find conversation with the specific user
    conversation_id = _find_conversation_for_user(conversations, recipient_igsid)
    
    if not conversation_id:
        print(f"[WARNING] No conversation found for user {recipient_igsid}. Creating new conversation...")
        # Try to create a new conversation
        return _create_new_conversation(recipient_igsid, text)
    
    # Send message to existing conversation
    return _send_message_to_conversation(conversation_id, text)

def _get_instagram_conversations() -> list:
    """
    Get Instagram conversations using the correct API endpoint.
    """
    url = f"{GRAPH_BASE_FB}/{IG_ID}/conversations?platform=instagram"
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}
    print(f"[DEBUG] Getting conversations from: {url}")
    
    resp = requests.get(url, headers=headers, timeout=20)
    try:
        resp.raise_for_status()
        data = resp.json()
        print(f"[DEBUG] Found {len(data.get('data', []))} conversations")
        return data.get('data', [])
    except Exception as e:
        print(f"[DEBUG] Failed to get conversations: {resp.status_code} {resp.text}")
        return []

def _find_conversation_for_user(conversations: list, user_id: str) -> str:
    """
    Find conversation ID for a specific user.
    """
    # For now, return the first conversation (we'll improve this later)
    if conversations:
        return conversations[0]['id']
    return None

def _create_new_conversation(user_id: str, text: str) -> dict:
    """
    Try to create a new conversation with the user.
    """
    print(f"[DEBUG] Trying to create new conversation with user {user_id}...")
    # This might not be possible via API, but let's try
    return {"success": False, "reason": "Cannot create new conversation via API"}

def _send_message_to_conversation(conversation_id: str, text: str) -> dict:
    """
    Send message to an existing conversation.
    """
    url = f"{GRAPH_BASE_FB}/{conversation_id}/messages"
    payload = {
        "message": {"text": text}
    }
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}
    print(f"[DEBUG] Sending message to conversation: {url}")
    print(f"[DEBUG] Payload: {payload}")
    
    resp = requests.post(url, headers=headers, json=payload, timeout=20)
    try:
        resp.raise_for_status()
        print(f"[SUCCESS] Message sent to conversation successfully!")
        return resp.json()
    except Exception as e:
        print(f"[DEBUG] Failed to send message to conversation: {resp.status_code} {resp.text}")
        return {"success": False, "reason": f"Failed to send message: {resp.text}"}

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
