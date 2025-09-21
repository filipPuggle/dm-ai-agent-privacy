import os
import requests

# ===== Config comun =====
GRAPH_VERSION = (os.getenv("GRAPH_VERSION") or "v23.0").strip()

IG_GRAPH_BASE = f"https://graph.instagram.com/{GRAPH_VERSION}"  # pentru DM (Instagram Graph)
FB_GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_VERSION}"   # pentru replies la comentarii (Facebook Graph)


def send_instagram_message(recipient_igsid: str, text: str) -> dict:
    """
    Trimite un DM către un utilizator Instagram (IGSID) via Instagram Graph API.
    Endpoint:
      POST https://graph.instagram.com/{VERSION}/{IG_ID}/messages
    Auth:
      Authorization: Bearer <PAGE_ACCESS_TOKEN> (token de pagină sau system-user cu permisiuni IG Messaging)
    Body (JSON):
      { "recipient": {"id": "<IGSID>"}, "message": {"text": "<text>"} }
    Env necesare:
      - PAGE_ACCESS_TOKEN
      - IG_ID (fallback: PAGE_ID)
    """
    access_token = (os.getenv("PAGE_ACCESS_TOKEN") or "").strip()
    ig_id = (os.getenv("IG_ID") or os.getenv("PAGE_ID") or "").strip()

    if not access_token or not ig_id:
        raise RuntimeError(
            "Pentru send_instagram_message lipsesc env: PAGE_ACCESS_TOKEN și/sau IG_ID/PAGE_ID."
        )

    url = f"{IG_GRAPH_BASE}/{ig_id}/messages"
    headers = {"Authorization": f"Bearer {access_token}"}
    payload = {
        "recipient": {"id": str(recipient_igsid)},
        "message": {"text": text},
    }

    resp = requests.post(url, headers=headers, json=payload, timeout=20)
    resp.raise_for_status()
    return resp.json()


def reply_public_to_comment(ig_comment_id: str, text: str) -> dict:
    """
    Răspunde PUBLIC pe firul unui comentariu Instagram via Facebook Graph API.
    Endpoint:
      POST https://graph.facebook.com/{VERSION}/{ig-comment-id}/replies
    Auth:
      access_token=<USER_ACCESS_TOKEN> (query/form) — necesită instagram_manage_comments
    Body (form):
      message=<text>&access_token=<USER_ACCESS_TOKEN>
    Env necesare:
      - USER_ACCESS_TOKEN
    Return:
      { "success": True/False, "response"/"error", ... }
    Docs:
      https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-comment/replies/
    """
    user_token = (os.getenv("USER_ACCESS_TOKEN") or "").strip()
    if not user_token:
        return {"success": False, "error": "Lipsește USER_ACCESS_TOKEN în variabilele de mediu."}

    url = f"{FB_GRAPH_BASE}/{ig_comment_id}/replies"
    data = {"message": text, "access_token": user_token}

    try:
        resp = requests.post(url, data=data, timeout=20)
        resp.raise_for_status()
        return {"success": True, "response": resp.json()}
    except Exception:
        status = getattr(resp, "status_code", None)
        body = getattr(resp, "text", "")
        return {"success": False, "status": status, "error": body}
