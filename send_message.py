# send_message.py
import os
import requests
from dotenv import load_dotenv

load_dotenv()

PAGE_ID          = os.getenv("PAGE_ID")
IG_ACCESS_TOKEN  = os.getenv("IG_ACCESS_TOKEN")

def send_instagram_message(recipient_id: str, message_text: str):
    """
    Send a text DM via the Instagram Graph API.
    """
    url = f"https://graph.facebook.com/v15.0/{PAGE_ID}/messages"
    params = {"access_token": IG_ACCESS_TOKEN}
    payload = {
        "messaging_product": "instagram",
        "recipient": {"id": recipient_id},
        "message":   {"text": message_text}
    }
    resp = requests.post(url, params=params, json=payload)
    resp.raise_for_status()
    return resp.json()
