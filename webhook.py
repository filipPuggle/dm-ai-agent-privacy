import os
import json
import time
import hmac
import hashlib
import logging
import re
import random
import threading
from typing import Dict, Iterable, Tuple
from flask import Flask, request, abort, jsonify

# === Importurile tale existente pentru trimitere mesaje/replies ===
from send_message import (
    send_instagram_message,           # DM to user_id
    reply_public_to_comment,          # public ack under comment (dacă platforma permite)
    send_instagram_images,            # pentru galeria de imagini

)
app = Flask(__name__, static_folder="static", static_url_path="/static")
logging.basicConfig(level=logging.INFO)

# === ENV (exact ca în Railway) ===
VERIFY_TOKEN = os.getenv("IG_VERIFY_TOKEN", "").strip()
APP_SECRET   = os.getenv("IG_APP_SECRET", "").strip()  # opțional, pentru semnătură
MY_IG_USER_ID = os.getenv("IG_ID", "").strip()
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").strip()

# === Dedup DM (MID) — 5 minute ===
SEEN_MIDS: Dict[str, float] = {}
DEDUP_TTL_SEC = 300

# === Anti-spam ofertă (o singură replică per user într-un interval) ===
OFFER_COOLDOWN_SEC = int(os.getenv("OFFER_COOLDOWN_SEC", "180"))  # default 3 min
LAST_OFFER_AT: Dict[str, float] = {}  # sender_id -> epoch

# === Dedup comentarii — 1 oră ===
PROCESSED_COMMENTS: Dict[str, float] = {}
COMMENT_TTL = 3600  # 1 oră în secunde

# Separate anti-spam for different payment question types
PAYMENT_GENERAL_REPLIED: Dict[str, float] = {}  # General payment questions
ADVANCE_AMOUNT_REPLIED: Dict[str, float] = {}  # Amount questions  
ADVANCE_METHOD_REPLIED: Dict[str, float] = {}  # Method questions
PAYMENT_TTL_SEC = 2 * 60  # 2 minutes for each type

REPLY_DELAY_MIN_SEC = float(os.getenv("REPLY_DELAY_MIN_SEC", "4.0"))
REPLY_DELAY_MAX_SEC = float(os.getenv("REPLY_DELAY_MAX_SEC", "7.0"))

# === Texte ofertă ===
OFFER_TEXT_RO = (
    "Salutare 👋\n\n"
    "Vă putem propune aceste modele de lămpi pentru ziua profesorului\n\n"
    "Textul și elementele de decor de pe lampă pot fi personalizate după dorința dvs\n\n"
    "Lămpile au 16 culori și telecomandă în set 🥰\n\n"
    "Beneficiați de garanție la toată electronica⚡\n\n"
    "Prețul unei asemenea lucrări este 650 lei\n\n"
    "Care model vă este mai pe plac ?"
)
OFFER_TEXT_RU = (
    "Здравствуйте 👋\n\n"
    "Мы можем предложить вам такие модели ламп к Дню Учителя 🎉\n\n"
    "Текст на лампе можно персонализировать по вашему желанию ✍️\n\n"
    "Лампы имеют 16 цветов и идут в комплекте с пультом 🥰\n\n"
    "На всю электронику предоставляется гарантия ⚡\n\n"
    "Стоимость такой работы составляет 650 лей\n\n"
    "Какой вариант вам больше нравится?"
)

# === Mesaj public scurt sub comentariu ===
ACK_PUBLIC_RO = "Bună 👋 V-am răspuns în privat 💌"
ACK_PUBLIC_RU = "Здравствуйте 👋\nОтветили в личные сообщения 💌"

# === Offer intent (price/catalog/models/details) — RO + RU extins ===
CYRILLIC_RE = re.compile(r"[\u0400-\u04FF]")

_SHORT_PRICE_RO = re.compile(r"\b(?:la\s+ce\s+)?pre[tț]\b", re.IGNORECASE)
_SHORT_PRICE_RU = re.compile(r"\b(?:цен[ауые]|сколько)\b", re.IGNORECASE)

# RO — termeni legati de pret
RO_PRICE_TERMS = {
    "pret","pretul","preturi","tarif","cost","costa","cat e","cat este","cat costa",
    "cat vine","cat ajunge","care e pretul","aveti preturi","oferta","oferti","price",
}

# RO — termeni de produs / categorie
RO_PRODUCT_TERMS = {
    "lampa","lampa","lampi","lampe","lampă","lampile","modele","model","catalog","neon",
    "pentru profesori","profesori","profesor",
}

# RO — termeni de detalii / informatii
RO_DETAIL_TERMS = {
    "detalii","mai multe detalii","informatii","informații","descriere","specificatii",
    "detalii despre","vreau detalii","doresc detalii","as dori detalii","as dori informatii",
    "doresc mai multe informatii","spune-mi mai multe","spuneti-mi mai multe","mai multe info",
}

# RO — comparatori
RO_COMPARATORS = {
    "diferit","diferite","acelasi","același","pentru orice","toate modelele","depinde de model",
}

# RU — termeni legati de pret
RU_PRICE_TERMS = {
    "цена","цену","цены","прайс","стоимость","сколько","сколько стоит",
    "сколько цена","сколько будет","по чем","почем","узнать цену",
    "сколько будет стоить","ск сколько",
}

# RU — termeni de produs / categorie
RU_PRODUCT_TERMS = {
    "лампа","лампы","модель","модели","каталог","для учителя","учителю","учителям","неон",
}

# RU — detalii/informații
RU_DETAIL_TERMS = {
    "подробнее","детали","хочу детали","расскажите подробнее","можно подробнее",
    "больше информации","узнать подробнее","инфо","информация",
}

# RU — comparatori
RU_COMPARATORS = {
    "разная","разные","одинаковая","одинаковая цена","для всех моделей","зависит от модели",
}

# Expresii compuse (ancore clare)
RO_PRICE_REGEX = re.compile(
    r"(care\s+e\s+pretul|sunt\s+preturi\s+diferite|acelasi\s+pret|pret\s+pe\s+model|pret\s+pentru\s+orice\s+model|la\s+ce\s+pret)",
    re.IGNORECASE,
)
RU_PRICE_REGEX = re.compile(
    r"(цена\s+для\s+всех\s+моделей|разная\s+цена|одинаковая\s+цена|цена\s+за\s+модель|можно\s+узнать\s+цену)",
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
    r"\bсколько\s+дн(?:ей|я)\b",
    r"\bсрок(?:и)?\s+изготовлени[яе]\b",
    r"\bза\s+какое\s+время\b",
    # — extinderi uzuale/colocviale —
    r"\bчто\s+по\s+срокам\??",                 # Что по срокам?
    r"\bкакие\s+сроки\??",                     # Какие сроки?
    r"\bкакие\s+сроки\s+изготовлени[яе]\??",   # Какие сроки изготовления?
    r"\bпо\s+времени\s+как\??",                # По времени как?
    r"\bк\s+каком[уы]\s+числ[уы]\??",          # К какому числу?
    r"\bуспеет[е]?\s+к\s+\d{1,2}\.?(\s*[а-я]+)?",   # Успеете к 15/к 15 мая
    r"\bсрок[и]?\b",                           # одиночное «сроки?»
    r"\bпо\s+срокам\b",                        # «по срокам»
    
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

# === Galeria de imagini - o singură dată per conversație ===
GALLERY_SENT: Dict[str, bool] = {}

# === Ofertă text - o singură dată per conversație ===
OFFER_SENT: Dict[str, bool] = {}

# === Configurare imagini ofertă ===
OFFER_MEDIA_RO = [
    f"{PUBLIC_BASE_URL}/static/offer/ro_01.jpg",
    f"{PUBLIC_BASE_URL}/static/offer/ro_02.jpg", 
    f"{PUBLIC_BASE_URL}/static/offer/ro_03.jpg",
    f"{PUBLIC_BASE_URL}/static/offer/ro_04.jpg",
    f"{PUBLIC_BASE_URL}/static/offer/ro_05.jpg"
] if PUBLIC_BASE_URL else []

OFFER_MEDIA_RU = [
    f"{PUBLIC_BASE_URL}/static/offer/ru_01.jpg",
    f"{PUBLIC_BASE_URL}/static/offer/ru_02.jpg",
    f"{PUBLIC_BASE_URL}/static/offer/ru_03.jpg", 
    f"{PUBLIC_BASE_URL}/static/offer/ru_04.jpg",
    f"{PUBLIC_BASE_URL}/static/offer/ru_05.jpg"
] if PUBLIC_BASE_URL else []

# === Trigger „mă gândesc / revin” ===
FOLLOWUP_PATTERNS_RO = [
    # Existing patterns - preserved
    r"\bm[ăa]\s+voi\s+g[âa]ndi\b",
    r"\bm[ăa]\s+g[âa]ndesc\b",
    r"\bo\s+s[ăa]\s+m[ăa]\s+g[âa]ndesc\b",
    r"\bm[ăa]\s+determin\b",
    r"\b(revin|revin\s+mai\s+t[âa]rziu)\b",
    r"\bv[ăa]\s+anun[țt]\b",
    r"\bdac[ăa]\s+ceva\s+v[ăa]\s+anun[țt]\b",
    r"\bpoate\s+revin\b",
    r"\bdecid\s+dup[ăa]\b",
    r"\bmai\s+t[âa]rziu\s+revin\b",
    
    # Additional Romanian variations for "I'll think about it"
    r"\bm[ăa]\s+voi\s+reflecta\b",                    # mă voi reflecta
    r"\bm[ăa]\s+voi\s+considera\b",                   # mă voi considera
    r"\bm[ăa]\s+voi\s+medita\b",                      # mă voi medita
    r"\bvoi\s+g[âa]ndi\b",                           # voi gândi
    r"\bvoi\s+reflecta\b",                           # voi reflecta
    r"\bvoi\s+considera\b",                          # voi considera
    r"\bvoi\s+medita\b",                             # voi medita
    r"\bm[ăa]\s+g[âa]ndesc\s+la\s+asta\b",           # mă gândesc la asta
    r"\bm[ăa]\s+g[âa]ndesc\s+la\s+ce\s+mi\s+ai\s+spus\b", # mă gândesc la ce mi-ai spus
    r"\bhai\s+s[ăa]\s+m[ăa]\s+g[âa]ndesc\b",         # hai să mă gândesc
    r"\blas[ăa]\-m[ăa]\s+s[ăa]\s+m[ăa]\s+g[âa]ndesc\b", # lasă-mă să mă gândesc
    r"\btrebuie\s+s[ăa]\s+m[ăa]\s+g[âa]ndesc\b",     # trebuie să mă gândesc
    r"\bvreau\s+s[ăa]\s+m[ăa]\s+g[âa]ndesc\b",       # vreau să mă gândesc
    r"\bvreau\s+s[ăa]\s+g[âa]ndesc\b",               # vreau să gândesc
    r"\bam\s+nevoie\s+s[ăa]\s+m[ăa]\s+g[âa]ndesc\b", # am nevoie să mă gândesc
    r"\bam\s+nevoie\s+s[ăa]\s+g[âa]ndesc\b",         # am nevoie să gândesc
    
    # Additional Romanian variations for "I'll get back to you"
    r"\bmai\s+t[âa]rziu\s+v[ăa]\s+contactez\b",      # mai târziu vă contactez
    r"\bmai\s+t[âa]rziu\s+v[ăa]\s+scriu\b",          # mai târziu vă scriu
    r"\bmai\s+t[âa]rziu\s+v[ăa]\s+anun[țt]\b",       # mai târziu vă anunț
    r"\bmai\s+t[âa]rziu\s+v[ăa]\s+spun\b",           # mai târziu vă spun
    r"\bmai\s+t[âa]rziu\s+te\s+contactez\b",         # mai târziu te contactez
    r"\bmai\s+t[âa]rziu\s+te\s+scriu\b",             # mai târziu te scriu
    r"\bmai\s+t[âa]rziu\s+te\s+anun[țt]\b",          # mai târziu te anunț
    r"\bmai\s+t[âa]rziu\s+te\s+spun\b",              # mai târziu te spun
    r"\bv[ăa]\s+contactez\s+mai\s+t[âa]rziu\b",      # vă contactez mai târziu
    r"\bv[ăa]\s+scriu\s+mai\s+t[âa]rziu\b",          # vă scriu mai târziu
    r"\bv[ăa]\s+anun[țt]\s+mai\s+t[âa]rziu\b",       # vă anunț mai târziu
    r"\bv[ăa]\s+spun\s+mai\s+t[âa]rziu\b",           # vă spun mai târziu
    r"\bte\s+contactez\s+mai\s+t[âa]rziu\b",         # te contactez mai târziu
    r"\bte\s+scriu\s+mai\s+t[âa]rziu\b",             # te scriu mai târziu
    r"\bte\s+anun[țt]\s+mai\s+t[âa]rziu\b",          # te anunț mai târziu
    r"\bte\s+spun\s+mai\s+t[âa]rziu\b",              # te spun mai târziu
    
    # Romanian variations for "I'll decide later"
    r"\bvoi\s+decide\s+mai\s+t[âa]rziu\b",          # voi decide mai târziu
    r"\bvoi\s+decide\s+dup[ăa]\b",                  # voi decide după
    r"\bvoi\s+decide\s+dup[ăa]\s+ce\s+m[ăa]\s+g[âa]ndesc\b", # voi decide după ce mă gândesc
    r"\bm[ăa]\s+voi\s+hot[ăa]r[âa]i\b",             # mă voi hotărâi
    r"\bvoi\s+hot[ăa]r[âa]i\b",                     # voi hotărâi
    r"\bhot[ăa]r[âa]esc\s+mai\s+t[âa]rziu\b",       # hotărâesc mai târziu
    r"\bhot[ăa]r[âa]esc\s+dup[ăa]\b",               # hotărâesc după
    r"\bm[ăa]\s+voi\s+decide\b",                    # mă voi decide
    r"\bdecid\s+mai\s+t[âa]rziu\b",                 # decid mai târziu
    r"\bdecid\s+dup[ăa]\s+ce\s+m[ăa]\s+g[âa]ndesc\b", # decid după ce mă gândesc
    
    # Romanian variations for "I'll let you know"
    r"\bv[ăa]\s+anun[țt]\s+c[âa]nd\s+decid\b",      # vă anunț când decid
    r"\bv[ăa]\s+anun[țt]\s+c[âa]nd\s+hot[ăa]r[âa]esc\b", # vă anunț când hotărâesc
    r"\bv[ăa]\s+anun[țt]\s+c[âa]nd\s+ma\s+g[âa]ndesc\b", # vă anunț când ma gândesc
    r"\bte\s+anun[țt]\s+c[âa]nd\s+decid\b",         # te anunț când decid
    r"\bte\s+anun[țt]\s+c[âa]nd\s+hot[ăa]r[âa]esc\b", # te anunț când hotărâesc
    r"\bte\s+anun[țt]\s+c[âa]nd\s+ma\s+g[âa]ndesc\b", # te anunț când ma gândesc
    r"\bv[ăa]\s+spun\s+c[âa]nd\s+decid\b",          # vă spun când decid
    r"\bv[ăa]\s+spun\s+c[âa]nd\s+hot[ăa]r[âa]esc\b", # vă spun când hotărâesc
    r"\bte\s+spun\s+c[âa]nd\s+decid\b",             # te spun când decid
    r"\bte\s+spun\s+c[âa]nd\s+hot[ăa]r[âa]esc\b",   # te spun când hotărâesc
    
    # Romanian variations for "maybe I'll come back"
    r"\bpoate\s+v[ăa]\s+contactez\b",               # poate vă contactez
    r"\bpoate\s+te\s+contactez\b",                  # poate te contactez
    r"\bpoate\s+v[ăa]\s+scriu\b",                   # poate vă scriu
    r"\bpoate\s+te\s+scriu\b",                      # poate te scriu
    r"\bpoate\s+v[ăa]\s+anun[țt]\b",                # poate vă anunț
    r"\bpoate\s+te\s+anun[țt]\b",                   # poate te anunț
    r"\bpoate\s+v[ăa]\s+spun\b",                    # poate vă spun
    r"\bpoate\s+te\s+spun\b",                       # poate te spun
]

FOLLOWUP_PATTERNS_RU = [
    # Existing patterns - preserved
    r"\bя\s+подумаю\b",
    r"\bподум[аюе]\b",
    r"\bесли\s+что\s+сообщ[уим]\b",
    r"\bдам\s+знать\b",
    r"\bпозже\s+напиш[ую]\b",
    r"\bреш[уим]\s+и\s+вернусь\b",
    r"\bвернусь\s+позже\b",
    r"\bнапишу\s+позже\b",
    r"\bкак\s+решу\s+—?\s*напишу\b",
    
    # Additional Russian variations for "I'll think about it"
    r"\bя\s+обдумаю\b",                               # я обдумаю
    r"\bя\s+рассмотрю\b",                             # я рассмотрю
    r"\bя\s+взвешу\b",                                # я взвешу
    r"\bя\s+проанализирую\b",                         # я проанализирую
    r"\bобдумаю\b",                                   # обдумаю
    r"\bрассмотрю\b",                                 # рассмотрю
    r"\bвзвешу\b",                                    # взвешу
    r"\bпроанализирую\b",                             # проанализирую
    r"\bмне\s+нужно\s+подумать\b",                    # мне нужно подумать
    r"\bмне\s+нужно\s+обдумать\b",                    # мне нужно обдумать
    r"\bмне\s+нужно\s+рассмотреть\b",                 # мне нужно рассмотреть
    r"\bмне\s+нужно\s+взвесить\b",                    # мне нужно взвесить
    r"\bхочу\s+подумать\b",                           # хочу подумать
    r"\bхочу\s+обдумать\b",                           # хочу обдумать
    r"\bхочу\s+рассмотреть\b",                        # хочу рассмотреть
    r"\bхочу\s+взвесить\b",                           # хочу взвесить
    r"\bдай\s+подумать\b",                            # дай подумать
    r"\bдай\s+обдумать\b",                            # дай обдумать
    r"\bдай\s+рассмотреть\b",                         # дай рассмотреть
    r"\bдай\s+взвесить\b",                            # дай взвесить
    r"\bдайте\s+подумать\b",                          # дайте подумать
    r"\bдайте\s+обдумать\b",                          # дайте обдумать
    r"\bдайте\s+рассмотреть\b",                       # дайте рассмотреть
    r"\bдайте\s+взвесить\b",                          # дайте взвесить
    r"\bнужно\s+подумать\b",                          # нужно подумать
    r"\bнужно\s+обдумать\b",                          # нужно обдумать
    r"\bнужно\s+рассмотреть\b",                       # нужно рассмотреть
    r"\bнужно\s+взвесить\b",                          # нужно взвесить
    r"\bдолжен\s+подумать\b",                         # должен подумать
    r"\bдолжен\s+обдумать\b",                         # должен обдумать
    r"\bдолжен\s+рассмотреть\b",                      # должен рассмотреть
    r"\bдолжен\s+взвесить\b",                         # должен взвесить
    r"\bдолжна\s+подумать\b",                         # должна подумать
    r"\bдолжна\s+обдумать\b",                         # должна обдумать
    r"\bдолжна\s+рассмотреть\b",                      # должна рассмотреть
    r"\bдолжна\s+взвесить\b",                         # должна взвесить
    
    # Additional Russian variations for "I'll get back to you"
    r"\bпозже\s+напиш[ую]\b",                         # позже напишу
    r"\bпозже\s+свяж[уе]сь\b",                        # позже свяжусь
    r"\bпозже\s+отвеч[уе]\b",                         # позже отвечу
    r"\bпозже\s+напиш[уе]м\b",                        # позже напишем
    r"\bпозже\s+свяжемся\b",                          # позже свяжемся
    r"\bпозже\s+отвечим\b",                           # позже отвечим
    r"\bнапиш[ую]\s+позже\b",                         # напишу позже
    r"\bсвяж[уе]сь\s+позже\b",                        # свяжусь позже
    r"\bотвеч[уе]\s+позже\b",                         # отвечу позже
    r"\bнапиш[уе]м\s+позже\b",                        # напишем позже
    r"\bсвяжемся\s+позже\b",                          # свяжемся позже
    r"\bотвечим\s+позже\b",                           # отвечим позже
    r"\bнапиш[ую]\s+чуть\s+позже\b",                  # напишу чуть позже
    r"\bсвяж[уе]сь\s+чуть\s+позже\b",                 # свяжусь чуть позже
    r"\bотвеч[уе]\s+чуть\s+позже\b",                  # отвечу чуть позже
    r"\bнапиш[уе]м\s+чуть\s+позже\b",                 # напишем чуть позже
    r"\bсвяжемся\s+чуть\s+позже\b",                   # свяжемся чуть позже
    r"\bотвечим\s+чуть\s+позже\b",                    # отвечим чуть позже
    
    # Russian variations for "I'll decide later"
    r"\bреш[ую]\s+позже\b",                           # решу позже
    r"\bреш[ую]\s+чуть\s+позже\b",                    # решу чуть позже
    r"\bреш[ую]\s+потом\b",                           # решу потом
    r"\bреш[ую]\s+чуть\s+потом\b",                    # решу чуть потом
    r"\bреш[ую]\s+чуть\s+позднее\b",                  # решу чуть позднее
    r"\bреш[ую]\s+чуть\s+позднее\b",                  # решу чуть позднее
    r"\bреш[ую]\s+после\s+того\s+как\s+подумаю\b",    # решу после того как подумаю
    r"\bреш[ую]\s+после\s+того\s+как\s+обдумаю\b",    # решу после того как обдумаю
    r"\bреш[ую]\s+после\s+того\s+как\s+рассмотрю\b",  # решу после того как рассмотрю
    r"\bреш[ую]\s+после\s+того\s+как\s+взвешу\b",     # решу после того как взвешу
    r"\bреш[уе]м\s+позже\b",                          # решим позже
    r"\bреш[уе]м\s+чуть\s+позже\b",                   # решим чуть позже
    r"\bреш[уе]м\s+потом\b",                          # решим потом
    r"\bреш[уе]м\s+чуть\s+потом\b",                   # решим чуть потом
    r"\bреш[уе]м\s+чуть\s+позднее\b",                 # решим чуть позднее
    r"\bреш[уе]м\s+после\s+того\s+как\s+подумаем\b",  # решим после того как подумаем
    r"\bреш[уе]м\s+после\s+того\s+как\s+обдумаем\b",  # решим после того как обдумаем
    r"\bреш[уе]м\s+после\s+того\s+как\s+рассмотрим\b", # решим после того как рассмотрим
    r"\bреш[уе]м\s+после\s+того\s+как\s+взвесим\b",   # решим после того как взвесим
    
    # Russian variations for "I'll let you know"
    r"\bдам\s+знать\s+когда\s+реш[ую]\b",             # дам знать когда решу
    r"\bдам\s+знать\s+когда\s+реш[уе]м\b",            # дам знать когда решим
    r"\bдам\s+знать\s+когда\s+подумаю\b",             # дам знать когда подумаю
    r"\bдам\s+знать\s+когда\s+подумаем\b",            # дам знать когда подумаем
    r"\bдам\s+знать\s+когда\s+обдумаю\b",             # дам знать когда обдумаю
    r"\bдам\s+знать\s+когда\s+обдумаем\b",            # дам знать когда обдумаем
    r"\bдам\s+знать\s+когда\s+рассмотрю\b",           # дам знать когда рассмотрю
    r"\bдам\s+знать\s+когда\s+рассмотрим\b",          # дам знать когда рассмотрим
    r"\bдам\s+знать\s+когда\s+взвешу\b",              # дам знать когда взвешу
    r"\bдам\s+знать\s+когда\s+взвесим\b",             # дам знать когда взвесим
    r"\bсообщ[ую]\s+когда\s+реш[ую]\b",               # сообщу когда решу
    r"\bсообщ[уе]м\s+когда\s+реш[уе]м\b",             # сообщим когда решим
    r"\bсообщ[ую]\s+когда\s+подумаю\b",               # сообщу когда подумаю
    r"\bсообщ[уе]м\s+когда\s+подумаем\b",             # сообщим когда подумаем
    r"\bсообщ[ую]\s+когда\s+обдумаю\b",               # сообщу когда обдумаю
    r"\bсообщ[уе]м\s+когда\s+обдумаем\b",             # сообщим когда обдумаем
    r"\bсообщ[ую]\s+когда\s+рассмотрю\b",             # сообщу когда рассмотрю
    r"\bсообщ[уе]м\s+когда\s+рассмотрим\b",           # сообщим когда рассмотрим
    r"\bсообщ[ую]\s+когда\s+взвешу\b",                # сообщу когда взвешу
    r"\bсообщ[уе]м\s+когда\s+взвесим\b",              # сообщим когда взвесим
    r"\bнапиш[ую]\s+когда\s+реш[ую]\b",               # напишу когда решу
    r"\bнапиш[уе]м\s+когда\s+реш[уе]м\b",             # напишем когда решим
    r"\bнапиш[ую]\s+когда\s+подумаю\b",               # напишу когда подумаю
    r"\bнапиш[уе]м\s+когда\s+подумаем\b",             # напишем когда подумаем
    r"\bнапиш[ую]\s+когда\s+обдумаю\b",               # напишу когда обдумаю
    r"\bнапиш[уе]м\s+когда\s+обдумаем\b",             # напишем когда обдумаем
    r"\bнапиш[ую]\s+когда\s+рассмотрю\b",             # напишу когда рассмотрю
    r"\bнапиш[уе]м\s+когда\s+рассмотрим\b",           # напишем когда рассмотрим
    r"\bнапиш[ую]\s+когда\s+взвешу\b",                # напишу когда взвешу
    r"\bнапиш[уе]м\s+когда\s+взвесим\b",              # напишем когда взвесим
    
    # Russian variations for "maybe I'll come back"
    r"\bможет\s+напиш[ую]\b",                         # может напишу
    r"\bможет\s+напиш[уе]м\b",                        # может напишем
    r"\bможет\s+свяж[уе]сь\b",                        # может свяжусь
    r"\bможет\s+свяжемся\b",                          # может свяжемся
    r"\bможет\s+отвеч[уе]\b",                         # может отвечу
    r"\bможет\s+отвечим\b",                           # может отвечим
    r"\bможет\s+сообщ[ую]\b",                         # может сообщу
    r"\bможет\s+сообщ[уе]м\b",                        # может сообщим
    r"\bможет\s+дам\s+знать\b",                       # может дам знать
    r"\bможет\s+дадим\s+знать\b",                     # может дадим знать
    r"\bвозможно\s+напиш[ую]\b",                      # возможно напишу
    r"\bвозможно\s+напиш[уе]м\b",                     # возможно напишем
    r"\bвозможно\s+свяж[уе]сь\b",                     # возможно свяжусь
    r"\bвозможно\s+свяжемся\b",                       # возможно свяжемся
    r"\bвозможно\s+отвеч[уе]\b",                      # возможно отвечу
    r"\bвозможно\s+отвечим\b",                        # возможно отвечим
    r"\bвозможно\s+сообщ[ую]\b",                      # возможно сообщу
    r"\bвозможно\s+сообщ[уе]м\b",                     # возможно сообщим
    r"\bвозможно\s+дам\s+знать\b",                    # возможно дам знать
    r"\bвозможно\s+дадим\s+знать\b",                  # возможно дадим знать
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

# === ACHITARE / PAYMENT: text + trigger intent (RO+RU) ===
PAYMENT_TEXT_RO = (
    "Punem accent pe achitare la primire, însă în cazul lucrărilor personalizate este nevoie de un avans."
)

PAYMENT_TEXT_RU = (
    "Обычно оплата при получении, но для персонализированных работ требуется предоплата (аванс)."
)

# RO — întrebări / fraze despre plată/achitare
PAYMENT_PATTERNS_RO = [
    r"\bcum\s+se\s+face\s+achitarea\b",
    r"\bcum\s+se\s+face\s+plata\b",
    r"\bcum\s+pl[ăa]tesc\b",
    r"\bmetod[ăa]?\s+de\s+pl[ăa]t[ăa]\b",
    r"\bmodalit[ăa][țt]i\s+de\s+pl[ăa]t[ăa]\b",
    r"\bachitare\b", r"\bpl[ăa]t[ăa]\b",
    r"\bplata\s+la\s+livrare\b", r"\bramburs\b", r"\bnumerar\b",
    r"\btransfer\b", r"\bpe\s+card\b", r"\bcard\b",
    r"\bavans(ul)?\b", r"\bprepl[ăa]t[ăa]\b", r"\bprepay\b",
]

# RU — întrebări / fraze despre plată/оплата
PAYMENT_PATTERNS_RU = [
    r"\bкак\s+оплатить\b",
    r"\bкак\s+происходит\s+оплата\b",
    r"\bспособ(ы)?\s+оплаты\b",
    r"\bоплат[аи]\b", r"\bоплата\b",
    r"\bоплата\s+при\s+получени[ию]\b", r"\bналичными\b",
    r"\bкартой\b", r"\bоплата\s+картой\b",
    r"\bперевод(ом)?\s+на\s+карту\b", r"\bперевод\b",
    r"\bпредоплата\b", r"\bаванс\b",
    r"\bкак\s+будет\s+оплата\b", r"\bоплата\s+как\b",
]

PAYMENT_REGEX = re.compile("|".join(PAYMENT_PATTERNS_RO + PAYMENT_PATTERNS_RU), re.IGNORECASE)

# Anti-spam plată: o singură dată per user/conversație
# — AVANS / PREPAY exact amount —
ADVANCE_TEXT_RO = (
    "Avansul e în sumă de 200 lei, se achită doar pentru lucrările personalizate!"
)

ADVANCE_TEXT_RU = (
    "Предоплата составляет 200 лей и требуется только для персонализированных работ!"
)

# RO — întrebări specifice despre avans (doar generale, nu sumă/metodă)
ADVANCE_PATTERNS_RO = [
    r"\beste\s+nevoie\s+de\s+avans\b",
    r"\bce\s+avans\s+e\s+nevoie\b",                 # ce avans e nevoie?
    r"\btrebuie\s+avans\b",
    r"\bavans\s+este\s+necesar\b",                  # avans este necesar?
    r"\beste\s+necesar\s+avans\b",                  # este necesar avans?
    r"\bavans\s+obligatoriu\b",                     # avans obligatoriu?
    r"\bobligatoriu\s+avans\b",                     # obligatoriu avans?
    r"\bavans\s+necesar\b",                         # avans necesar?
    r"\bnecesar\s+avans\b",                         # necesar avans?
    r"\bc[âa]t\s+trebuie\s+s[ăa]\s+achit\b.*avans", # cât trebuie să achit avans?
    r"\bprepl[ăa]t[ăa]\b",                          # preplată (rom/rus mix folosit)
]

# RU — întrebări specifice despre предоплата/аванс (doar generale, nu sumă/metodă)
ADVANCE_PATTERNS_RU = [
    r"\bнужн[аы]\s+ли\s+предоплата\b",
    r"\bнужен\s+ли\s+аванс\b",
    r"\bсколько\s+нужно\s+внести\b",
    r"\bнадо\s+ли\s+вносить\s+предоплату\b",
    r"\bнужн[аы]\s+ли\s+аванс\b",                    # нужны ли аванс?
    r"\bнужен\s+ли\s+предоплата\b",                  # нужен ли предоплата?
    r"\bобязательн[аы]\s+ли\s+предоплат[аы]\b",      # обязательны ли предоплата?
    r"\bобязательн[аы]\s+ли\s+аванс\b",             # обязательны ли аванс?
    r"\bобязательн[аы]\s+ли\s+вносить\s+предоплат[уы]\b", # обязательны ли вносить предоплату?
    r"\bобязательн[аы]\s+ли\s+вносить\s+аванс\b",    # обязательны ли вносить аванс?
    r"\bтребуется\s+ли\s+предоплат[аы]\b",           # требуется ли предоплата?
    r"\bтребуется\s+ли\s+аванс\b",                  # требуется ли аванс?
    r"\bнеобходим[аы]\s+ли\s+предоплат[аы]\b",       # необходимы ли предоплата?
    r"\bнеобходим[аы]\s+ли\s+аванс\b",              # необходимы ли аванс?
]
ADVANCE_REGEX = re.compile("|".join(ADVANCE_PATTERNS_RO + ADVANCE_PATTERNS_RU), re.IGNORECASE)


# — AVANS: întrebări despre SUMĂ (RO / RU) —
ADVANCE_AMOUNT_PATTERNS_RO = [
    r"\bc[âa]t\s+(?:e|este)\s+avans(ul)?\b",
    r"\bc[âa]t\s+avans(ul)?\b",
    r"\bcat\s+este\s+avansul\b",                     # cat este avansul?
    r"\bcare\s+e\s+suma\s+(?:de\s+)?avans(ului)?\b",
    r"\bce\s+suma\s+are\s+avansul\b",
    r"\bce\s+sum[ăa]\s+e\s+avansul\b",              # ce sumă e avansul?
    r"\bce\s+sum[ăa]\s+avans\b",                     # ce sumă avans?
    r"\bavans\s+c[âa]t\b",                          # avans cât?
    r"\bavans\s+cat\b",                              # avans cat?
    r"\bavans\s+care\s+suma\b",                      # avans care suma?
    r"\bavans\s+ce\s+suma\b",                       # avans ce suma?
    r"\bavans\s+ce\s+sum[ăa]\b",                    # avans ce sumă?
    r"\bavans\s+suma\b",                            # avans suma?
    r"\bsuma\s+avans(ului)?\b",
    r"\bavansul\s+(?:de|este)\s*\?\b",
    r"\bavans\s+(?:de|este)\s+\d+\b",
    r"\bavans\s+lei\b",                              # avans lei?
    r"\bavans\s+bani\b",                            # avans bani?
    r"\bavans\s+bani\s+c[âa]t\b",                   # avans bani cât?
    r"\bavans\s+bani\s+cat\b",                      # avans bani cat?
]

ADVANCE_AMOUNT_PATTERNS_RU = [
    r"\bсколько\s+(?:нужно\s+)?предоплат[ыыу]\b",
    r"\bсколько\s+нужно\s+для\s+предоплат[ыы]\b",  # сколько нужно для предоплаты?
    r"\bкакая\s+сумма\s+предоплат[ыы]\b",
    r"\bкак[аяой]\s+(?:предоплат[аы]|аванс)\b",     # какая предоплата? / какой аванс?
    r"\bкакой\s+аванс\b",                          # какой аванс?
    r"\bкакая\s+предоплат[аы]\b",                  # какая предоплата?
    r"\bкако[йя]\s+размер\s+предоплат[ыы]\b",
    r"\bсколько\s+аванс\b",
    r"\bаванс\s+сколько\b",
    r"\bсумма\s+аванса\b",
    r"\bаванс\s+сумма\b",                          # аванс сумма?
    r"\bаванс\s+размер\b",                         # аванс размер?
    r"\bаванс\s+размер\s+сколько\b",               # аванс размер сколько?
    r"\bаванс\s+сколько\s+денег\b",                # аванс сколько денег?
    r"\bаванс\s+деньги\b",                         # аванс деньги?
    r"\bаванс\s+лей\b",                           # аванс лей?
    r"\bпредоплат[аы]\s+сколько\b",               # предоплата сколько?
    r"\bпредоплат[аы]\s+сумма\b",                  # предоплата сумма?
    r"\bпредоплат[аы]\s+размер\b",                 # предоплата размер?
    r"\bпредоплат[аы]\s+лей\b",                    # предоплата лей?
    r"\bпредоплат[аы]\s+деньги\b",                 # предоплата деньги?
]
ADVANCE_AMOUNT_REGEX = re.compile("|".join(ADVANCE_AMOUNT_PATTERNS_RO + ADVANCE_AMOUNT_PATTERNS_RU), re.IGNORECASE)

# — AVANS: metoda de plată (RO / RU) —
ADVANCE_METHOD_TEXT_RO = (
    "Avansul se poate achita prin transfer pe card.\n\n"
    "5397 0200 6122 9082 cont MAIB\n\n"
    "062176586 MIA plăți instant\n\n"
    "După transfer, expediați o poză a chitanței, pentru confirmarea transferului."
)

ADVANCE_METHOD_TEXT_RU = (
    "Предоплату можно внести переводом на карту.\n\n"
    "5397 0200 6122 9082 (счёт MAIB)\n\n"
    "062176586 MIA — мгновенные платежи\n\n"
    "После перевода, пожалуйста, отправьте фото квитанции для подтверждения."
)

# RO — cum se achită avansul (metodă / detalii card)
ADVANCE_METHOD_PATTERNS_RO = [
    r"\bcum\s+se\s+poate\s+achita\s+avansul\b",
    r"\bcum\s+pl[ăa]tesc\s+avansul\b",
    r"\bcum\s+pl[ăa]tim\s+avansul\b",              # cum plătim avansul?
    r"\bcum\s+pot\s+pl[ăa]ti\s+avansul\b",         # cum pot plăti avansul?
    r"\bcum\s+pot\s+achita\s+avansul\b",           # cum pot achita avansul?
    r"\bcum\s+se\s+achit[ăa]\s+avansul\b",         # cum se achită avansul?
    r"\bmetod[ăa]?\s+de\s+pl[ăa]t[ăa]\s+pentru\s+avans\b",
    r"\bmetod[ăa]?\s+de\s+achitare\s+avans\b",     # metodă de achitare avans?
    r"\bachitare\s+avans\b", r"\bplata\s+avansului\b",
    r"\btransfer\s+pe\s+card\b", r"\bpe\s+card\s+avans\b",
    r"\bpot\s+pl[ăa]ti\s+avansul\s+cu\s+card(ul)?\b",
    r"\bpot\s+achita\s+avansul\s+cu\s+card(ul)?\b", # pot achita avansul cu card?
    r"\bavans\s+card\b",                           # avans card?
    r"\bavans\s+transfer\b",                       # avans transfer?
    r"\bavans\s+pe\s+card\b",                      # avans pe card?
    r"\bdetalii\s+card\b", r"\bdate\s+card\b",
    r"\brechizite\b", r"\bnum[aă]r\s+de\s+card\b",
    r"\bunde\s+pot\s+pl[ăa]ti\s+avansul\b",
    r"\bunde\s+pot\s+achita\s+avansul\b",          # unde pot achita avansul?
    r"\bcont\s+maib\b", r"\bpl[ăa]ți\s+instant\b", r"\bplati\s+instant\b",
    r"\bavans\s+cont\b",                           # avans cont?
    r"\bavans\s+maib\b",                          # avans maib?
    r"\bavans\s+instant\b",                       # avans instant?
]

# RU — как оплатить предоплату (метод / реквизиты)
ADVANCE_METHOD_PATTERNS_RU = [
    r"\bкак\s+(?:оплатить|внести)\s+предоплат[ау]\b",
    r"\bкак\s+(?:оплатить|внести)\s+аванс\b",
    r"\bкак\s+можно\s+оплатить\s+аванс\b",         # как можно оплатить аванс?
    r"\bкак\s+можно\s+внести\s+аванс\b",           # как можно внести аванс?
    r"\bкак\s+можно\s+оплатить\s+предоплат[уы]\b", # как можно оплатить предоплату?
    r"\bкак\s+можно\s+внести\s+предоплат[уы]\b",   # как можно внести предоплату?
    r"\bоплата\s+аванс[а]?\b", r"\bпредоплата\s+как\b",
    r"\bаванс\s+как\b",                            # аванс как?
    r"\bаванс\s+оплатить\b",                       # аванс оплатить?
    r"\bаванс\s+внести\b",                         # аванс внести?
    r"\bаванс\s+перевод\b",                        # аванс перевод?
    r"\bаванс\s+карта\b",                          # аванс карта?
    r"\bаванс\s+картой\b",                         # аванс картой?
    r"\bперевод\s+на\s+карту\b", r"\bкартой\s+можно\b",
    r"\bреквизит[ыа]\b", r"\bномер\s+карты\b",
    r"\bкуда\s+перевест[ьи]\b", r"\bкак\s+сделать\s+перевод\b",
    r"\bкуда\s+оплатить\s+предоплат[уы]\b",
    r"\bкуда\s+оплатить\s+аванс\b",                # куда оплатить аванс?
    r"\bкуда\s+внести\s+аванс\b",                  # куда внести аванс?
    r"\bкуда\s+внести\s+предоплат[уы]\b",          # куда внести предоплату?
    r"\bреквизиты\s+для\s+предоплаты\b",
    r"\bреквизиты\s+для\s+аванса\b",               # реквизиты для аванса?
    r"\bмгновенн[аы]е\s+платежи\b",
    r"\bаванс\s+мгновенно\b",                      # аванс мгновенно?
    r"\bаванс\s+мгновенные\b",                     # аванс мгновенные?
    r"\bаванс\s+maib\b",                          # аванс maib?
    r"\bаванс\s+счёт\b",                          # аванс счёт?
    r"\bаванс\s+счет\b",                          # аванс счет?
]
ADVANCE_METHOD_REGEX = re.compile("|".join(ADVANCE_METHOD_PATTERNS_RO + ADVANCE_METHOD_PATTERNS_RU), re.IGNORECASE)

_AMOUNT_HINT_RE = re.compile(r"\b(c[âa]t|suma|lei)\b|\d{2,}", re.IGNORECASE)

def _select_payment_message(lang: str, text: str) -> str:
    """
    Selector pentru tema 'plată':
      1) dacă e întrebare despre SUMA avansului -> 200 lei
      2) dacă e întrebare despre METODA de achitare -> detalii card
      3) altfel -> mesajul general despre plată
    """
    low = (text or "").lower()
    has_cyr = bool(CYRILLIC_RE.search(low))

    # 1) SUMA avansului (prioritar)
    if ADVANCE_AMOUNT_REGEX.search(low):
        return ADVANCE_TEXT_RU if has_cyr or lang == "RU" else ADVANCE_TEXT_RO

    # Guard: “avans”/„предоплат…/аванс” + (cât/sumă/lei/număr) -> tratează ca SUMĂ
    if ("avans" in low or "предоплат" in low or "аванс" in low) and _AMOUNT_HINT_RE.search(low):
        return ADVANCE_TEXT_RU if has_cyr or lang == "RU" else ADVANCE_TEXT_RO

    # 2) METODA de achitare (card/rechizite)
    if ADVANCE_METHOD_REGEX.search(low):
        return ADVANCE_METHOD_TEXT_RU if has_cyr or lang == "RU" else ADVANCE_METHOD_TEXT_RO

    # 3) General “cum se face achitarea?”
    return PAYMENT_TEXT_RU if has_cyr or lang == "RU" else PAYMENT_TEXT_RO


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
    """Anti-spam: o singură ofertă per user per conversație (o singură dată)."""
    if OFFER_SENT.get(sender_id):
        return False
    OFFER_SENT[sender_id] = True  # set BEFORE sending to prevent race conditions
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

# Normalizare RO (fără diacritice)
_DIAC_MAP = str.maketrans({"ă":"a","â":"a","î":"i","ș":"s","ţ":"t","ț":"t",
                           "Ă":"a","Â":"a","Î":"i","Ș":"s","Ţ":"t","Ț":"t"})
def _norm_ro(s: str) -> str:
    s = (s or "").lower().translate(_DIAC_MAP)
    s = re.sub(r"[^\w\s]", " ", s)   
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _detect_offer_lang(text: str) -> str | None:
    """
    'RO' / 'RU' dacă mesajul indică intenție de ofertă (preț/cataloage/detalii).
    Reguli:
      1) Match direct pe expresii compuse (RO_PRICE_REGEX / RU_PRICE_REGEX)
      2) Scor lexiconic clasic: (PRICE ∪ DETAIL) + PRODUCT
      3) Fallback-uri prietenoase pentru mesaje scurte / întrebări simple:
         - doar PRODUCT (ex: "modele?", "catalog") -> ofertă
         - doar PRICE (ex: "cât costă?", "цена?")  -> ofertă
    """
    if not text or not text.strip():
        return None

    has_cyr = bool(CYRILLIC_RE.search(text))
    low = (text or "").lower()
    low_clean = re.sub(r"[^\w\s]", " ", low)

    # RO normalize (fără diacritice) + tokenizare
    ro_norm = _norm_ro(text)
    ro_toks = set(ro_norm.split())

    # RU tokenizare simplă
    ru_toks = set(low_clean.split())

    # 1) Expresii compuse – ancore clare
    if has_cyr and RU_PRICE_REGEX.search(low):
        return "RU"
    if (not has_cyr) and RO_PRICE_REGEX.search(text):
        return "RO"

    # Câte cuvinte are mesajul (după normalizare)
    word_count = len((low_clean if has_cyr else ro_norm).split())

    # Întrebări scurte de preț (ex: "цена?", "cât costă?")
    if not has_cyr and _SHORT_PRICE_RO.search(text) and ("?" in text or word_count <= 4):
        return "RO"
    if has_cyr and _SHORT_PRICE_RU.search(low) and ("?" in text or word_count <= 4):
        return "RU"

    # 2) Scor lexiconic clasic: (PRICE ∪ DETAIL) + PRODUCT
    ro_has_price_or_detail = bool(ro_toks & (RO_PRICE_TERMS | RO_DETAIL_TERMS))
    ro_has_product         = bool(ro_toks & RO_PRODUCT_TERMS)

    ru_has_price_or_detail = bool(ru_toks & (RU_PRICE_TERMS | RU_DETAIL_TERMS))
    ru_has_product         = bool(ru_toks & RU_PRODUCT_TERMS)

    if has_cyr:
        if ru_has_price_or_detail and ru_has_product:
            return "RU"
    else:
        if ro_has_price_or_detail and ro_has_product:
            return "RO"

    # 3) Fallback-uri prietenoase pentru mesaje scurte / cu semnul întrebării

    # — doar PRODUCT (modele/catalog) => ofertă
    if not has_cyr and (ro_has_product) and (word_count <= 5 or "?" in text):
        return "RO"
    if has_cyr and (ru_has_product) and (word_count <= 6 or "?" in text):
        return "RU"

    # — doar PRICE/DETAIL, dacă e întrebare scurtă (ex: "și cât costă?")
    if not has_cyr and ro_has_price_or_detail and (word_count <= 5 or "?" in text):
        return "RO"
    if has_cyr and ru_has_price_or_detail and (word_count <= 6 or "?" in text):
        return "RU"

    # Ultima plasă: „detalii?/подробнее?”
    if (ro_toks & RO_DETAIL_TERMS) and ("?" in text or ro_has_product):
        return "RO"
    if (ru_toks & RU_DETAIL_TERMS) and ("?" in text or ru_has_product):
        return "RU"

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

def _send_dm_delayed(recipient_id: str, text: str, seconds: float | None = None) -> None:
    """
    Trimite DM cu întârziere fără să blocheze webhook-ul.
    Nu atinge antispam-ul: tu chemi funcția DOAR după ce ai trecut de guard-urile _should_*.
    """
    delay = seconds if seconds is not None else random.uniform(REPLY_DELAY_MIN_SEC, REPLY_DELAY_MAX_SEC)

    def _job():
        try:
            send_instagram_message(recipient_id, text[:900])
        except Exception as e:
            app.logger.exception("Delayed DM failed: %s", e)

    t = threading.Timer(delay, _job)
    t.daemon = True  # nu ține procesul în viață la shutdown
    t.start()

def _send_images_delayed(recipient_id: str, urls: list[str], seconds: float | None = None) -> None:
    """
    Trimite galeria de imagini cu întârziere fără să blocheze webhook-ul.
    """
    delay = seconds if seconds is not None else random.uniform(0.8, 1.6)

    def _job():
        try:
            send_instagram_images(recipient_id, urls)
        except Exception as e:
            app.logger.exception("Delayed images failed: %s", e)

    t = threading.Timer(delay, _job)
    t.daemon = True  # nu ține procesul în viață la shutdown
    t.start()

def _should_send_payment(sender_id: str, text: str) -> str | None:
    """
    'RU' / 'RO' dacă mesajul întreabă despre plată/avans (inclusiv SUMĂ sau METODĂ),
    cu anti-spam specific pe tip de întrebare. Altfel None.
    """
    if not text:
        return None

    now = time.time()
    # curățare TTL pentru toate tipurile
    for uid, ts in list(PAYMENT_GENERAL_REPLIED.items()):
        if now - ts > PAYMENT_TTL_SEC:
            PAYMENT_GENERAL_REPLIED.pop(uid, None)
    for uid, ts in list(ADVANCE_AMOUNT_REPLIED.items()):
        if now - ts > PAYMENT_TTL_SEC:
            ADVANCE_AMOUNT_REPLIED.pop(uid, None)
    for uid, ts in list(ADVANCE_METHOD_REPLIED.items()):
        if now - ts > PAYMENT_TTL_SEC:
            ADVANCE_METHOD_REPLIED.pop(uid, None)

    # Verifică tipul de întrebare și anti-spam specific (ordinea contează!)
    if ADVANCE_AMOUNT_REGEX.search(text):
        # Întrebare despre SUMA avansului (prioritate înaltă)
        last = ADVANCE_AMOUNT_REPLIED.get(sender_id, 0.0)
        if now - last < PAYMENT_TTL_SEC:
            return None
        ADVANCE_AMOUNT_REPLIED[sender_id] = now
        app.logger.info("[ADVANCE_AMOUNT_MATCH] sender=%s text=%r", sender_id, text)
        return "RU" if CYRILLIC_RE.search(text) else "RO"
    
    elif ADVANCE_METHOD_REGEX.search(text):
        # Întrebare despre METODA de achitare (prioritate înaltă)
        last = ADVANCE_METHOD_REPLIED.get(sender_id, 0.0)
        if now - last < PAYMENT_TTL_SEC:
            return None
        ADVANCE_METHOD_REPLIED[sender_id] = now
        app.logger.info("[ADVANCE_METHOD_MATCH] sender=%s text=%r", sender_id, text)
        return "RU" if CYRILLIC_RE.search(text) else "RO"
    
    elif PAYMENT_REGEX.search(text) or ADVANCE_REGEX.search(text):
        # Întrebare generală despre plată/avans (prioritate joasă)
        last = PAYMENT_GENERAL_REPLIED.get(sender_id, 0.0)
        if now - last < PAYMENT_TTL_SEC:
            return None
        PAYMENT_GENERAL_REPLIED[sender_id] = now
        app.logger.info("[PAYMENT_GENERAL_MATCH] sender=%s text=%r", sender_id, text)
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
                _send_dm_delayed(sender_id, msg_eta[:900])   
            except Exception as e:
                app.logger.exception("Failed to schedule ETA reply: %s", e)
            continue

        # --- LIVRARE (o singură dată) ---
        lang_del = _should_send_delivery(sender_id, text_in)
        if lang_del:
            try:
                msg_del = DELIVERY_TEXT_RU if lang_del == "RU" else DELIVERY_TEXT
                _send_dm_delayed(sender_id, msg_del[:900])   
            except Exception as e:
                app.logger.exception("Failed to schedule delivery reply: %s", e)
            continue

        # --- FOLLOW-UP — răspunde DOAR o dată ---
        lang_followup = _should_send_followup(sender_id, text_in)
        if lang_followup:
            reply = FOLLOWUP_TEXT_RU if lang_followup == "RU" else FOLLOWUP_TEXT_RO
            try:
                _send_dm_delayed(sender_id, reply[:900])     
            except Exception as e:
                app.logger.exception("Failed to schedule follow-up reply: %s", e)
            continue

        
        # --- PLATĂ / ACHITARE (o singură dată) ---
        lang_pay = _should_send_payment(sender_id, text_in)
        if lang_pay:
            try:
                msg_pay = _select_payment_message(lang_pay, text_in)
                _send_dm_delayed(sender_id, msg_pay[:900])
            except Exception as e:
                app.logger.exception("Failed to schedule payment/advance reply: %s", e)
            continue


        # Trigger ofertă (RO/RU) o singură dată per conversație
        lang = _detect_offer_lang(text_in)
        if lang and _should_send_offer(sender_id):
            offer = OFFER_TEXT_RU if lang == "RU" else OFFER_TEXT_RO
            try:
                _send_dm_delayed(sender_id, offer[:900])     
            except Exception as e:
                app.logger.exception("Failed to schedule offer: %s", e)
            
            # Galeria de imagini - o singură dată per conversație
            if not GALLERY_SENT.get(sender_id):
                media_list = OFFER_MEDIA_RU if lang == "RU" else OFFER_MEDIA_RO
                if PUBLIC_BASE_URL.startswith("https://") and all(u.endswith((".jpg",".jpeg",".png",".webp")) for u in media_list):
                    GALLERY_SENT[sender_id] = True  # set BEFORE scheduling
                    _send_images_delayed(sender_id, media_list, seconds=random.uniform(0.8, 1.6))
                else:
                    app.logger.warning("Skipping gallery: invalid PUBLIC_BASE_URL or media list")
            continue
        
        if "?" in text_in and len(text_in) <= 160:
            app.logger.info("[OFFER_INTENT_MISSING] %r", text_in)
        # AICI poți adăuga alte fluxuri viitoare, dacă e cazul
        # (momentan webhook-ul rămâne minimal pe DM)

    return jsonify({"ok": True}), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8080")), debug=False)