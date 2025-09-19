import os
import re
import time
from flask import Flask, request, jsonify
from send_message import reply_public_to_comment, send_private_reply_to_comment_ig

app = Flask(__name__)

# === Deduplication pentru comentarii ===
PROCESSED_COMMENTS = {}  # comment_id -> timestamp
COMMENT_TTL = 3600  # 1 oră în secunde

# === ENV exact ca în Railway ===
VERIFY_TOKEN = os.getenv("IG_VERIFY_TOKEN", "").strip()
MY_IG_USER_ID = os.getenv("IG_ID", "").strip()

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
# === Mesajul public scurt sub comentariu (editabil) ===
ACK_PUBLIC_RO = "Bună 👋 V-am răspuns în privat 💌"
ACK_PUBLIC_RU = "Здравствуйте 👋\nОтветили в личные сообщения 💌"

# === Detecție simplă RU (alfabet chirilic) ===
CYRILLIC_RE = re.compile(r"[А-Яа-яЁёЇїІіЄєҐґ]")

def _is_ru(text: str) -> bool:
    return bool(CYRILLIC_RE.search(text or ""))

# === Handshake (GET /webhook) ===
@app.get("/webhook")
def verify_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge, 200
    return "Forbidden", 403

# === Evenimente (POST /webhook) — DOAR fluxul de comentarii ===
@app.post("/webhook")
def webhook():
    data = request.get_json(silent=True) or {}

    for entry in data.get("entry", []):
        for change in entry.get("changes", []):
            if change.get("field") != "comments":
                continue  # ignorăm TOT ce nu e „comments”

            value = change.get("value", {}) or {}
            comment_id = value.get("id") or value.get("comment_id")
            text = value.get("text", "")
            from_user = (value.get("from") or {}).get("id")
            
            # Debug: Log the user ID to see what we're getting
            app.logger.info(f"[DEBUG] Comment {comment_id} from user: {from_user}")

            # evităm self-replies (comentarii făcute de propriul cont)
            if from_user and MY_IG_USER_ID and str(from_user) == str(MY_IG_USER_ID):
                continue
            if not comment_id:
                continue
            
            # === DEDUPLICATION: evităm procesarea aceluiași comentariu de mai multe ori ===
            current_time = time.time()
            
            # Curățăm comentarii vechi (mai vechi de 1 oră)
            for old_comment_id, old_timestamp in list(PROCESSED_COMMENTS.items()):
                if current_time - old_timestamp > COMMENT_TTL:
                    del PROCESSED_COMMENTS[old_comment_id]
            
            # Verificăm dacă am procesat deja acest comentariu
            if comment_id in PROCESSED_COMMENTS:
                app.logger.info(f"[comments] Comment {comment_id} already processed, skipping")
                continue
            
            # Marcăm comentariul ca procesat
            PROCESSED_COMMENTS[comment_id] = current_time
            app.logger.info(f"[comments] Processing new comment {comment_id}")

            # 1) răspuns public scurt (RO/RU) - Instagram nu suportă public replies
            lang_ru = _is_ru(text)
            ack = ACK_PUBLIC_RU if lang_ru else ACK_PUBLIC_RO
            try:
                result = reply_public_to_comment(comment_id, ack)
                if result.get("success") == False:
                    app.logger.info(f"[comments] Instagram public reply not supported for {comment_id}, continuing with private message")
            except Exception:
                app.logger.exception(f"[comments] Public reply failed for {comment_id}")

            # 2) private reply cu OFERTA folosind Instagram Private Reply (funcționează pentru toți comentatorii)
            offer = OFFER_TEXT_RU if lang_ru else OFFER_TEXT_RO
            try:
                if from_user:
                    # Use Instagram Private Reply - works for all commenters, even first-time visitors
                    result = send_private_reply_to_comment_ig(str(comment_id), offer)
                    if result.get("success") == False:
                        app.logger.warning(f"[comments] Private reply failed for {comment_id}. Public reply was sent successfully.")
                    else:
                        app.logger.info(f"[comments] Private reply sent successfully to {comment_id}")
                else:
                    app.logger.warning(f"[comments] Lipsă from.id pentru {comment_id} – sar peste DM")
            except Exception:
                app.logger.exception(f"[comments] Private reply failed for {comment_id}")

    # Nu declanșăm alte fluxuri, nu trimitem alte mesaje — omul preia ulterior
    return jsonify({"ok": True})
