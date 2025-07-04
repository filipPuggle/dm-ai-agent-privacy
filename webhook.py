import os
import json
import hmac
import hashlib
import logging
from flask import Flask, request, abort, make_response, send_from_directory, jsonify
from dotenv import load_dotenv
load_dotenv()
from send_message import send_instagram_message

# Configure logger to show INFO-level messages
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create Flask app
app = Flask(__name__)
app.logger.setLevel(logging.INFO)

# Load environment variables
VERIFY_TOKEN = os.getenv("IG_VERIFY_TOKEN")
APP_SECRET = os.getenv("IG_APP_SECRET")
IG_PAGE_ACCESS_TOKEN = os.getenv("IG_PAGE_ACCESS_TOKEN")
INSTAGRAM_BUSINESS_ACCOUNT_ID = os.getenv("INSTAGRAM_BUSINESS_ACCOUNT_ID")
GRAPH_API_ACCESS_TOKEN = os.getenv("GRAPH_API_ACCESS_TOKEN")


def verify_signature(req):
    """
    Verify the HMAC SHA-256 signature sent by Instagram.
    In development (Meta UI tests), if APP_SECRET or signature header
    is missing, bypass the check.
    """
    signature = req.headers.get("X-Hub-Signature-256")
    if not APP_SECRET:
        app.logger.warning(
            "APP_SECRET not set; skipping signature verification (development bypass)."
        )
        return True
    if not signature:
        app.logger.warning(
            "No X-Hub-Signature-256 header; skipping signature verification (development bypass)."
        )
        return True

    expected = "sha256=" + hmac.new(
        APP_SECRET.encode(), req.data, hashlib.sha256
    ).hexdigest()
    valid = hmac.compare_digest(expected, signature)
    if not valid:
        app.logger.error("Invalid signature: expected %s but got %s", expected, signature)
    return valid


@app.route("/")
def hello_world():
    return "<p>Hello, World!</p>"


@app.route("/privacy_policy")
def privacy_policy():
    return send_from_directory(
        directory=".",
        filename="privacy_policy.html",
        mimetype="text/html"
    )


@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    if request.method == "GET":
        mode      = request.args.get("hub.mode")
        challenge = request.args.get("hub.challenge")
        token     = request.args.get("hub.verify_token")

        if mode == "subscribe" and VERIFY_TOKEN and token == VERIFY_TOKEN:
            return make_response(challenge, 200)

        app.logger.error("Webhook verification failed: invalid or missing verify_token.")
        return abort(403)

    # POST
    if not verify_signature(request):
        return abort(403)

    payload = request.get_json(force=True)
    app.logger.info("Instagram Webhook Payload:\n%s", json.dumps(payload, indent=2))

    # Process Instagram webhook payload
    # Based on: https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/messaging-api
    for entry in payload.get("entry", []):
        app.logger.info("Processing entry: %s", entry.get("id"))
        
        for messaging_event in entry.get("messaging", []):
            # Extract the Instagram-scoped ID (IGSID) of the sender
            sender_id = messaging_event.get("sender", {}).get("id")
            app.logger.info("Sender ID: %s", sender_id)
            
            # Send "Hello, World!" response to every message
            app.logger.info("Attempting to send response to user %s", sender_id)
            response = send_instagram_message(sender_id, "Hello, World!")
            
            if response:
                app.logger.info("API Response status: %s", response["status_code"])
                app.logger.info("API Response body: %s", response["response_text"])
            else:
                app.logger.error("Failed to send message - no response returned")

    return make_response("", 200)


@app.route("/instagram/callback")
def instagram_callback():
    """
    OAuth callback endpoint for Instagram Business login.
    Instagram will redirect here with ?code=<authorization_code>.
    """
    data = request.args.to_dict()
    app.logger.info("Instagram OAuth callback data: %s", data)
    return jsonify(data), 200



