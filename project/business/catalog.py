import json
import os

CATALOG_PATH = os.path.join("data", "shop_catalog.json")

def load_catalog() -> dict:
    """Load catalog data from JSON file."""
    with open(CATALOG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def get_product_by_id(product_id: str, lang: str = "ro") -> dict:
    """Return product details by ID and language."""
    catalog = load_catalog()
    product = catalog.get(product_id)
    if not product:
        return {}
    return {
        "id": product_id,
        "name": product["name"].get(lang, product["name"]["ro"]),
        "price": product["price"],
        "template": product["template"].get(lang, product["template"]["ro"]),
        "tags": product.get("tags", [])
    }

def list_all_products(lang: str = "ro") -> list:
    """List all products with name and price in selected language."""
    catalog = load_catalog()
    return [
        {
            "id": pid,
            "name": data["name"].get(lang, data["name"]["ro"]),
            "price": data["price"]
        }
        for pid, data in catalog.items()
    ]

def search_product_by_text(text: str, lang: str = "ro") -> dict | None:
    """Search product by free text using tags."""
    catalog = load_catalog()
    low_text = text.lower()
    for pid, data in catalog.items():
        for tag in data.get("tags", []):
            if tag.lower() in low_text:
                return get_product_by_id(pid, lang)
    return None

def get_message_template(product_id: str, lang: str = "ro") -> str:
    """Return message template for product in selected language."""
    product = get_product_by_id(product_id, lang)
    return product.get("template", "")
