import os
import requests

# ===== Config =====
GRAPH_VERSION = os.getenv("GRAPH_VERSION", "v23.0").strip()
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_VERSION}"

# Tokenuri separate pentru operațiuni diferite
USER_TOKEN = (os.getenv("USER_ACCESS_TOKEN") or "").strip()   # pentru comentarii (IG Graph)
PAGE_TOKEN = (os.getenv("PAGE_ACCESS_TOKEN") or "").strip()   # pentru DM (Messenger/IG Messaging)

# (Opțional) ID-ul paginii Facebook conectate la IG (pentru /{PAGE_ID}/messages)
PAGE_ID = (os.getenv("PAGE_ID") or "").strip()

# Debug minimal (nu loga tokenul complet)
print(f"[DEBUG] GRAPH_VERSION={GRAPH_VERSION}")
print(f"[DEBUG] USER_TOKEN len={len(USER_TOKEN)}  PAGE_TOKEN len={len(PAGE_TOKEN)}  PAGE_ID={PAGE_ID or '-'}")

if not USER_TOKEN:
    raise RuntimeError("Lipsește USER_ACCESS_TOKEN în variabilele de mediu (necesar pentru /{ig-comment-id}/replies).")
if not PAGE_TOKEN:
    raise RuntimeError("Lipsește PAGE_ACCESS_TOKEN în variabilele de mediu (necesar pentru /{PAGE_ID}/messages).")

# ===== Public reply la comentariu (IG Graph API) =====
def reply_public_to_comment(ig_comment_id: str, text: str) -> dict:
    """
    Răspunde public pe firul comentariului.
    Endpoint: POST /{ig-comment-id}/replies
    Auth: USER_ACCESS_TOKEN (permisiune instagram_manage_comments).
    Docs: https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-comment/replies/
    """
    url = f"{GRAPH_BASE}/{ig_comment_id}/replies"
    # IG Graph acceptă tokenul ca parametru form-data/query
    data = {"message": text, "access_token": USER_TOKEN}
    print(f"[DEBUG] POST {url} (public reply)")
    resp = requests.post(url, data=data, timeout=20)
    try:
        resp.raise_for_status()
        print("[SUCCESS] Public reply trimis.")
        return {"success": True, "response": resp.json()}
    except Exception:
        print("[ERROR] Public reply eșuat:", resp.status_code, resp.text)
        return {"success": False, "error": resp.text, "status": resp.status_code}

# ===== Private Reply prin comment_id (Instagram Messaging) =====
def send_private_reply_via_comment(ig_comment_id: str, text: str, page_id: str | None = None) -> dict:
    """
    Trimite un DM de tip 'Private Reply' către autorul comentariului.
    * O singură dată per comentariu, în max. 7 zile de la comentariu.
    Endpoint: POST /{PAGE_ID}/messages  cu payload: {"recipient":{"comment_id": ...}, "message":{"text": ...}}
    Auth: PAGE_ACCESS_TOKEN (Bearer).
    Docs: https://developers.facebook.com/docs/instagram-platform/private-replies/
          https://developers.facebook.com/docs/messenger-platform/instagram/features/private-replies/
    """
    _page_id = page_id or PAGE_ID
    if not _page_id:
        return {"success": False, "error": "Lipsește PAGE_ID (env PAGE_ID sau parametrul page_id)."}

    url = f"{GRAPH_BASE}/{_page_id}/messages"
    payload = {"recipient": {"comment_id": str(ig_comment_id)}, "message": {"text": text}}
    headers = {"Authorization": f"Bearer {PAGE_TOKEN}"}

    print(f"[DEBUG] POST {url} (private reply) comment_id={ig_comment_id}")
    print(f"[DEBUG] Using PAGE_TOKEN: {PAGE_TOKEN[:10]}...")
    resp = requests.post(url, json=payload, headers=headers, timeout=20)
    try:
        resp.raise_for_status()
        print("[SUCCESS] Private Reply trimis.")
        return {"success": True, "response": resp.json()}
    except Exception:
        print("[ERROR] Private Reply eșuat:", resp.status_code, resp.text)
        return {"success": False, "error": resp.text, "status": resp.status_code}

# ===== Instagram Direct Messaging (vechiul approach care funcționa) =====
def send_instagram_message(recipient_igsid: str, text: str) -> dict:
    """
    Trimite un DM direct către utilizatorul cu IGSID folosind Instagram Graph API.
    Endpoint Instagram Login:
      POST https://graph.instagram.com/v23.0/{IG_ID}/messages
      Authorization: Bearer <IG user/system user token>
      Body: { "recipient": {"id": "<IGSID>"}, "message": {"text": "<text>"} }
    """
    # Folosește Instagram Graph API endpoint (vechiul approach)
    GRAPH_BASE_IG = f"https://graph.instagram.com/{GRAPH_VERSION}"
    url = f"{GRAPH_BASE_IG}/{PAGE_ID}/messages"
    payload = {
        "recipient": {"id": str(recipient_igsid)},
        "message": {"text": text},
    }
    headers = {"Authorization": f"Bearer {PAGE_TOKEN}"}
    print(f"[DEBUG] POST {url} (Instagram DM) recipient={recipient_igsid}")
    resp = requests.post(url, headers=headers, json=payload, timeout=20)
    try:
        resp.raise_for_status()
        print("[SUCCESS] Instagram DM trimis.")
        return {"success": True, "response": resp.json()}
    except Exception:
        print("[ERROR] Instagram DM eșuat:", resp.status_code, resp.text)
        return {"success": False, "error": resp.text, "status": resp.status_code}

def send_private_reply_to_comment_ig(ig_comment_id: str, text: str, page_id: str | None = None) -> dict:
    """
    Wrapper păstrat pentru compatibilitate cu numele folosit anterior.
    Intern apelează send_private_reply_via_comment(...).
    """
    return send_private_reply_via_comment(ig_comment_id=ig_comment_id, text=text, page_id=page_id)
