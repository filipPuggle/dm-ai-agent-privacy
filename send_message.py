import os
import requests

INSTAGRAM_ACCESS_TOKEN         = os.getenv("INSTAGRAM_ACCESS_TOKEN")
INSTAGRAM_BUSINESS_ACCOUNT_ID = os.getenv("INSTAGRAM_BUSINESS_ACCOUNT_ID")

def send_instagram_message(recipient_id: str, message_text: str):
    """
    Send a text DM via the Instagram Graph API.
    """
    url = f"https://graph.facebook.com/v15.0/{INSTAGRAM_BUSINESS_ACCOUNT_ID}/messages"
    params = {"access_token": INSTAGRAM_ACCESS_TOKEN}
    payload = {
        "messaging_product": "instagram",
        "recipient": {"id": recipient_id},
        "message":   {"text": message_text}
    }
    resp = requests.post(url, params=params, json=payload)
    resp.raise_for_status()
    return resp.json()
