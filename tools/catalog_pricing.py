# tools/catalog_pricing.py
import json, os
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Dict, Optional

# Rezolvăm cale absolută către <repo>/shop_catalog.json (fără ENV)
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
_DEFAULT_PATH = os.path.join(BASE_DIR, "shop_catalog.json")

@dataclass(frozen=True)
class Product:
    id: str
    sku: str
    name: str
    price: Decimal
    desc: str

@dataclass(frozen=True)
class Catalog:
    currency: str
    products: List[Product]
    offer_template_initial: str
    offer_template_ask_qty: str
    offer_template_ask_delivery: str
    classifier_tags: Dict[str, List[str]]

_cached: Optional["Catalog"] = None  # forward-ref prin string (nu folosim __future__)

def _to_decimal(x) -> Decimal:
    return x if isinstance(x, Decimal) else Decimal(str(x))

def load_catalog(path: str = _DEFAULT_PATH) -> Catalog:
    """Încarcă o singură dată catalogul din JSON și validează schema."""
    global _cached
    if _cached:
        return _cached
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict) or "products" not in data:
        raise ValueError(f"Catalog JSON invalid: missing 'products' at {path}")

    products = [
        Product(
            id=p["id"],
            sku=p["sku"],
            name=p["name"],
            price=_to_decimal(p["price"]),
            desc=p.get("desc", "")
        )
        for p in data["products"]
    ]

    _cached = Catalog(
        currency=data.get("currency", "MDL"),
        products=products,
        offer_template_initial=data["offer_text_templates"]["initial"],
        offer_template_ask_qty=data["offer_text_templates"]["ask_quantity"],
        offer_template_ask_delivery=data["offer_text_templates"]["ask_delivery"],
        classifier_tags=data.get("classifier_tags", {})
    )
    return _cached

# -------- API public --------

def list_products() -> List[Dict]:
    c = load_catalog()
    return [dict(id=p.id, sku=p.sku, name=p.name, price=str(p.price), desc=p.desc) for p in c.products]

def get_product(product_id: str) -> Optional[Dict]:
    c = load_catalog()
    for p in c.products:
        if p.id == product_id:
            return dict(id=p.id, sku=p.sku, name=p.name, price=str(p.price), desc=p.desc)
    return None

def search_product_by_text(query: str) -> Optional[Dict]:
    if not query:
        return None
    q = query.lower().strip()
    c = load_catalog()
    for p in c.products:
        if q in p.name.lower() or q in p.desc.lower():
            return dict(id=p.id, sku=p.sku, name=p.name, price=str(p.price), desc=p.desc)
    for pid, tags in c.classifier_tags.items():
        if any(q in t.lower() for t in tags):
            return get_product(pid)
    return None

def format_initial_offer() -> str:
    c = load_catalog()
    p1 = next(p for p in c.products if p.id == "P1")
    p2 = next(p for p in c.products if p.id == "P2")
    return c.offer_template_initial.format(p1=format_money(p1.price), p2=format_money(p2.price))

# -------- utilități monetare --------

def format_money(amount: Decimal) -> str:
    q = _to_decimal(amount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"{q.normalize():f}" if q == q.to_integral() else f"{q}"

def to_minor_units(amount: Decimal) -> int:
    return int((_to_decimal(amount) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))

def price_for(product_id: str, quantity: int = 1) -> Dict:
    if quantity < 1:
        raise ValueError("quantity trebuie >= 1")
    prod = get_product(product_id)
    if not prod:
        raise KeyError(f"Produs inexistent: {product_id}")
    unit = _to_decimal(prod["price"])
    subtotal = unit * quantity
    total = subtotal
    return {
        "currency": load_catalog().currency,
        "product_id": prod["id"],
        "qty": quantity,
        "unit_price": str(unit),
        "subtotal": str(subtotal),
        "total": str(total),
        "total_minor_units": to_minor_units(total)
    }
