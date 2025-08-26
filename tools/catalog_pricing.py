# catalog_pricing.py – robust path resolution for shop_catalog.json
import json, os
from dataclasses import dataclass
from typing import Dict, Iterable, Optional

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

def _find_catalog(path: Optional[str] = None) -> str:
    """
    Returnează calea existentă către shop_catalog.json.
    Ordine: arg -> env -> lângă acest fișier -> unul mai sus -> cwd.
    """
    candidates = [
        path,
        os.getenv("SHOP_CATALOG_PATH"),
        os.path.join(BASE_DIR, "shop_catalog.json"),
        os.path.abspath(os.path.join(BASE_DIR, "..", "shop_catalog.json")),
        os.path.join(os.getcwd(), "shop_catalog.json"),
    ]
    checked = []
    for p in candidates:
        if not p:
            continue
        ap = os.path.abspath(p)
        checked.append(ap)
        if os.path.isfile(ap):
            return ap
    raise FileNotFoundError(
        "shop_catalog.json not found. Looked in:\n- " + "\n- ".join(checked)
    )

def load_catalog(path: Optional[str] = None) -> Dict:
    with open(_find_catalog(path), "r", encoding="utf-8") as f:
        return json.load(f)

@dataclass(frozen=True)
class Product:
    id: str
    sku: str
    name: str
    price: float
    desc: str = ""
    templates: Dict[str, str] = None  # type: ignore

def _iter_products(c: Dict) -> Iterable[Product]:
    for p in c.get("products", []):
        yield Product(
            id=p.get("id", ""),
            sku=p.get("sku", ""),
            name=p.get("name", ""),
            price=float(p.get("price", 0)),
            desc=p.get("desc", ""),
            templates=p.get("templates", {}) or {},
        )

def _price_for(c: Dict, pid: str) -> Optional[float]:
    for p in _iter_products(c):
        if p.id == pid:
            return p.price
    return None

def format_initial_offer_multiline() -> str:
    c = load_catalog()
    tpl = (c.get("global_templates", {}) or {}).get("initial_multiline")
    p1 = int(_price_for(c, "P1") or 0)
    p2 = int(_price_for(c, "P2") or 0)
    if tpl:
        try:
            return tpl.format(p1=p1, p2=p2)
        except Exception:
            pass
    return (
        "Avem modele simple cum ar fi un ursuleț , inimi (la fel fiind personalizabile ) "
        f"la preț de {p1} lei\n\n"
        "Facem si lucrări la comandă, o lucrare în baza pozei poate ajunge la "
        f"{p2} lei\n\n"
        "Lămpile dispun de 16 culori si o telecomandă în set 🥰\n\n"
        "Primiți 6 luni garanție la toată electronica⚡\n\n"
        "Pentru ce tip de lampă ați opta ?"
    )

def format_catalog_overview() -> str:
    c = load_catalog()
    cur = c.get("currency", "MDL")
    lines = ["Avem în ofertă:\n"]
    for p in _iter_products(c):
        lines.append(f"• {p.name} — {int(p.price)} {cur}")
    lines.append("\nPentru ce variantă ați dori detalii?")
    return "\n".join(lines)

def format_product_detail(pid: str) -> str:
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
            return f"{p.name}: {int(p.price)} {cur}\n{p.desc}".strip()
    return "Nu găsesc produsul cerut."

def get_global_template(name: str) -> Optional[str]:
    c = load_catalog()
    tpl = (c.get("global_templates", {}) or {}).get(name)
    if not tpl:
        return None
    try:
        return tpl.format(
            p1=int(_price_for(c, "P1") or 0),
            p2=int(_price_for(c, "P2") or 0),
        )
    except Exception:
        return tpl

def search_product_by_text(text: str) -> Optional[Dict]:
    c = load_catalog()
    tags = c.get("classifier_tags", {}) or {}
    low = (text or "").lower()
    for pid, tag_list in tags.items():
        for t in tag_list:
            t_low = (t or "").lower()
            if t_low and t_low in low:
                for p in _iter_products(c):
                    if p.id == pid:
                        return {
                            "id": p.id,
                            "sku": p.sku,
                            "name": p.name,
                            "price": int(p.price),
                            "desc": p.desc,
                        }
    return None
