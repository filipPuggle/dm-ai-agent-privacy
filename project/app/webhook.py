import os
import json
import hmac
import hashlib
import logging
from typing import Dict, Iterable, Tuple

from flask import Flask, request, abort

from sendmessage import send_instagram_message
from ai_router import route_message

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# ===== envs (do NOT rename per user constraint) =====
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
VERIFY_TOKEN   = os.getenv("IG_VERIFY_TOKEN", "").strip()



# --- helpers ---

def _verify_signature() -> bool:
    """Optional: verify X-Hub-Signature-256 when IG_APP_SECRET is present."""
    if not APP_SECRET:
        return True  # in dev we don't verify
    sig = request.headers.get("X-Hub-Signature-256", "")
    if not sig.startswith("sha256="):
        return False
    digest = hmac.new(APP_SECRET.encode(), request.data, hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig[7:], digest)


def _iter_incoming_events(payload: Dict) -> Iterable[Tuple[str, Dict]]:
    """Extract (sender_id, message) tuples from IG webhook payload."""
    for entry in payload.get("entry", []):
        # Messenger-style
        for item in entry.get("messaging", []) or []:
            sender_id = (item.get("sender") or {}).get("id")
            msg = item.get("message") or {}
            if sender_id and isinstance(msg, dict):
                yield sender_id, msg

        # Instagram Graph "changes" style
        for ch in entry.get("changes", []) or []:
            val = ch.get("value") or {}
            for msg in val.get("messages", []) or []:
                if not isinstance(msg, dict):
                    continue
                from_field = msg.get("from") or val.get("from") or {}
                sender_id = from_field.get("id") if isinstance(from_field, dict) else from_field
                if sender_id:
                    yield sender_id, msg


# --- routes ---

@app.get("/health")
def health():
    return {"ok": True}, 200


@app.get("/webhook")
def verify():
    """Verification callback for IG webhook subscription."""
    mode      = request.args.get("hub.mode")
    token     = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token and token == VERIFY_TOKEN:
        return challenge, 200
    return "Forbidden", 403


@app.post("/webhook")
def webhook():
    try:
        if not _verify_signature():
            app.logger.error("Invalid X-Hub-Signature-256")
            abort(403)

        data = request.get_json(force=True, silent=True) or {}
        app.logger.info("Incoming webhook: %s", json.dumps(data, ensure_ascii=False))

        for sender_id, msg in _iter_incoming_events(data):
            if msg.get("is_echo"):  # ignore echoes
                continue

            text_in = (msg.get("text") or "").strip()
            if not text_in:
                continue

            try:
                result = route_message(sender_id, text_in)
                if result:
                    send_instagram_message(sender_id, result[:900])
            except Exception as e:
                app.logger.exception("Message handling failed: %s", e)

        return "OK", 200
    except Exception as e:
        app.logger.exception("Webhook handler failed: %s", e)
        return "Internal Server Error", 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8080")), debug=False)
