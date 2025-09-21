import os
import json
import time
import hmac
import hashlib
import logging
import re
from typing import Dict, Iterable, Tuple
from flask import Flask, request, abort, jsonify

# === Importurile tale existente pentru trimitere mesaje/replies ===
from send_message import (
    send_instagram_message,           # DM to user_id
    reply_public_to_comment,          # public ack under comment (dacă platforma permite)
    send_private_reply_to_comment_ig  # Instagram Private Reply to a comment
)

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# === ENV (exact ca în Railway) ===
VERIFY_TOKEN = os.getenv("IG_VERIFY_TOKEN", "").strip()
APP_SECRET   = os.getenv("IG_APP_SECRET", "").strip()  # opțional, pentru semnătură
MY_IG_USER_ID = os.getenv("IG_ID", "").strip()

# === Dedup DM (MID) — 5 minute ===
SEEN_MIDS: Dict[str, float] = {}
DEDUP_TTL_SEC = 300

# === Anti-spam ofertă (o singură replică per user într-un interval) ===
OFFER_COOLDOWN_SEC = int(os.getenv("OFFER_COOLDOWN_SEC", "180"))  # default 3 min
LAST_OFFER_AT: Dict[str, float] = {}  # sender_id -> epoch

# === Dedup comentarii — 1 oră ===
PROCESSED_COMMENTS: Dict[str, float] = {}
COMMENT_TTL = 3600  # 1 oră în secunde

# === Texte ofertă ===
OFFER_TEXT_RO = (
    "Bună ziua 👋\n\n"
    "Avem modele pentru profesori, personalizabile cu text, care sunt la preț de 650 lei\n\n"
    "Facem și lucrări la comandă în baza pozei, la preț de 780 lei\n\n"
    "Lămpile au 16 culori și o telecomandă în set 🥰\n\n"
    "Primiți 6 luni garanție la toată electronica⚡\n\n"
    "Pentru ce tip de lampă ați opta ?"
)
OFFER_TEXT_RU = (
    "Здравствуйте 👋\n\n"
    "У нас есть модели для учителей, которые можно персонализировать с текстом, которые стоят 650 лей\n\n"
    "Также выполняем работы на заказ по фотографии, стоимость — 780 лей\n\n"
    "Лампы имеют 16 цветов и пульт в комплекте 🥰\n\n"
    "Вы получаете 6 месяцев гарантии на всю электронику⚡\n\n"
    "Какой тип лампы вы бы выбрали?"
)

# === Mesaj public scurt sub comentariu ===
ACK_PUBLIC_RO = "Bună 👋 V-am răspuns în privat 💌"
ACK_PUBLIC_RU = "Здравствуйте 👋\nОтветили в личные сообщения 💌"

# === Detectare limbă / trigger intent cumpărare ===
CYRILLIC_RE = re.compile(r"[\u0400-\u04FF]")

RO_PATTERNS = [
    r"\bpre[țt]?\b", r"\bpret(ul|uri)?\b", r"\bpre[țt]ul\b",
    r"\bc(â|î)?t(?:\s+cost[ăa]|e)\b", r"\bcost(ă|a)\b", r"\btarif\b", r"\bofert[ăa]\b",
    r"\bdetalii\b", r"\bmai multe detalii\b",
    r"\bmodele\b", r"\bmodele\s+(pentru|pt)\s+profesor[i]?\b",
    r"\bcatalog\b", r"\blamp[ăa]?(?:\s+profesori)?\b", r"\blampi\b",
    r"\bcomand[ăa]\b", r"\bvreau\s+(s[ăa]\s+)?cump[ăa]r\b",
]
RU_PATTERNS = [
    r"\bцен[аи]\b", r"\bсколько\s+стоит\b", r"\bстоимост[ьи]\b", r"\bпрайс\b",
    r"\bподробн(ее|ости)\b", r"\bкаталог\b", r"\bмодел(ь|и)\b", r"\bламп(а|ы)\b",
    r"\bдля\s+учител(я|ей)\b", r"\bподарок\s+учител(ю|ю)\b",
    r"\bзаказ\b", r"\bхочу\s+купить\b",
]
RO_REGEX = re.compile("|".join(RO_PATTERNS), re.IGNORECASE)
RU_REGEX = re.compile("|".join(RU_PATTERNS), re.IGNORECASE)

# ---------- Helpers comune ----------
def _verify_signature() -> bool:
    """Verifică X-Hub-Signature-256 dacă APP_SECRET e setat."""
    if not APP_SECRET:
        return True
    sig = request.headers.get("X-Hub-Signature-256", "")
    if not sig.startswith("sha256="):
        return False
    digest = hmac.new(APP_SECRET.encode(), request.data, hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig[7:], digest)

def _is_duplicate_mid(mid: str) -> bool:
    """Dedup DM după MID (5 min)."""
    now = time.time()
    last = SEEN_MIDS.get(mid, 0.0)
    if now - last < DEDUP_TTL_SEC:
        return True
    SEEN_MIDS[mid] = now
    # curățare ocazională
    for k, ts in list(SEEN_MIDS.items()):
        if now - ts > DEDUP_TTL_SEC:
            SEEN_MIDS.pop(k, None)
    return False

def _should_send_offer(sender_id: str) -> bool:
    """Anti-spam: o singură ofertă per user într-un interval."""
    now = time.time()
    last = LAST_OFFER_AT.get(sender_id, 0.0)
    if now - last < OFFER_COOLDOWN_SEC:
        return False
    LAST_OFFER_AT[sender_id] = now
    return True

def _detect_offer_lang(text: str) -> str | None:
    """'RU' / 'RO' dacă textul sugerează intenție de cumpărare; altfel None."""
    if not text:
        return None
    if CYRILLIC_RE.search(text):
        return "RU" if RU_REGEX.search(text) or True else None
    if RO_REGEX.search(text):
        return "RO"
    if RU_REGEX.search(text):
        return "RU"
    t = (text or "").strip().lower()
    if t in {"pret", "preț", "cat costa", "cât costă", "price"}:
        return "RO"
    if t in {"цена", "сколько стоит", "прайс", "стоимость"}:
        return "RU"
    return None

def _iter_message_events(payload: Dict) -> Iterable[Tuple[str, Dict]]:
    """
    Normalizează doar mesajele (NU comentariile).
    - Messenger: entry[].messaging[].message
    - Instagram Graph changes: entry[].changes[] cu value.messages[] DAR field != "comments"
    Yield: (sender_id, msg_dict)
    """
    # Messenger
    for entry in payload.get("entry", []):
        for item in entry.get("messaging", []) or []:
            sender_id = (item.get("sender") or {}).get("id")
            msg = item.get("message") or {}
            if not sender_id or not isinstance(msg, dict):
                continue
            if ("text" in msg) or ("attachments" in msg) or ("quick_reply" in msg):
                yield sender_id, msg

    # Instagram Graph (doar messages, evităm field == 'comments')
    for entry in payload.get("entry", []):
        for ch in entry.get("changes", []) or []:
            if ch.get("field") == "comments":
                continue  # skip aici; comentariile sunt tratate separat
            val = ch.get("value") or {}
            for msg in val.get("messages", []) or []:
                if not isinstance(msg, dict):
                    continue
                from_field = msg.get("from") or val.get("from") or {}
                sender_id = from_field.get("id") if isinstance(from_field, dict) else from_field
                if not sender_id:
                    continue
                # normalize attachments
                attachments = None
                if isinstance(msg.get("attachments"), list):
                    attachments = msg["attachments"]
                elif isinstance(msg.get("attachments"), dict):
                    attachments = [msg["attachments"]]
                elif isinstance(msg.get("message"), dict):
                    inner = msg["message"]
                    if isinstance(inner.get("attachments"), list):
                        attachments = inner["attachments"]
                    elif isinstance(inner.get("attachments"), dict):
                        attachments = [inner["attachments"]]
                if attachments is not None:
                    msg = dict(msg)
                    msg["attachments"] = attachments

                if ("text" in msg) or ("attachments" in msg) or ("quick_reply" in msg):
                    yield sender_id, msg

def _is_ru_text(text: str) -> bool:
    return bool(CYRILLIC_RE.search(text or ""))

# ---------- Routes ----------
@app.get("/health")
def health():
    return {"ok": True}, 200

# Handshake (GET /webhook)
@app.get("/webhook")
def verify_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge, 200
    return "Forbidden", 403

# Evenimente (POST /webhook): tratează și mesaje, și comentarii
@app.post("/webhook")
def webhook():
    # (opțional) verificare semnătură
    if not _verify_signature():
        app.logger.error("Invalid X-Hub-Signature-256")
        abort(403)

    data = request.get_json(force=True, silent=True) or {}
    app.logger.info("Incoming webhook: %s", json.dumps(data, ensure_ascii=False))

    # --- 1) Fluxul de COMENTARII (exact ca până acum) ---
    for entry in data.get("entry", []):
        for change in entry.get("changes", []):
            if change.get("field") != "comments":
                continue  # ignorăm ce nu e „comments” aici

            value = change.get("value", {}) or {}
            comment_id = value.get("id") or value.get("comment_id")
            text = value.get("text", "") or ""
            from_user = (value.get("from") or {}).get("id")

            app.logger.info(f"[DEBUG] Comment {comment_id} from user: {from_user}")

            # evităm self-replies
            if from_user and MY_IG_USER_ID and str(from_user) == str(MY_IG_USER_ID):
                continue
            if not comment_id:
                continue

            # DEDUP comentarii
            now = time.time()
            # curățare TTL
            for old_cid, ts in list(PROCESSED_COMMENTS.items()):
                if now - ts > COMMENT_TTL:
                    del PROCESSED_COMMENTS[old_cid]
            if comment_id in PROCESSED_COMMENTS:
                app.logger.info(f"[comments] Comment {comment_id} already processed, skipping")
                continue
            PROCESSED_COMMENTS[comment_id] = now
            app.logger.info(f"[comments] Processing new comment {comment_id}")

            # 1) răspuns public scurt (RO/RU)
            lang_ru = _is_ru_text(text)
            ack = ACK_PUBLIC_RU if lang_ru else ACK_PUBLIC_RO
            try:
                result = reply_public_to_comment(comment_id, ack)
                if isinstance(result, dict) and result.get("success") is False:
                    app.logger.info(f"[comments] Public reply not supported for {comment_id}, continue with private message")
            except Exception:
                app.logger.exception(f"[comments] Public reply failed for {comment_id}")

            # 2) private reply (oferta)
            offer = OFFER_TEXT_RU if lang_ru else OFFER_TEXT_RO
            try:
                if from_user:
                    result = send_private_reply_to_comment_ig(str(comment_id), offer)
                    if isinstance(result, dict) and result.get("success") is False:
                        app.logger.warning(f"[comments] Private reply failed for {comment_id}.")
                    else:
                        app.logger.info(f"[comments] Private reply sent to {comment_id}")
                else:
                    app.logger.warning(f"[comments] Missing from.id for {comment_id} – skipping DM")
            except Exception:
                app.logger.exception(f"[comments] Private reply failed for {comment_id}")

    # --- 2) Fluxul de MESAJE (DM) — trigger ofertă + anti-spam ---
    for sender_id, msg in _iter_message_events(data):
        if msg.get("is_echo"):
            continue

        mid = msg.get("mid") or msg.get("id")
        if mid and _is_duplicate_mid(mid):
            continue

        text_in = (
            (msg.get("text"))
            or ((msg.get("message") or {}).get("text"))
            or ""
        ).strip()

        attachments = msg.get("attachments") if isinstance(msg.get("attachments"), list) else []
        app.logger.info("EVENT sender=%s text=%r attachments=%d", sender_id, text_in, len(attachments))

        # Trigger ofertă (RO/RU) o singură dată în fereastra de cooldown
        lang = _detect_offer_lang(text_in)
        if lang and _should_send_offer(sender_id):
            offer = OFFER_TEXT_RU if lang == "RU" else OFFER_TEXT_RO
            try:
                send_instagram_message(sender_id, offer[:900])
            except Exception as e:
                app.logger.exception("Failed to send offer: %s", e)
            # nu mai răspundem altceva la acest mesaj
            continue

        # AICI poți adăuga alte fluxuri viitoare, dacă e cazul
        # (momentan webhook-ul rămâne minimal pe DM)

    return jsonify({"ok": True}), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8080")), debug=False)