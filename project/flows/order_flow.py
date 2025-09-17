# app/flows/order_flow.py

from typing import Dict, Optional, Tuple
import re

from app.business.catalog import get_product_by_id, get_global_template
from app.business.pricing import calculate_price, format_price, get_base_price
from app.business.shipping import get_shipping_message, get_shipping_by_city
from app.business.validators import normalize_phone, validate_name

# !!! Pune în .env și citește de acolo în webhook/app root dacă dorești, dar aici lăsăm constantul tehnic
CONTACT_NUMBER = "+373 62176586"  # <- mută în .env dacă vrei

# ---------------------------
# Helpers (slot filling)
# ---------------------------

AFFIRM = {"da", "ok", "okay", "confirm", "confirmăm", "confirmam", "hai", "sigur", "yes", "bine"}
NEGATE = {"nu", "nu acum", "anulez", "stop", "mai târziu", "later"}

def _norm(s: Optional[str]) -> str:
    return (s or "").strip()

def _is_affirm(t: str) -> bool:
    low = (t or "").lower()
    return any(w in low for w in AFFIRM)

def _is_negate(t: str) -> bool:
    low = (t or "").lower()
    return any(w in low for w in NEGATE)

def _extract_phone_or_none(text: str) -> Optional[str]:
    p = normalize_phone(text)
    return p

def _maybe_name(text: str) -> Optional[str]:
    text = (text or "").strip()
    if not text or any(ch.isdigit() for ch in text):
        return None
    if validate_name(text):
        return text.title()
    # „Mă numesc Ion Popescu”
    m = re.search(r"(?:mă|ma)\s+numesc\s+([a-zA-Zăâîșț\-\s]{3,40})", text, flags=re.IGNORECASE)
    if m and validate_name(m.group(1).strip()):
        return m.group(1).strip().title()
    return None

def _looks_like_address(line: str) -> bool:
    l = (line or "").lower()
    return any(k in l for k in ("str", "str.", "bd", "bd.", "bloc", "ap", "ap.", "sc", "sc.", "nr")) and any(ch.isdigit() for ch in l)

def _fill_slots_from_text(slots: Dict, text: str) -> None:
    """
    Simplu: dintr-un mesaj liber încearcă să deduci phone / name / address / payment / delivery / city.
    City e lăsat pentru parse în alt layer; aici doar cele generale.
    """
    parts = [p.strip() for p in re.split(r"[\n•;,|]+", text or "") if p.strip()]
    if not parts:
        return
    for p in parts:
        if not slots.get("phone"):
            ph = _extract_phone_or_none(p)
            if ph:
                slots["phone"] = ph
                continue
        if not slots.get("name"):
            nm = _maybe_name(p)
            if nm:
                slots["name"] = nm
                continue
        if not slots.get("address") and _looks_like_address(p):
            slots["address"] = p.strip()
            continue
        low = p.lower()
        if not slots.get("payment"):
            if any(k in low for k in ("numerar", "cash", "ramburs")):
                slots["payment"] = "numerar"
            elif any(k in low for k in ("transfer", "card", "iban", "prepl", "prepay")):
                slots["payment"] = "transfer"
        if not slots.get("delivery"):
            if "curier" in low:
                slots["delivery"] = "curier"
            elif "poșt" in low or "post" in low:
                slots["delivery"] = "poștă"
            elif "oficiu" in low or "pick" in low or "preluare" in low:
                slots["delivery"] = "oficiu"

def _collect_prompt(slots: Dict, city_required: bool = True, chisinau_office_only: bool = False) -> str:
    """
    Construiește promptul de colectare în funcție de ce lipsește.
    - pentru 'oficiu' Chișinău cerem doar nume + telefon
    """
    need = []
    if not slots.get("name"):   need.append("• Nume complet")
    if not slots.get("phone"):  need.append("• Telefon")

    if chisinau_office_only:
        if not need:
            return "Datele sunt complete. Confirmăm?"
        return "Pentru a finaliza comanda mai avem nevoie de:\n" + "\n".join(need)

    if city_required and not slots.get("city"):
        need.append("• Localitatea")
    if not slots.get("address"):  need.append("• Adresa exactă")
    if not slots.get("delivery"): need.append("• Metoda de livrare (curier/poștă/oficiu)")
    if not slots.get("payment"):  need.append("• Metoda de plată (numerar/transfer)")

    if not need:
        return "Toate datele sunt complete. Confirmăm?"
    return "Pentru expedierea comenzii mai avem nevoie de:\n" + "\n".join(need)

# ---------------------------
# P3 (Neon) – handoff la om
# ---------------------------

def handle_neon_request(user_id: str, lang: str = "ro") -> str:
    """
    P3 necesită handoff la operator. Trimite template + opțiuni de contact.
    """
    product = get_product_by_id("P3", lang)
    msg = product.get("template", "")
    msg += "\n\n📞 Pentru detalii rapide ne puteți suna la: {phone}".format(phone=CONTACT_NUMBER)
    msg += "\nSau lăsați numărul dvs. aici și vă contactăm noi în scurt timp."
    return msg

# ---------------------------
# P1 – Lampă simplă
# ---------------------------

def p1_initial_offer(lang: str = "ro", is_repeat_client: bool = False, quantity: int = 1) -> str:
    """
    Returnează oferta pentru P1 folosind template-ul din catalog și regulile de preț.
    """
    base = get_base_price("P1") or 0
    total = calculate_price("P1", quantity=quantity, is_repeat_client=is_repeat_client) or base
    product = get_product_by_id("P1", lang)
    # Template-ul din catalog are placeholders {name} și {price}
    text = (product.get("template") or "") \
        .replace("{name}", product.get("name", "Lampă simplă")) \
        .replace("{price}", str(int(total)))  # afișăm totalul curent
    return text

def p1_terms_intro() -> str:
    """
    Trimite mesajul cu timpii de execuție + solicită localitatea.
    """
    return get_shipping_message("terms_delivery_intro") or ""

def p1_shipping_by_city(city: str) -> str:
    """
    După ce aflăm localitatea, oferim opțiunile de livrare potrivite.
    """
    return get_shipping_by_city(city)

def p1_start_collect(slots: Dict) -> str:
    """
    După ce clientul alege metoda (curier/poștă/oficiu), cerem datele necesare.
    Pentru Chișinău + oficiu: doar nume + telefon.
    """
    city = (slots.get("city") or "").lower()
    delivery = (slots.get("delivery") or "").lower()
    chisinau_office = (delivery == "oficiu") and ("chișinău" in city or "chisinau" in city)
    return _collect_prompt(slots, city_required=not chisinau_office, chisinau_office_only=chisinau_office)

def p1_collect_step(slots: Dict, user_text: str) -> Tuple[str, bool]:
    """
    Ingest un mesaj liber și completează sloturile.
    Returnează (mesaj_către_client, ready_for_confirm).
    """
    _fill_slots_from_text(slots, user_text)
    city = (slots.get("city") or "").lower()
    delivery = (slots.get("delivery") or "").lower()
    chisinau_office = (delivery == "oficiu") and ("chișinău" in city or "chisinau" in city)

    need_msg = _collect_prompt(slots, city_required=not chisinau_office, chisinau_office_only=chisinau_office)
    ready = need_msg.startswith("Toate datele sunt complete")
    if ready:
        # Recapitulare
        recap = []
        recap.append(f"• Nume: {slots.get('name')}")
        recap.append(f"• Telefon: {slots.get('phone')}")
        if not chisinau_office:
            recap.append(f"• Localitate: {slots.get('city')}")
            recap.append(f"• Adresă: {slots.get('address')}")
            recap.append(f"• Livrare: {slots.get('delivery')}")
            recap.append(f"• Plată: {slots.get('payment')}")
        else:
            recap.append("• Preluare: oficiu (Chișinău)")
        msg = "Recapitulare comandă:\n" + "\n".join(recap) + "\n\nTotul este corect?"
        return msg, True
    return need_msg, False

def p1_confirm_or_adjust(user_text: str, personalized: bool = False) -> Tuple[str, str]:
    """
    Primește răspunsul clientului (da/nu). Dacă e DA:
      - dacă produsul e personalizat -> anunță despre avans și trimite în handoff
      - dacă NU -> cere corecții și revine la collect
    Returnează ( mesaj, next_step ) unde next_step ∈ {"awaiting_prepay_proof", "collect", "handoff", "noop"}
    """
    if _is_affirm(user_text):
        if personalized:
            pay_msg = (
                "Perfect! Fiind un produs personalizat, e necesar un avans de 200 lei pentru confirmare.\n\n"
                "După transfer, expediați o poză a chitanței, pentru confirmare."
            )
            return pay_msg, "awaiting_prepay_proof"
        # Ne-personalizat: poți închide direct sau marca pentru operator
        return "Mulțumim! Un coleg va confirma expedierea în scurt timp. 💜", "handoff"
    if _is_negate(user_text):
        return "Spuneți-mi ce ar trebui corectat și ajustăm imediat.", "collect"
    return "Confirmăm comanda? (da/nu)", "noop"

# ---------------------------
# P2 – Lampă după poză
# ---------------------------

def p2_initial_offer(lang: str = "ro") -> str:
    """
    Trimite șablonul P2 (după poză).
    """
    product = get_product_by_id("P2", lang)
    price = calculate_price("P2", quantity=1, is_repeat_client=False) or (get_base_price("P2") or 0)
    text = (product.get("template") or "").replace("{price}", str(int(price)))
    return text

def p2_photo_received(lang: str = "ro") -> str:
    """
    După prima fotografie – confirmăm și trecem spre termeni + localitate.
    """
    confirm = get_global_template("photo_received_confirm") or "Am primit fotografia. Mulțumim!"
    ask = get_shipping_message("terms_delivery_intro") or ""
    return (confirm + "\n\n" + ask).strip()

def p2_shipping_by_city(city: str) -> str:
    """
    După localitate, oferim opțiunile corecte de livrare.
    """
    return get_shipping_by_city(city)

def p2_start_collect(slots: Dict) -> str:
    """
    Cerem datele necesare pentru expediere.
    """
    city = (slots.get("city") or "").lower()
    delivery = (slots.get("delivery") or "").lower()
    chisinau_office = (delivery == "oficiu") and ("chișinău" in city or "chisinau" in city)
    return _collect_prompt(slots, city_required=not chisinau_office, chisinau_office_only=chisinau_office)

def p2_collect_step(slots: Dict, user_text: str) -> Tuple[str, bool]:
    """
    Completează sloturile din mesajul liber; întoarce (mesaj, ready_for_confirm).
    """
    return p1_collect_step(slots, user_text)

def p2_confirm_or_adjust(user_text: str) -> Tuple[str, str]:
    """
    P2 este produs personalizat => la confirmare cerem avans + handoff.
    """
    return p1_confirm_or_adjust(user_text, personalized=True)

# ---------------------------
# Utilitare comune
# ---------------------------

def human_handoff_banner(lang: str = "ro") -> str:
    """
    Mesaj scurt de închidere automată + handoff la operator (orice produs).
    """
    base = {
        "ro": "Gata! Un coleg preia comanda și vă contactează cât de curând. Mulțumim! 💜",
        "ru": "Готово! Коллега свяжется с вами в ближайшее время. Спасибо! 💜",
        "en": "Done! A colleague will contact you shortly. Thank you! 💜",
    }
    return base.get(lang, base["ro"])
