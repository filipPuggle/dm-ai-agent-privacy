from app.business.catalog import get_product_by_id

def get_base_price(product_id: str) -> float | None:
    """Returnează prețul de bază al produsului (P1=650, P2=780)."""
    product = get_product_by_id(product_id, lang="ro")  # prețul e același indiferent de limbă
    return product.get("price")


def calculate_price(product_id: str, quantity: int = 1, is_repeat_client: bool = False) -> float | None:
    """
    Calculează prețul total ținând cont de reguli:
    - 10% reducere pentru clienți care au mai comandat înainte
    - 10% reducere pentru 2+ bucăți
    (se aplică o singură reducere, nu cumulativ)
    """
    base_price = get_base_price(product_id)
    if base_price is None:
        return None

    subtotal = base_price * quantity

    # Regulă: discount 10% dacă clientul a mai comandat
    if is_repeat_client:
        discount = 0.10
    # Regulă: discount 10% dacă cumpără 2+ bucăți
    elif quantity >= 2:
        discount = 0.10
    else:
        discount = 0.0

    final_price = subtotal * (1 - discount)
    return round(final_price, 2)


def format_price(amount: float, lang: str = "ro") -> str:
    """
    Formatează prețul pentru afișare în funcție de limbă.
    """
    if amount is None:
        return "N/A"

    if lang == "ro":
        return f"{amount} lei"
    elif lang == "ru":
        return f"{amount} леев"
    elif lang == "en":
        return f"{amount} MDL"
    else:
        return str(amount)
