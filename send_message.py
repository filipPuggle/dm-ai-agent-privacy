# send_message.py — IG DM via Graph API; suportă INSTAGRAM_* și PAGE_*; verifică tipul tokenului

import os
import requests
import logging

log = logging.getLogger("send_message")

GRAPH_API_VERSION = (os.getenv("GRAPH_API_VERSION") or "v23.0").strip()

# Acceptă ambele stiluri de variabile:
IG_BUSINESS_ID = (
    os.getenv("INSTAGRAM_BUSINESS_ACCOUNT_ID")
    or os.getenv("PAGE_ID")
    or ""
).strip()

ACCESS_TOKEN = (
    os.getenv("GRAPH_API_ACCESS_TOKEN")
    or os.getenv("INSTAGRAM_ACCESS_TOKEN")
    or os.getenv("PAGE_ACCESS_TOKEN")
    or ""
).strip()

API_BASE = f"https://graph.facebook.com/{GRAPH_API_VERSION}"


def _token_kind(tok: str) -> str:
    if not tok:
        return "none"
    if tok.startswith("EAAG"):
        return "page(EAAG)"
    if tok.startswith("EAA"):
        return "page(EAA)"
    if tok.startswith("IG"):
        return "instagram(IG..)"
    return "unknown"


def _post_json(url: str, payload: dict) -> dict:
    r = requests.post(url, params={"access_token": ACCESS_TOKEN}, json=payload, timeout=20)
    if not r.ok:
        logging.error("❌ Instagram send error: %s %s", r.status_code, r.text)
        r.raise_for_status()
    logging.info("✅ IG send ok: %s", r.text)
    return r.json()


def send_text(recipient_id: str, text: str) -> dict:
    """
    POST /{IG_USER_ID}/messages cu Page Access Token (EAA/EAAG).
    NOTĂ: pe Instagram NU folosim `messaging_type`.
    """
    if not IG_BUSINESS_ID:
        raise RuntimeError("Missing IG business id. Set INSTAGRAM_BUSINESS_ACCOUNT_ID sau PAGE_ID.")
    if not ACCESS_TOKEN:
        raise RuntimeError("Missing token. Set GRAPH_API_ACCESS_TOKEN/INSTAGRAM_ACCESS_TOKEN sau PAGE_ACCESS_TOKEN.")

    kind = _token_kind(ACCESS_TOKEN)
    logging.info("Sending IG DM using token=%s", kind)
    if kind.startswith("instagram("):
        # Explicăm de ce nu va merge (dar lăsăm și Graph să confirme cu 190 dacă vrei)
        raise RuntimeError(
            "Tokenul din env este de tip Instagram (IG…). Pentru DM este necesar un **Page Access Token** "
            "(de obicei începe cu EAA/EAAG). Pune-l în PAGE_ACCESS_TOKEN sau GRAPH_API_ACCESS_TOKEN."
        )

    url = f"{API_BASE}/{IG_BUSINESS_ID}/messages"
    payload = {"recipient": {"id": recipient_id}, "message": {"text": text}}
    return _post_json(url, payload)
