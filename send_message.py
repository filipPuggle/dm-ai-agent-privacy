import requests
import json
import os

def send_instagram_message(recipient_id, message_text, access_token=None):
    """
    Send a message to an Instagram user using the Instagram Graph API.
    
    Args:
        recipient_id (str): The Instagram-scoped ID of the recipient
        message_text (str): The message text to send
        access_token (str, optional): Instagram access token. If None, uses environment variable.
    
    Returns:
        dict: Response from the Instagram API
    """
    
    # Default access token from environment if none provided
    if access_token is None:
        access_token = os.getenv("INSTAGRAM_ACCESS_TOKEN")
        if not access_token:
            return {
                "status_code": None,
                "response_text": "INSTAGRAM_ACCESS_TOKEN not set in environment",
                "success": False
            }
    
    # Instagram Business Account ID from environment
    instagram_business_account_id = os.getenv("INSTAGRAM_BUSINESS_ACCOUNT_ID")
    if not instagram_business_account_id:
        return {
            "status_code": None,
            "response_text": "INSTAGRAM_BUSINESS_ACCOUNT_ID not set in environment",
            "success": False
        }
    
    url = f"https://graph.instagram.com/v23.0/{instagram_business_account_id}/messages"
    
    payload = json.dumps({
        "recipient": {
            "id": recipient_id
        },
        "message": {
            "text": message_text
        }
    })
    
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json'
    }
    
    try:
        response = requests.post(url, headers=headers, data=payload)
        return {
            "status_code": response.status_code,
            "response_text": response.text,
            "success": response.status_code == 200
        }
    except Exception as e:
        return {
            "status_code": None,
            "response_text": str(e),
            "success": False
        }

