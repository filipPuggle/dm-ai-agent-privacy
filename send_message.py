import os
import json
import logging
from typing import Optional

import requests

GRAPH_VERSION = os.getenv("GRAPH_VERSION", "v23.0")
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_VERSION}"

logger = logging.getLogger(__name__)


def send_instagram_message(page_id: str, page_access_token: str, recipient_igsid: str, text: str) -> bool:
    """
    Trimite un mesaj text pe Instagram către utilizatorul cu IGSID (id-ul din webhook: sender.id)
    folosind endpoint-ul Messenger Platform for Instagram: /{PAGE_ID}/messages
    """
    url = f"{GRAPH_BASE}/{page_id}/messages"
    headers = {"Content-Type": "application/json"}
    payload = {
        "recipient": {"id": recipient_igsid},
        "message": {"text": text},
    }
    params = {"access_token": page_access_token}

    try:
        resp = requests.post(url, headers=headers, params=params, data=json.dumps(payload), timeout=20)
        if resp.status_code >= 400:
            logger.error("❌ Instagram send error [%s]: %s", resp.status_code, resp.text)
            return False
        logger.info("✅ Sent DM to %s", recipient_igsid)
        return True
    except requests.RequestException as e:
        logger.exception("❌ Request to IG failed: %s", e)
        return False