import requests
import json

def send_instagram_message(recipient_id, message_text, access_token=None):
    """
    Send a message to an Instagram user using the Instagram Graph API.
    
    Args:
        recipient_id (str): The Instagram-scoped ID of the recipient
        message_text (str): The message text to send
        access_token (str, optional): Instagram access token. If None, uses default token.
    
    Returns:
        dict: Response from the Instagram API
    """
    
    # Default access token if none provided
    if access_token is None:
        access_token = "IGAARxzZCIIdAFBZAE5IYmpYaThJY1FVcl94V3JzX2dhd0VtakE4YXR6ZAVJZAbjdJRWQ4UnRJYWs5cHA3VXFLaU5mTFhwQ2VldG9kZAUlPczFreVBkTHdfbDd1WTJRQUhzRVZARUTFvd0pnSXBPRnFmdXM0YmVqcTN5TXI3UWdFUHV6TQZDZD"
    
    # Instagram Business Account ID
    instagram_business_account_id = "17841444279395933"
    
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

