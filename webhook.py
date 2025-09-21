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
    "Salutare 👋\n\n"
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

CYRILLIC_RE = re.compile(r"[\u0400-\u04FF]")

# Lexicon RO
RO_PRICE_TERMS = {
    "pret","pretul","preturi","tarif","cost","costa","cat e","cat costa","cat vine","cat ajunge",
    "cat este","care e pretul","aveti preturi","oferta","oferti",
}
RO_MODEL_TERMS = {
    "model","modele","pentru profesori","profesori","catalog","lampi","lampa","lampă","neon",
}
RO_COMPARATORS = {
    "diferit","diferite","acelasi","același","pentru orice","toate modelele","depinde de model",
}

# Lexicon RU
RU_PRICE_TERMS = {
    "цена","прайс","стоимость","сколько стоит","сколько цена","сколько будет",
}
RU_MODEL_TERMS = {
    "модель","модели","каталог","лампа","лампы","для учителя","учителю","учителям",
}
RU_COMPARATORS = {
    "разная","разные","одинаковая","одинаковая цена","для всех моделей","зависит от модели",
}

# Expresii compuse utile
RO_PRICE_REGEX = re.compile(
    r"(care\s+e\s+pretul|sunt\s+preturi\s+diferite|acelasi\s+pret|pret\s+pe\s+model|pret\s+pentru\s+orice\s+model)",
    re.IGNORECASE,
)
RU_PRICE_REGEX = re.compile(
    r"(цена\s+для\s+всех\s+моделей|разная\s+цена|одинаковая\s+цена|цена\s+за\s+модель)",
    re.IGNORECASE,
)

ETA_TEXT = (
    "Lucrarea se elaborează timp de 3-4 zile lucrătoare\n\n"
    "Livrarea durează de la o zi până la trei zile independent de metodă și locație\n\n"
    "Ați avea nevoie de produs pentru o anumită dată?\n\n"
    "Unde va trebui de livrat produsul?"
)

ETA_TEXT_RU = (
    "Изготовление изделия занимает 3-4 рабочих дня\n\n"
    "Доставка длится от одного до трёх дней, в зависимости от метода и локации\n\n"
    "Вам нужен продукт к определённой дате?\n\n"
    "Куда необходимо будет доставить заказ?"
)

# === Regex pentru întrebări despre timp/termen (RO + RU) ===
ETA_PATTERNS_RO = [
    r"\bîn\s+c[âa]t\s+timp\b",
    r"\bc[âa]t\s+se\s+(face|realizeaz[ăa]|execut[ăa])\b",
    r"\bcare\s+este\s+termenul\b",
    r"\btermen(ul)?\s+de\s+(realizare|executare)\b",
    r"\b(timp|durat[ăa])\s+de\s+executare\b",
]

ETA_PATTERNS_RU = [
    r"\bчерез\s+сколько\b",
    r"\bсколько\s+дн(ей|я)\b",
    r"\bсрок(и)?\s+изготовлени[яе]\b",
    r"\bза\s+какое\s+время\b",
]

ETA_REGEX = re.compile("|".join(ETA_PATTERNS_RO + ETA_PATTERNS_RU), re.IGNORECASE)

# === Anti-spam ETA: răspunde o singură dată per conversație (per user) ===
ETA_REPLIED: Dict[str, bool] = {} 

# === LIVRARE: text + trigger intent (RO+RU) ===
DELIVERY_TEXT = (
    "Livrăm în toată Moldova 📦\n\n"
    "✅ În Chișinău și Bălți: prin curier personal, timp de o zi lucrătoare, din moment ce este gata comanda, direct la adresă. Cost livrare: 65 lei.\n\n"
    "✅ În alte localități:\n"
    "• Prin poștă — ajunge în 3 zile lucrătoare, plata la primire (cash), 65 lei livrarea.\n"
    "• Prin curier — 1/2 zile lucrătoare din momentul expedierii, plata pentru comandă se face în prealabil pe card, 68 lei livrarea.\n\n"
    "Cum ați prefera să facem livrarea?"
)

DELIVERY_TEXT_RU = (
    "Доставляем по всей Молдове 📦\n\n"
    "✅ В Кишинёве и Бельцах: курьером лично, в течение 1 рабочего дня после готовности заказа, прямо по адресу. Стоимость доставки: 65 лей.\n\n"
    "✅ В другие населённые пункты:\n"
    "• Почтой — доставка за 3 рабочих дня, оплата при получении (наличными), 65 лей доставка.\n"
    "• Курьером — 1/2 рабочих дня с момента отправки, оплата заказа предварительно на карту, доставка 68 лей.\n\n"
    "Как вам было бы удобнее получить заказ?"
)

# Cuvinte-cheie/întrebări pentru livrare (intenție explicită), fără a include executarea/ETA
DELIVERY_PATTERNS_RO = [
    r"\bcum\s+se\s+face\s+livrarea\b",
    r"\bcum\s+livra[țt]i\b",                        # cum livrați/livrati
    r"\bmetod[ăa]?\s+de\s+livrare\b",
    r"\bmodalit[ăa][țt]i\s+de\s+livrare\b",
    r"\bexpediere\b", r"\btrimite[țt]i\b",          # „trimiteți în...?”, „trimiteți prin...?”
    r"\blivrarea\b", r"\blivrare\b",
    r"\bcurier\b", r"\bpo[șs]t[ăa]\b",
    r"\bcost(ul)?\s+livr[ăa]rii?\b", r"\btaxa\s+de\s+livrare\b",
    r"\blivra[țt]i\s+în\b",                         # „livrați în Orhei?”
    r"\bse\s+livreaz[ăa]\b",
    r"\bcum\s+ajunge\b",                            # „cum ajunge coletul?”
]
DELIVERY_PATTERNS_RU = [
    r"\bкак\s+доставка\b", r"\bкак\s+вы\s+доставляете\b",
    r"\bспособ(ы)?\s+доставки\b",
    r"\bотправк[аи]\b", r"\bпересылк[аи]\b",
    r"\bдоставк[аи]\b", r"\bкурьер\b", r"\bпочт[аы]\b",
    r"\bстоимост[ьи]\s+доставки\b", r"\bсколько\s+стоит\s+доставк[аи]\b",
    r"\bдоставляете\s+в\b",                         # „доставляете в ...?”
    r"\bкак\s+получить\b",
]

DELIVERY_REGEX = re.compile("|".join(DELIVERY_PATTERNS_RO + DELIVERY_PATTERNS_RU), re.IGNORECASE)

# Anti-spam livrare: răspunde o singură dată per user/conversație
DELIVERY_REPLIED: Dict[str, bool] = {}

# === Trigger „mă gândesc / revin” ===
FOLLOWUP_PATTERNS_RO = [
    r"\bm[ăa]\s+voi\s+g[âa]ndi\b",
    r"\bm[ăa]\s+determin\b",
    r"\b(revin|revin\s+mai\s+t[âa]rziu)\b",
    r"\bv[ăa]\s+anun[țt]\b",
    r"\bdac[ăa]\s+ceva\s+v[ăa]\s+anun[țt]\b",
    r"\bpoate\s+revin\b",
    r"\bdecid\s+dup[ăa]\b",
]
FOLLOWUP_PATTERNS_RU = [
    r"\bподум[аюе]\b",
    r"\bесли\s+что\s+сообщ[уим]\b",
    r"\bя\s+реш[уим]\s+и\s+вернусь\b",
    r"\bпозже\s+отпиш[усь]\b",
    r"\bмогу\s+верн[уть]\b",
]

FOLLOWUP_REGEX = re.compile("|".join(FOLLOWUP_PATTERNS_RO + FOLLOWUP_PATTERNS_RU), re.IGNORECASE)

# Anti-spam: răspunde doar o dată pe conversație
FOLLOWUP_REPLIED: Dict[str, bool] = {}

# === FOLLOW-UP: când clientul spune că se gândește și revine ===
FOLLOWUP_TEXT_RO = (
    "Dacă apar careva întrebări privitor la produsele noastre sau la alte lucruri legate de livrare, "
    "vă puteți adresa, noi mereu suntem dispuși pentru a reveni cu un răspuns explicit 😊\n\n"
    "Pentru o comandă cu termen limită rugăm să ne apelați din timp."
)

FOLLOWUP_TEXT_RU = (
    "Если появятся вопросы по нашим товарам или по доставке, "
    "вы можете обращаться — мы всегда готовы дать подробный ответ 😊\n\n"
    "Для заказа с ограниченным сроком просим связаться с нами заранее."
)

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

_DIAC_MAP = str.maketrans({"ă":"a","â":"a","î":"i","ș":"s","ţ":"t","ț":"t",
                           "Ă":"a","Â":"a","Î":"i","Ș":"s","Ţ":"t","Ț":"t"})

def _norm_ro(s: str) -> str:
    s = (s or "").strip().lower().translate(_DIAC_MAP)
    return " ".join(s.split())

def _count_signals(tokens: set, lexicons: list[set[str]]) -> int:
    return sum(1 for lex in lexicons if tokens & lex)

def _detect_offer_lang(text: str) -> str | None:
    """
    Întoarce 'RO' sau 'RU' dacă mesajul indică intenție de preț/ofertă.
    Regulă: >=2 semnale din (TERMS_PRET, TERMS_MODEL, COMPARATORS)
            sau potrivire pe expresii compuse,
            sau fallback: '?' + termeni de preț.
    """
    if not text or not text.strip():
        return None

    has_cyr = bool(CYRILLIC_RE.search(text))
    ro_norm = _norm_ro(text)
    ro_toks = set(ro_norm.split())

    # RO match
    ro_score = _count_signals(ro_toks, [RO_PRICE_TERMS, RO_MODEL_TERMS, RO_COMPARATORS])
    ro_match = bool(RO_PRICE_REGEX.search(text)) or ro_score >= 2 or (
        "?" in text and (ro_toks & RO_PRICE_TERMS)
    )

    # RU match
    low = (text or "").lower()
    ru_toks = set(low.split())
    ru_score = _count_signals(ru_toks, [RU_PRICE_TERMS, RU_MODEL_TERMS, RU_COMPARATORS])
    ru_match = bool(RU_PRICE_REGEX.search(low)) or ru_score >= 2 or (
        "?" in low and any(term in low for term in RU_PRICE_TERMS)
    )

    if has_cyr and ru_match:
        return "RU"
    if ro_match and not has_cyr:
        return "RO"
    if ru_match:
        return "RU"
    if ro_match:
        return "RO"
    return None

def _should_send_delivery(sender_id: str, text: str) -> str | None:
    """
    Returnează 'RU' sau 'RO' dacă mesajul întreabă despre livrare
    și nu am răspuns încă în conversația curentă. Altfel None.
    """
    if not text:
        return None
    if DELIVERY_REGEX.search(text):
        if DELIVERY_REPLIED.get(sender_id):
            return None
        DELIVERY_REPLIED[sender_id] = True
        return "RU" if CYRILLIC_RE.search(text) else "RO"
    return None

def _should_send_eta(sender_id: str, text: str) -> str | None:
    """
    Returnează 'RU' sau 'RO' dacă mesajul întreabă despre termenul de executare
    și nu am răspuns încă în conversația curentă. Altfel None.
    """
    if not text:
        return None
    if ETA_REGEX.search(text):
        if ETA_REPLIED.get(sender_id):
            return None
        ETA_REPLIED[sender_id] = True
        return "RU" if CYRILLIC_RE.search(text) else "RO"
    return None

def _should_send_followup(sender_id: str, text: str) -> str | None:
    """
    Returnează 'RO' sau 'RU' dacă mesajul e de tip 'mă gândesc/revin'.
    Asigură o singură trimitere per conversație (anti-spam).
    """
    if not text:
        return None
    if FOLLOWUP_REGEX.search(text):
        if FOLLOWUP_REPLIED.get(sender_id):
            return None
        FOLLOWUP_REPLIED[sender_id] = True
        # limbă: dacă textul conține chirilice -> RU
        return "RU" if CYRILLIC_RE.search(text) else "RO"
    return None

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

            # --- ETA (timp execuție) — răspunde DOAR o dată per user ---
        lang_eta = _should_send_eta(sender_id, text_in)
        if lang_eta:
            try:
                msg_eta = ETA_TEXT_RU if lang_eta == "RU" else ETA_TEXT
                send_instagram_message(sender_id, msg_eta[:900])
            except Exception as e:
                app.logger.exception("Failed to send ETA reply: %s", e)
            continue

            # --- LIVRARE (o singură dată) ---
        lang_del = _should_send_delivery(sender_id, text_in)
        if lang_del:
            try:
                msg_del = DELIVERY_TEXT_RU if lang_del == "RU" else DELIVERY_TEXT
                send_instagram_message(sender_id, msg_del[:900])
            except Exception as e:
                    app.logger.exception("Failed to send delivery reply: %s", e)
            continue


                # --- FOLLOW-UP („mă gândesc / revin”) — răspunde DOAR o dată ---
        lang_followup = _should_send_followup(sender_id, text_in)
        if lang_followup:
            reply = FOLLOWUP_TEXT_RU if lang_followup == "RU" else FOLLOWUP_TEXT_RO
            try:
                send_instagram_message(sender_id, reply[:900])
            except Exception as e:
                app.logger.exception("Failed to send follow-up reply: %s", e)
            continue

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
        
        if "?" in text_in and len(text_in) <= 160:
            app.logger.info("[OFFER_INTENT_MISSING] %r", text_in)
        # AICI poți adăuga alte fluxuri viitoare, dacă e cazul
        # (momentan webhook-ul rămâne minimal pe DM)

    return jsonify({"ok": True}), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8080")), debug=False)