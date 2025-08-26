import json, os
from dataclasses import dataclass
from typing import Dict, Iterable, Optional

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
CATALOG_PATH = os.path.join(BASE_DIR, "shop_catalog.json")

@dataclass(frozen=True)
class Product:
    id: str
    sku: str
    name: str
    price: float
    desc: str = ""
    templates: Dict[str,str] = None  # type: ignore

# ---------- catalog helpers ----------

def load_catalog(path: Optional[str] = None) -> Dict:
    """Load the shop catalog JSON as a dict."""
    p = path or CATALOG_PATH
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)

def _iter_products(c: Dict) -> Iterable[Product]:
    for p in c.get("products", []):
        yield Product(
            id=p.get("id",""),
            sku=p.get("sku",""),
            name=p.get("name",""),
            price=float(p.get("price", 0)),
            desc=p.get("desc",""),
            templates=p.get("templates",{}) or {}
        )

def _price_for(c: Dict, pid: str) -> Optional[float]:
    for p in _iter_products(c):
        if p.id == pid:
            return p.price
    return None

# ---------- public formatters ----------

def format_initial_offer_multiline() -> str:
    """Return the initial multi-line offer using prices from catalog."""
    c = load_catalog()
    tpl = (c.get("global_templates", {}) or {}).get("initial_multiline")
    if tpl:
        p1 = _price_for(c, "P1") or 0
        p2 = _price_for(c, "P2") or 0
        try:
            return tpl.format(p1=int(p1), p2=int(p2))
        except Exception:
            # fall back to a safe template if placeholders mismatch
            pass
    # Fallback hard-coded but using prices
    p1 = int(_price_for(c, "P1") or 0)
    p2 = int(_price_for(c, "P2") or 0)
    return (
        "Avem modele simple cum ar fi un ursuleț , inimi (la fel fiind personalizabile ) la preț de "
        f"{p1} lei\n\n"
        "Facem si lucrări la comandă, o lucrare în baza pozei poate ajunge la "
        f"{p2} lei\n\n"
        "Lămpile dispun de 16 culori si o telecomandă în set 🥰\n\n"
        "Primiți 6 luni garanție la toată electronica⚡\n\n"
        "Pentru ce tip de lampă ați opta ?"
    )

def format_catalog_overview() -> str:
    """One-line per product overview."""
    c = load_catalog()
    cur = c.get("currency", "MDL")
    lines = ["Avem în ofertă:\n"]
    for p in _iter_products(c):
        lines.append(f"• {p.name} — {int(p.price)} {cur}")
    lines.append("\nPentru ce variantă ați dori detalii?")
    return "\n".join(lines)

def format_product_detail(pid: str) -> str:
    """Return product-specific detail message using its template."""
    c = load_catalog()
    cur = c.get("currency", "MDL")
    for p in _iter_products(c):
        if p.id == pid:
            tpl = (p.templates or {}).get("detail_multiline")
            if tpl:
                try:
                    return tpl.format(name=p.name, price=int(p.price), currency=cur)
                except Exception:
                    pass
            # fallback
            return f"{p.name}: {int(p.price)} {cur}\n{p.desc}".strip()
    return "Nu găsesc produsul cerut."

def get_global_template(name: str) -> Optional[str]:
    """Return a global template with basic price interpolation if requested."""
    c = load_catalog()
    tpl = (c.get("global_templates", {}) or {}).get(name)
    if not tpl:
        return None
    # Provide price placeholders if present
    try:
        return tpl.format(
            p1=int(_price_for(c, "P1") or 0),
            p2=int(_price_for(c, "P2") or 0),
        )
    except Exception:
        return tpl

def search_product_by_text(text: str) -> Optional[Dict]:
    """Very small rule-based classifier using classifier_tags from catalog."""
    c = load_catalog()
    tags = c.get("classifier_tags", {}) or {}
    low = (text or "").lower()
    for pid, tag_list in tags.items():
        for t in tag_list:
            t_low = (t or "").lower()
            if t_low and t_low in low:
                # find the product object
                for p in _iter_products(c):
                    if p.id == pid:
                        return {
                            "id": p.id, "sku": p.sku, "name": p.name,
                            "price": int(p.price), "desc": p.desc
                        }
    return None