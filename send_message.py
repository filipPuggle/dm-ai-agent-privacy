import os
import requests

INSTAGRAM_ACCESS_TOKEN = os.getenv("INSTAGRAM_ACCESS_TOKEN")

def send_instagram_message(recipient_id: str, message_text: str):
    """
    Trimite un mesaj text către recipient_id folosind Graph API.
    """
    url = f"https://graph.facebook.com/v15.0/me/messages"
    params = {"access_token": INSTAGRAM_ACCESS_TOKEN}
    payload = {
        "recipient": {"id": recipient_id},
        "message":   {"text": message_text}
    }
    resp = requests.post(url, params=params, json=payload)
    resp.raise_for_status()
    return resp.json()