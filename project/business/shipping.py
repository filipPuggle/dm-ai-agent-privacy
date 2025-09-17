from typing import Optional

# Reguli de livrare organizate pe zone
SHIPPING_RULES = {
    "chisinau": {
        "default": (
            "Putem livra prin curier\n\n"
            "Livrează timp de o zi lucrătoare \n\n"
            "Direct la adresa comodă\n\n"
            "Sună și se înțelege din timp\n\n"
            "Livrarea e 65 lei\n\n"
            "La fel din Chișinău este posibilă preluarea comenzii din oficiu \n\n"
            "str.Feredeului 4/4 \n\n"
            "În intervalul orelor 9:00-16:00\n\n"
            "Cum vă este mai comod ? \n"
            "Cu livrare sau preluare din oficiu?"
        ),
        "delivery_only": (
            "Putem livra prin curier\n\n"
            "Livrează timp de o zi lucrătoare \n\n"
            "Direct la adresa comodă\n\n"
            "Sună și se înțelege din timp\n\n"
            "Livrarea e 65 lei"
        ),
        "pickup_only": (
            "Este posibilă preluarea comenzii din oficiu \n\n"
            "str.Feredeului 4/4 \n\n"
            "În intervalul orelor 9:00-16:00\n\n"
        ),
    },

    "balti": {
        "default": (
            "Putem livra prin curier\n\n"
            "Livrează timp de o zi lucrătoare \n\n"
            "Direct la adresa comodă\n\n"
            "Sună și se înțelege din timp\n\n"
            "Livrarea e 65 lei"
        )
    },

    "other": {
        "default": (
            "Putem livra produsul prin \npoștă sau curier \n\n"
            "Prin poștă ajunge timp de 3 zile lucrătoare, achitarea se face la primire cash - 65 lei livrarea \n\n"
            "Prin curier timp de o zi lucrătoare \n\n"
            "Plata pentru produs se realizează prealabil (pe card bancar)\n"
            "68 lei livrarea\n\n"
            "Cum am trebui să livrăm produsul?"
        )
    },

    "terms_delivery_intro": (
        "Lucrarea se elaborează timp de 3-4 zile lucrătoare\n\n"
        "Livrarea durează de la o zi până la trei zile independent de metodă și locație \n\n"
        "Ați avea nevoie de produs pentru o anumită dată ?\n\n"
        "Unde va trebui de livrat produsul?"
    ),
}


def get_shipping_message(zone: str, key: str = "default") -> Optional[str]:
    """
    Returnează mesajul de livrare corespunzător în funcție de zonă și cheie.
    Exemple:
        get_shipping_message("chisinau")
        get_shipping_message("chisinau", "pickup_only")
        get_shipping_message("balti")
        get_shipping_message("other")
    """
    rules = SHIPPING_RULES.get(zone)
    if isinstance(rules, dict):
        return rules.get(key)
    return rules  # pentru cazurile când valoarea e direct string (ex: terms_delivery_intro)


def get_shipping_by_city(city: str) -> str:
    """
    Returnează mesajul de livrare corect în funcție de localitate.
    """
    if not city:
        return SHIPPING_RULES["other"]["default"]

    low = city.lower()
    if "chișinău" in low or "chisinau" in low:
        return SHIPPING_RULES["chisinau"]["default"]
    elif "bălți" in low or "balti" in low:
        return SHIPPING_RULES["balti"]["default"]
    else:
        return SHIPPING_RULES["other"]["default"]
