# webhook.py
import os, hmac, hashlib, json, logging
from flask import Flask, request, jsonify, Response, send_file
from agency_setup import agency, attach_thread_callbacks, sales
from dotenv import load_dotenv
from agency_setup import agency, attach_thread_callbacks
from send_message import send_instagram_text

load_dotenv()
app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
log = app.logger

VERIFY_TOKEN = os.getenv("IG_VERIFY_TOKEN", "").strip()
APP_SECRET   = os.getenv("IG_APP_SECRET", "").strip()
FALLBACK     = os.getenv("DEFAULT_RESPONSE_MESSAGE", "Ne pare rău, a apărut o problemă. Încercați din nou.")

# --- Health & privacy ---------------------------------------------------------
@app.get("/health")
def health():
    return jsonify(ok=True)

@app.get("/privacy_policy")
def privacy():
    return send_file("privacy_policy.html")

# --- Webhook verify (GET) -----------------------------------------------------
@app.get("/webhook")
def webhook_verify():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        return Response(challenge, status=200)
    return Response("Forbidden", status=403)

# --- Validare semnătură Meta (X-Hub-Signature-256) ----------------------------
def _check_signature(req) -> bool:
    # Meta: sha256 HMAC(payload, APP_SECRET), comparat cu headerul X-Hub-Signature-256. :contentReference[oaicite:6]{index=6}
    if not APP_SECRET:
        log.warning("IG_APP_SECRET nedefinit - semnătura nu este verificată")
        return True
    received = req.headers.get("X-Hub-Signature-256", "")
    if not received.startswith("sha256="):
        return False
    digest = hmac.new(APP_SECRET.encode(), req.get_data(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(received[7:], digest)

# --- Extrage evenimentul IG (robust) -----------------------------------------
def _extract_ig_message(payload: dict):
    """
    Suportă formatele uzuale ale Messenger Platform for Instagram.
    Returnează (sender_id, text) sau (None, None).
    """
    try:
        for entry in payload.get("entry", []):
            for m in entry.get("messaging", []):
                sender = m.get("sender", {}).get("id")
                msg = m.get("message", {})
                text = msg.get("text")
                if sender and text:
                    return sender, text
    except Exception:
        pass
    try:
        for entry in payload.get("entry", []):
            for ch in entry.get("changes", []):
                val = ch.get("value", {})
                for item in val.get("messages", []):
                    sender = (item.get("from") or {}).get("id")
                    text = item.get("text")
                    if sender and text:
                        return sender, text
    except Exception:
        pass
    return None, None

# --- Webhook receive (POST) ---------------------------------------------------
@app.post("/webhook")
def webhook_receive():
    if not _check_signature(request):
        return Response("Invalid signature", status=403)

    payload = request.get_json(silent=True) or {}
    sender_id, text = _extract_ig_message(payload)
    if not sender_id or not text:
        log.info("Ignoring webhook: no text event")
        return jsonify(received=True)

    # 1) Persistență threads pe sender_id (memorie conversație între redeploy-uri)
    attach_thread_callbacks(sender_id)

    # 2) Răspuns de la Agency Swarm (entry point: Sales)
    try:
        reply = agency.get_completion(message=text, recipient_agent=sales)
    except Exception as e:
        log.exception("Agency error: %s", e)
        reply = FALLBACK

    # 3) Trimite DM înapoi pe Instagram
    try:
        send_instagram_text(sender_id, reply[:900])  # limită practică de lungime
    except Exception as e:
        log.exception("Instagram send error: %s", e)

    return jsonify(sent=True)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
