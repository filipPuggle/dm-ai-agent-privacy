# catalog.py
import json, re
from typing import List, Dict, Any

_CATALOG: Dict[str, Any] = {}

def load_catalog(path: str = "catalog.json") -> Dict[str, Any]:
    global _CATALOG
    if not _CATALOG:
        with open(path, "r", encoding="utf-8") as f:
            _CATALOG = json.load(f)
    return _CATALOG

def search_products(query: str, limit: int = 5) -> List[Dict[str, Any]]:
    cat = load_catalog()
    q = (query or "").lower()
    if not q.strip():
        return []
    scored = []
    for p in cat.get("products", []):
        hay = " ".join([
            p.get("sku",""), p.get("name",""), p.get("size",""),
            " ".join(p.get("tags", []))
        ]).lower()
        score = 0
        for token in re.findall(r"[a-z0-9]+", q):
            if token in hay:
                score += 1
        if score > 0:
            scored.append((score, p))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [p for _, p in scored[:limit]]
