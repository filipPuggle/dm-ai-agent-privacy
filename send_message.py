from __future__ import annotations
import os
import logging
import requests
from typing import Tuple

log = logging.getLogger(__name__)

API_BASE = "https://graph.facebook.com/v23.0"
TEXT_LIMIT = 900  # practic: eviți erori pe texte foarte lungi

def _pick_env(*names: str) -> Tuple[str, str]:
    """
    Returnează (valoare, nume_folosit) pentru primul env var ne-gol din 'names'.
    Dacă nu există, întoarce ("", "").
    """
    for n in names:
        v = os.getenv(n, "").strip()
        if v:
            return v, n
    return "", ""

def _get_token() -> Tuple[str, str]:
    # Acceptă toate variantele folosite de tine până acum (fără a schimba .env)
    return _pick_env(
        "IG_PAGE_ACCESS_TOKEN",      # preferat în proiectul tău
        "PAGE_ACCESS_TOKEN",         # fallback clasic PAT
        "GRAPH_API_ACCESS_TOKEN",    # fallback
        "INSTAGRAM_ACCESS_TOKEN"     # fallback
    )

def _get_ig_business_id() -> Tuple[str, str]:
    # Acceptă denumiri uzuale pentru ID-ul contului Instagram profesional (IG User)
    return _pick_env(
        "INSTAGRAM_BUSINESS_ACCOUNT_ID",  # preferat
        "IG_BUSINESS_ID",                 # fallback
        "IG_ID",                          # fallback uzual
        "PAGE_ID"                         # în unele setup-uri a fost stocat astfel
    )

def is_configured() -> bool:
    token, _ = _get_token()
    ig_id, _ = _get_ig_business_id()
    return bool(token and ig_id)

def send_instagram_text(recipient_igsid: str, text: str) -> dict:
    """
    Trimite un mesaj text în conversația cu utilizatorul Instagram (message-scoped id).
    `recipient_igsid` = ID-ul primit în webhook la `sender.id`.

    Ridică RuntimeError dacă lipsesc configurările, sau requests.HTTPError pe 4xx/5xx.
    """
    token, token_var = _get_token()
    ig_id, ig_var = _get_ig_business_id()

    if not token or not ig_id:
        # Logăm DOAR numele variabilelor lipsă, nu și valorile.
        missing = []
        if not token:
            missing.append("IG_PAGE_ACCESS_TOKEN/PAGE_ACCESS_TOKEN/GRAPH_API_ACCESS_TOKEN/INSTAGRAM_ACCESS_TOKEN")
        if not ig_id:
            missing.append("INSTAGRAM_BUSINESS_ACCOUNT_ID/IG_BUSINESS_ID/IG_ID/PAGE_ID")
        raise RuntimeError(f"Config lipsă: {' și '.join(missing)}")

    if not recipient_igsid:
        raise ValueError("recipient_igsid este gol")

    # Trunchiem textul la o limită sigură.
    safe_text = (text or "").strip()
    if not safe_text:
        safe_text = "..."  # fallback minim
    if len(safe_text) > TEXT_LIMIT:
        safe_text = safe_text[:TEXT_LIMIT]

    url = f"{API_BASE}/{ig_id}/messages"
    payload = {
        "messaging_product": "instagram",
        "recipient": {"id": recipient_igsid},
        "message": {"text": safe_text},
    }
    headers = {"Authorization": f"Bearer {token}"}

    # Logare minimală pentru troubleshooting (fără secrete)
    log.info(
        "IG DM -> POST %s  [vars: token=%s, ig_id=%s]",
        url, token_var or "N/A", ig_var or "N/A"
    )

    r = requests.post(url, json=payload, headers=headers, timeout=20)
    try:
        r.raise_for_status()
    except Exception:
        # Logăm codul și răspunsul brut pentru debugging.
        log.error("Instagram send error: %s %s", r.status_code, r.text)
        raise
    return r.json()
