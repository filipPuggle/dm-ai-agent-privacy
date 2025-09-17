from typing import Optional
from app.sendmessage import send_instagram_message
from app.business.shipping import get_shipping_message
from app.business.pricing import get_product_price

FAQ_MESSAGES = {
    "pricing": (
        "Prețurile sunt:\n"
        "• Lampă simplă – {p1} lei\n"
        "• Lampă după poză – {p2} lei\n\n"
    ),
    "delivery": (
        "Livrarea se face prin curier sau poștă 📦\n"
        "Timp: 1-3 zile lucrătoare\n"
        "Cost: de la 65 lei\n\n"
        "În Chișinău este posibilă și preluarea din oficiu."
    ),
    "terms": (
        "Realizarea unei lămpi durează 3-4 zile lucrătoare 🛠️\n"
        "În cazul comenzilor personalizate, timpul se confirmă împreună cu echipa noastră."
    ),
    "warranty": (
        "Toate produsele beneficiază de 6 luni garanție ⚡"
    ),
    "payment": (
        "Puteți achita în numerar la livrare (Chișinău, Bălți) 💵\n"
        "sau prin transfer bancar/card 💳 pentru comenzile în alte localități."
    )
}


def handle_faq(user_id: str, intent: str, city: Optional[str] = None) -> None:
    """
    Răspunde la întrebările frecvente (FAQ).
    - intent: tipul de întrebare detectată (pricing, delivery, terms, warranty, payment)
    """
    if intent == "pricing":
        msg = FAQ_MESSAGES["pricing"].format(
            p1=get_product_price("P1"),
            p2=get_product_price("P2")
        )
    elif intent == "delivery":
        msg = get_shipping_message("terms_delivery_intro")
    elif intent in FAQ_MESSAGES:
        msg = FAQ_MESSAGES[intent]
    else:
        msg = "Îmi cer scuze, nu am un răspuns pregătit la această întrebare."

    send_instagram_message(user_id, msg)
