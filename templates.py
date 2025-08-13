# templates.py

import json
from pathlib import Path
from typing import Dict, Any

ROOT = Path(__file__).resolve().parent
TEMPLATES_PATH = ROOT / "templates.json"

_cache: Dict[str, Any] = {}

def load() -> Dict[str, Any]:
    global _cache
    if _cache:
        return _cache
    with open(TEMPLATES_PATH, "r", encoding="utf-8") as f:
        _cache = json.load(f)
    return _cache

def detect_lang(text: str) -> str:
    if any("\u0400" <= ch <= "\u04FF" for ch in text):
        return "ru"
    return "ro"

def t(key: str, lang: str = "ro", **kwargs) -> str:
    data = load()
    node = data["templates"][key][lang]
    if isinstance(node, list):
        node = "\n".join(node)
    for k, v in (kwargs or {}).items():
        node = node.replace("{{" + k + "}}", str(v))
    return node

def policy(path: str):
    data = load()["policies"]
    cur = data
    for part in path.split("."):
        cur = cur[part]
    return cur
