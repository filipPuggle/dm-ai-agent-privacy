import os
import requests

def exchange_facebook_token():
    """
    Exchanges a short-lived Facebook user token for a long-lived token.
    Returns the new access token string, or None if failed.
    """
    FB_APP_ID = os.getenv("FB_APP_ID")
    FB_APP_SECRET = os.getenv("FB_APP_SECRET")
    FB_USER_TOKEN = os.getenv("FB_USER_TOKEN")  # This should be a short-lived user token

    if not (FB_APP_ID and FB_APP_SECRET and FB_USER_TOKEN):
        raise Exception("FB_APP_ID, FB_APP_SECRET, and FB_USER_TOKEN must be set in environment variables.")

    url = "https://graph.facebook.com/v17.0/oauth/access_token"
    params = {
        "grant_type": "fb_exchange_token",
        "client_id": FB_APP_ID,
        "client_secret": FB_APP_SECRET,
        "fb_exchange_token": FB_USER_TOKEN
    }

    response = requests.get(url, params=params)
    if response.status_code == 200:
        data = response.json()
        return data.get("access_token")
    else:
        print("Failed to exchange token:", response.text)
        return None 
    