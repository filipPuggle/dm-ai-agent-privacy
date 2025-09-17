from dataclasses import dataclass
from datetime import datetime, timedelta, time
from typing import Optional, List, Dict, Tuple
import re, math

try:
    import dateparser  # opțional
except Exception:
    dateparser = None

try:
    from zoneinfo import ZoneInfo  # Python 3.9+
except Exception:
    ZoneInfo = None

# ===================== CONFIG =====================

RO_TZ = "Europe/Chisinau"

DOW_RO_SHORT = ["Lun","Mar","Mie","Joi","Vin","Sâm","Dum"]
def _fmt_ro(dt: datetime) -> str:
    # ex: "Mie, 10.09 18:00"
    return f"{DOW_RO_SHORT[dt.weekday()]}, {dt.day:02d}.{dt.month:02d} {dt:%H:%M}"

FIELD_LABELS_RO = {
    "delivery_city": "orașul de livrare",
    "delivery": "metoda de livrare",
    "payment": "metoda de plată",
    "address": "adresa",
    "phone": "telefonul",
}

def _missing_human(fields: List[str]) -> str:
    human = [FIELD_LABELS_RO[f] for f in fields if f in FIELD_LABELS_RO]
    if not human:
        return ""
    if len(human) == 1:
        return human[0]
    return ", ".join(human[:-1]) + " și " + human[-1]

# Program atelier + curieri (doar zile lucrătoare)
WORKING_HOURS = {
    "start": time(9, 0),    # 09:00
    "end":   time(18, 0),   # 18:00
    "business_days": {0,1,2,3,4},  # Luni–Vineri
}

# Producție (zile lucrătoare)
SLA_CONFIG = {
    "lamp_simpla": {
        "production_business_days": 1,
        "rush_available": True,
        "rush_multiplier": 1.0,  # dacă ai taxă de urgență o poți folosi la preț, aici doar timpii
    },
    "lamp_dupa_poză": {
        "production_business_days": 2,
        "rush_available": True,
        "rush_multiplier": 1.2,
    },
}

# --- RO calendar words ---
MONTHS_RO = {
    "ianuarie":1,"februarie":2,"martie":3,"aprilie":4,"mai":5,"iunie":6,
    "iulie":7,"august":8,"septembrie":9,"octombrie":10,"noiembrie":11,"decembrie":12,
}
DOW_RO_SHORT = ["Lun","Mar","Mie","Joi","Vin","Sâm","Dum"]
def _fmt_ro(dt):  # înlocuiește strftime engleză
    return f"{DOW_RO_SHORT[dt.weekday()]}, {dt.day:02d}.{dt.month:02d} {dt:%H:%M}"


# Livrare (zile lucrătoare peste finis producție)
# min/max sunt *zile lucrătoare*, nu calendaristice
SHIPPING_SLA = {
    "balti":    {"min_days": 0, "max_days": 1, "label": "Curier Bălți (0–1 zile lucrătoare)"},
    "chisinau": {"min_days": 0, "max_days": 1, "label": "Curier Chișinău (0–1 zile lucrătoare)"},
    "md_alte":  {"min_days": 1, "max_days": 2, "label": "Curier Moldova (1–2 zile lucrătoare)"},
    "pickup":   {"min_days": 0, "max_days": 0, "label": "Ridicare personală (după finalizarea producției)"},
    "intl":     {"min_days": 3, "max_days": 7, "label": "Internațional (3–7 zile lucrătoare)"},
}
DEFAULT_CITY_KEY = "md_alte"

# ==================================================

DAY_NAMES_RO = {
    "luni":0, "marți":1, "marti":1, "miercuri":2, "joi":3, "vineri":4,
    "sâmbătă":5, "sambata":5, "duminică":6, "duminica":6
}
RELATIVE_WORDS = {
    r"\bazi\b":0, r"\bmâine\b|\bmaine\b":1, r"\bpoimâine\b|\bpoimaine\b":2,
}

@dataclass
class DeadlineResult:
    ok: bool
    reason: str
    requested_by: Optional[datetime]                 # ce a înțeles parserul din mesaj
    requested_effective: Optional[datetime]          # ajustat la L-V, 09–18
    earliest_delivery_range: Optional[Tuple[datetime, datetime]]
    chosen_shipping_label: Optional[str]
    missing_fields: List[str]
    debug: Dict[str, str]


# -------------- Utils timp lucrător --------------

def _now_tz() -> datetime:
    return datetime.now(ZoneInfo(RO_TZ)) if ZoneInfo else datetime.now()

def _is_business_day(dt: datetime) -> bool:
    return dt.weekday() in WORKING_HOURS["business_days"]

def _clone_with_time(dt: datetime, t: time) -> datetime:
    return dt.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)

def _next_business_start(dt: datetime) -> datetime:
    """Mută la următoarea fereastră de lucru (L-V, 09:00)."""
    start_t, end_t = WORKING_HOURS["start"], WORKING_HOURS["end"]
    cur = dt
    # du peste weekend
    while not _is_business_day(cur):
        cur = _clone_with_time(cur + timedelta(days=1), start_t)
    # aliniază în fereastra de program
    if cur.time() < start_t:
        cur = _clone_with_time(cur, start_t)
    elif cur.time() >= end_t:
        cur = _clone_with_time(cur + timedelta(days=1), start_t)
        while not _is_business_day(cur):
            cur = _clone_with_time(cur + timedelta(days=1), start_t)
    return cur

def _end_of_business(dt: datetime) -> datetime:
    end_t = WORKING_HOURS["end"]
    base = dt
    if not _is_business_day(base):
        base = _next_business_start(base)
    if base.time() > end_t:
        # next business day end-of-day
        base = _clone_with_time(_next_business_start(base + timedelta(days=1)), end_t)
    return _clone_with_time(base, end_t)

def _add_business_days(start: datetime, days: int, end_of_day: bool=True) -> datetime:
    """
    Adaugă N zile lucrătoare.
    Dacă end_of_day=True -> întoarce ora 18:00 în ultima zi lucrătoare.
    """
    cur = _next_business_start(start)
    remaining = max(0, int(days))
    while remaining > 0:
        if _is_business_day(cur):
            remaining -= 1
        cur = cur + timedelta(days=1)
    cur = cur - timedelta(days=1)
    return _end_of_business(cur) if end_of_day else _clone_with_time(cur, WORKING_HOURS["start"])

def _to_business_deadline(dt: datetime) -> Tuple[datetime, Optional[str]]:
    """
    Normalizează un deadline cerut de client la o limită validă (L-V, 09–18).
    - Dacă pică în weekend -> mută la următoarea zi lucrătoare 18:00.
    - Dacă e înainte de 09:00 -> îl ridică la 18:00 aceeași zi (considerăm termen până la finalul programului).
    - Dacă e după 18:00 -> mută la următoarea zi lucrătoare 18:00.
    """
    start_t, end_t = WORKING_HOURS["start"], WORKING_HOURS["end"]
    reason = None
    eff = dt

    if not _is_business_day(eff):
        eff = _clone_with_time(_next_business_start(eff), end_t)
        reason = "deadline_ajustat_weekend"
    else:
        if eff.time() < start_t:
            eff = _clone_with_time(eff, end_t)
            reason = "deadline_ajustat_dimineata"
        elif eff.time() > end_t:
            eff = _clone_with_time(_next_business_start(eff + timedelta(days=1)), end_t)
            reason = "deadline_ajustat_dupa_program"

    return eff, reason

# -------------- Parsing --------------

def _parse_with_dateparser(text: str, ref: datetime) -> Optional[datetime]:
    settings = {
        "PREFER_DATES_FROM": "future",
        "RELATIVE_BASE": ref,
        "RETURN_AS_TIMEZONE_AWARE": bool(ZoneInfo),
        "TIMEZONE": RO_TZ if ZoneInfo else None,
        "LANGUAGE_DETECTION_CONFIDENCE_THRESHOLD": 0.1,
    }
    return dateparser.parse(text, settings=settings, languages=["ro","ru","en"])

def _parse_ro_basic(text: str, ref: datetime) -> Optional[datetime]:
    t = text.lower().strip()

    for pat, offset in RELATIVE_WORDS.items():
        if re.search(pat, t):
            return ref + timedelta(days=offset)

    m = re.search(r"(în|peste)\s+(\d{1,2})\s+zile?", t)
    if m:
        return ref + timedelta(days=int(m.group(2)))
    
    m = re.search(r"\b(\d{1,2})\s+(ianuarie|februarie|martie|aprilie|mai|iunie|iulie|august|septembrie|octombrie|noiembrie|decembrie)(?:\s+(\d{4}))?\b", t)
    if m:
        d = int(m.group(1)); mo = MONTHS_RO[m.group(2)]
        year = int(m.group(3)) if m.group(3) else ref.year
        try:
            cand = datetime(year, mo, d, tzinfo=ZoneInfo(RO_TZ)) if ZoneInfo else datetime(year, mo, d)
            if cand < ref:
                cand = cand.replace(year=year + 1)
            return cand
        except Exception:
            pass

    for name, wk in DAY_NAMES_RO.items():
        if re.search(rf"\b{name}\b", t):
            base = ref
            days_ahead = (wk - base.weekday()) % 7
            if days_ahead == 0:
                days_ahead = 7
            if re.search(r"\bsăptămâna viitoare\b|\bsaptamana viitoare\b", t):
                days_ahead += 7 if days_ahead < 7 else 0
            return base + timedelta(days=days_ahead)

    m = re.search(r"\b(\d{1,2})[.\-/](\d{1,2})(?:[.\-/](\d{2,4}))?\b", t)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), m.group(3)
        year = int(y) if y else ref.year
        try:
            cand = datetime(year, mo, d, tzinfo=ZoneInfo(RO_TZ)) if ZoneInfo else datetime(year, mo, d)
            if cand < ref:
                cand = cand.replace(year=year + 1)
            return cand
        except Exception:
            pass
    return None

def parse_deadline(text: str, ref: Optional[datetime]=None) -> Optional[datetime]:
    """Extrage data-limită (dacă lipsește ora -> 18:00)."""
    ref = ref or _now_tz()
    dt = _parse_with_dateparser(text, ref) if dateparser else None
    if not dt:
        dt = _parse_ro_basic(text, ref)
    if not dt:
        return None
    # dacă nu s-a specificat ora -> consideră finalul zilei
    if dt.hour == 0 and dt.minute == 0 and dt.second == 0:
        dt = _clone_with_time(dt, WORKING_HOURS["end"])
    return dt

# -------------- Producție + Livrare --------------

def estimate_production_finish(now: datetime, product_key: str, rush: bool=False) -> datetime:
    cfg = SLA_CONFIG.get(product_key)
    days = cfg["production_business_days"] if cfg else 2
    if rush and cfg and cfg.get("rush_available"):
        days = max(1, math.ceil(days * 0.75))  # ajustează după realitatea ta
    start = _next_business_start(now)
    return _add_business_days(start, days, end_of_day=True)  # finalizează la 18:00, zi lucrătoare

def shipping_window_business(finish_dt: datetime, city_key: str) -> Tuple[datetime, datetime, str]:
    """
    Ferestră de livrare în *zile lucrătoare*, toate capetele la 18:00.
    """
    key = (city_key or DEFAULT_CITY_KEY).lower()
    data = SHIPPING_SLA.get(key, SHIPPING_SLA[DEFAULT_CITY_KEY])
    start = _add_business_days(finish_dt, data["min_days"], end_of_day=True)
    end   = _add_business_days(finish_dt, data["max_days"], end_of_day=True)
    return start, end, data["label"]

# -------------- Evaluare end-to-end --------------

def evaluate_deadline(
    user_text: str,
    product_key: str,
    delivery_city_hint: Optional[str] = None,
    rush_requested: bool = False,
) -> DeadlineResult:
    now = _now_tz()
    requested = parse_deadline(user_text, now)
    missing: List[str] = []
    dbg: Dict[str,str] = {}

    if not requested:
        return DeadlineResult(
            ok=False,
            reason="Nu am putut înțelege data limită din mesaj.",
            requested_by=None,
            requested_effective=None,
            earliest_delivery_range=None,
            chosen_shipping_label=None,
            missing_fields=["deadline_text"],
            debug={"parser":"none"},
        )

    # normalizează cererea clientului la o limită validă (L-V, 09–18)
    requested_eff, adjust_reason = _to_business_deadline(requested)
    if adjust_reason:
        dbg["requested_adjustment"] = adjust_reason
    dbg["requested_raw"] = requested.isoformat()
    dbg["requested_eff"] = requested_eff.isoformat()

    # producție
    finish = estimate_production_finish(now, product_key, rush=rush_requested)
    dbg["prod_finish"] = finish.isoformat()

    # city
    if delivery_city_hint:
        k = delivery_city_hint.lower()
        if "bălți" in k or "balti" in k: city_key = "balti"
        elif "chișinău" in k or "chisinau" in k: city_key = "chisinau"
        elif "pick" in k or "ridic" in k: city_key = "pickup"
        elif "intl" in k or "international" in k: city_key = "intl"
        else: city_key = DEFAULT_CITY_KEY
    else:
        city_key = DEFAULT_CITY_KEY
        missing.append("delivery_city")

    # livrare (zile lucrătoare)
    ship_start, ship_end, label = shipping_window_business(finish, city_key)
    dbg["ship_start"] = ship_start.isoformat()
    dbg["ship_end"]   = ship_end.isoformat()

    # decizie (comparam cu deadline-ul *efectiv*, valid L-V, 09–18)
    ok = ship_end <= requested_eff
    reason = "OK: putem livra până la termenul cerut (în program L-V)." if ok else \
             "NU reușim până la termenul cerut, ținând cont că livrările sunt L-V, 09:00–18:00."

    return DeadlineResult(
        ok=ok,
        reason=reason,
        requested_by=requested,
        requested_effective=requested_eff,
        earliest_delivery_range=(ship_start, ship_end),
        chosen_shipping_label=label,
        missing_fields=missing,
        debug=dbg,
    )

# -------------- Mesaj RO --------------

def format_reply_ro(res: DeadlineResult) -> str:
    """Mesaj compact, în română, fără placeholders; L–V 09–18."""
    def fmt(dt):
        return _fmt_ro(dt) if dt else ""

    # mapăm câmpurile lipsă pe etichete umane
    LABELS = {
        "delivery_city": "orașul de livrare",
        "delivery": "metoda de livrare",
        "payment": "metoda de plată",
        "address": "adresa",
        "phone": "telefonul",
    }
    def miss_to_text(missing):
        human = [LABELS.get(x, x) for x in (missing or [])]
        if not human:
            return ""
        return human[0] if len(human) == 1 else ", ".join(human[:-1]) + " și " + human[-1]

    # dacă nu avem deloc un termen înțeles
    if not res.requested_by:
        return ("Nu am reușit să înțeleg data-limită. "
                "Îmi poți scrie, te rog, data/ziua (ex: „miercuri”, „mâine”, „15.09”)?")

    lines: List[str] = []

    # --- când REUȘIM termenul ---
    if res.ok:
        lines.append(f"✅ Ne putem încadra în timp pentru data de: {fmt(res.requested_effective)} (Comenzile se produc doar în zile lucrătoare).")
        if res.earliest_delivery_range:
            a, b = res.earliest_delivery_range
            label = getattr(res, "chosen_shipping_label", "") or getattr(res, "delivery_method_hint", "")
            lines.append(f"📦 Produsul se estimează a fi livrat în intervalul : {fmt(a)} – {fmt(b)}" + (f" ({label})." if label else "."))
        miss = miss_to_text(res.missing_fields)
        if miss:
            lines.append(f"📝 Încă am nevoie de: {miss}.")
        return "\n".join(lines)

    # --- când NU reușim termenul ---
    lines.append("ℹ️ Livrările se fac în zile lucrătoare, 09:00–18:00.")
    lines.append(f"❌ Nu reușim până la {fmt(res.requested_by)}.")
    lines.append(f"✅ Cea mai rapidă opțiune: {fmt(res.requested_effective)}.")
    if res.earliest_delivery_range:
        a, b = res.earliest_delivery_range
        label = getattr(res, "chosen_shipping_label", "") or getattr(res, "delivery_method_hint", "")
        lines.append(f"📦 Estimare livrare: {fmt(a)} – {fmt(b)}" + (f" ({label})." if label else "."))
    lines.append("💡 Putem încerca *urgență* (cost suplimentar) sau *ridicare personală* imediat ce e gata.")
    miss = miss_to_text(res.missing_fields)
    if miss:
        lines.append(f"📝 Încă am nevoie de: {miss}.")
    return "\n".join(lines)