import os
import hmac
import json
import hashlib
from flask import Flask, request, send_file
from send_message import send_instagram_message

app = Flask(__name__)

VERIFY_TOKEN = os.environ["WEBHOOK_VERIFY_TOKEN"]
APP_SECRET = os.getenv("WEBHOOK_SECRET") or os.getenv("FB_APP_SECRET")
GRAPH_API_VERSION = os.getenv("GRAPH_API_VERSION", "23.0")

@app.get("/health")
def health():
    return {"status": "ok", "graph_api_version": GRAPH_API_VERSION}, 200

@app.get("/")
def root():
    return "OK", 200

@app.get("/privacy_policy")
def privacy():
    # servește fișierul privacy_policy.html din rădăcina proiectului
    return send_file("privacy_policy.html")

@app.get("/webhook")
def verify_webhook():
    # Verificare inițială (hub challenge)
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge, 200
    return "Forbidden", 403

def _valid_signature() -> bool:
    """
    Verifică antetul X-Hub-Signature-256 cu APP_SECRET.
    Dacă nu avem secret setat, nu blocăm (returnăm True) pentru a evita 401.
    """
    if not APP_SECRET:
        return True
    header_sig = request.headers.get("X-Hub-Signature-256", "")
    if not header_sig.startswith("sha256="):
        return False
    expected = hmac.new(APP_SECRET.encode("utf-8"), request.data, hashlib.sha256).hexdigest()
    return hmac.compare_digest("sha256=" + expected, header_sig)

@app.post("/webhook")
def handle_webhook():
    if not _valid_signature():
        return "Invalid signature", 401

    data = request.get_json(force=True, silent=True) or {}
    print("📥 Webhook payload:", json.dumps(data, ensure_ascii=False))

    # Structura tipică IG Messaging: entry[*].messaging[*]
    for entry in data.get("entry", []):
        for event in entry.get("messaging", []):
            sender_id = (event.get("sender") or {}).get("id")
            msg = event.get("message") or {}
            text = (msg.get("text") or "").strip()
            if sender_id and text:
                # Răspuns simplu (eco). Poți înlocui cu logica ta/AI.
                reply = f"Am primit mesajul tău: {text}"
                try:
                    send_instagram_message(sender_id, reply)
                except Exception:
                    # nu blocăm livrarea webhook-ului dacă trimiterea eșuează
                    pass

    return "OK", 200

if __name__ == "__main__":
    port = int(os.getenv("PORT", "3000"))
    app.run(host="0.0.0.0", port=port)
