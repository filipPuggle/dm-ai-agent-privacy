import requests
import os

def send_instagram_message(recipient_id: str, message_text: str, access_token: str = None) -> dict:
    """
    Send a DM to an Instagram user via Instagram Graph API (Facebook Graph endpoint).
    """
    # 1) Prind tokenul din ENV dacă nu e dat ca argument
    if access_token is None:
        access_token = os.getenv("INSTAGRAM_ACCESS_TOKEN")
        if not access_token:
            return {
                "status_code": None,
                "response_text": "INSTAGRAM_ACCESS_TOKEN not set in environment",
                "success": False
            }

    # 2) Prind IG Business Account ID
    ig_account_id = os.getenv("INSTAGRAM_BUSINESS_ACCOUNT_ID")
    if not ig_account_id:
        return {
            "status_code": None,
            "response_text": "INSTAGRAM_BUSINESS_ACCOUNT_ID not set in environment",
            "success": False
        }

    # 3) Construiesc URL-ul corect pentru Graph API v16.0
    url = f"https://graph.facebook.com/v16.0/{ig_account_id}/messages"

    # 4) Payload JSON
    payload = {
        "recipient": {"id": recipient_id},
        "message":   {"text": message_text}
    }

    # 5) Tokenul în query params
    params = {"access_token": access_token}

    # 6) Trimitem
    try:
        resp = requests.post(url, params=params, json=payload, timeout=5)
    except Exception as e:
        return {
            "status_code": None,
            "response_text": f"Request exception: {e}",
            "success": False
        }

    # 7) Returnez cod + text pentru debugging
    result = {
        "status_code": resp.status_code,
        "response_text": resp.text,
        "success": resp.status_code == 200
    }
    print(f"📤 IG send → {resp.status_code}\n{resp.text}")
    return result

