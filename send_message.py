import os
import requests

GRAPH_API_VERSION = os.getenv("GRAPH_API_VERSION", "23.0")
PAGE_ACCESS_TOKEN = os.environ["PAGE_ACCESS_TOKEN"]
IG_BUSINESS_ACCOUNT_ID = os.environ["IG_BUSINESS_ACCOUNT_ID"]

def send_instagram_message(user_id: str, text: str):
    """
    Trimite un mesaj DM pe Instagram către user_id (PSID) folosind
    endpointul: POST /v{version}/{ig-user-id}/messages
    """
    url = f"https://graph.facebook.com/v{GRAPH_API_VERSION}/{IG_BUSINESS_ACCOUNT_ID}/messages"
    payload = {
        "messaging_type": "RESPONSE",
        "recipient": {"id": user_id},
        "message": {"text": text},
    }
    params = {"access_token": PAGE_ACCESS_TOKEN}

    r = requests.post(url, json=payload, params=params, timeout=20)
    try:
        r.raise_for_status()
    except requests.HTTPError as e:
        print(f"❌ Instagram send error: {e} | {r.text}")
        raise
    return r.json()
