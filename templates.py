import json

_TPL = {}

def load_templates(path="templates.json"):
    global _TPL
    if not _TPL:
        with open(path, "r", encoding="utf-8") as f:
            _TPL = json.load(f)
    return _TPL

def render(name: str, lang: str = "ro", **kw) -> str:
    cfg = load_templates()
    node = cfg.get("templates", {}).get(name, {})
    if isinstance(node, dict):
        texts = node.get(lang) or node.get("ro") or node.get("ru") or []
    else:
        texts = node or []
    text = " ".join(texts) if isinstance(texts, list) else str(texts)

    # injectează metadata (ex: currency) ca fallback
    meta = cfg.get("meta", {})
    kw.setdefault("currency", meta.get("currency", "MDL"))

    for k, v in kw.items():
        text = text.replace(f"{{{{{k}}}}}", str(v))

    return " ".join(text.split())
