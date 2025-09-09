from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Optional, List, Dict
from zoneinfo import ZoneInfo

import re

try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None

RO_TZ = ZoneInfo("Europe/Chisinau")
WORK_START = 9
WORK_END = 18
DOW_RO_FULL = ["luni","marți","miercuri","joi","vineri","sâmbătă","duminică"]

def _to_ro(dt: datetime) -> datetime:
    return dt.astimezone(RO_TZ)

def _ro_now() -> datetime:
    return datetime.now(RO_TZ)

def _in_business_hours(dt: datetime) -> bool:
    d = _to_ro(dt)
    return d.weekday() < 5 and WORK_START <= d.hour < WORK_END

def _next_business_start(dt: datetime) -> datetime:
    d = _to_ro(dt)
    if d.hour >= WORK_END:
        d = d + timedelta(days=1)
    d = d.replace(hour=WORK_START, minute=0, second=0, microsecond=0)
    while d.weekday() >= 5:
        d = d + timedelta(days=1)
        d = d.replace(hour=WORK_START, minute=0, second=0, microsecond=0)
    return d

def _fmt_day_date_ro(dt: datetime) -> str:
    d = _to_ro(dt)
    return f"{DOW_RO_FULL[d.weekday()]}, {d.day:02d}.{d.month:02d}"

WORKING_HOURS = {
    "start": time(9, 0),    # 09:00
    "end":   time(18, 0),   # 18:00
    "business_days": {0,1,2,3,4},  # L-V
}

# Număr public (editabil în cod). Lasă-l cum e până îl înlocuiești tu.
PHONE_PUBLIC = "+373 62176586"

URGENT_KWS = [
    "urgent", "urgență", "urgentă", "rapid", "repede", "acum", "imediat",
    "critică", "critica", "grabă", "graba", "grabnic",
    "срочно", "очень срочно", "сейчас", "немедленно",
]

CALL_KWS = [
    "sună-mă", "suna-ma", "sunati-ma", "sunați-mă", "telefon", "apel",
    "nr", "număr", "numar", "whatsapp", "viber", "teleg", "telegram",
    "позвоните", "звонок", "телефон",
]

PHONE_REGEXES = [
    r"\+373\s?6\d{7}",          # +373 6xxxxxxx
    r"0\s?6\d{7}",              # 06xxxxxxx
    r"\+373\s?7\d{7}",          # dacă folosești și 7
    r"\+?\d[\d\s\-]{6,14}\d"    # fallback generic
]

@dataclass
class UrgentDecision:
    escalate: bool
    need_phone: bool
    when_call: datetime
    in_business_hours: bool
    phone_found: Optional[str]
    debug: Dict[str, str]
 
def _now_tz() -> datetime:
    return datetime.now(ZoneInfo(RO_TZ)) if ZoneInfo else datetime.now()

def _is_business_day(dt: datetime) -> bool:
    return dt.weekday() in WORKING_HOURS["business_days"]

def _in_business_hours(dt: datetime) -> bool:
    if not _is_business_day(dt):
        return False
    start, end = WORKING_HOURS["start"], WORKING_HOURS["end"]
    return start <= dt.time() <= end

def _next_business_start(dt: datetime) -> datetime:
    start_t = WORKING_HOURS["start"]
    cur = dt
    # dacă e weekend -> mută la Luni 09:00
    while not _is_business_day(cur):
        cur = cur + timedelta(days=1)
    # set la 09:00
    return cur.replace(hour=start_t.hour, minute=start_t.minute, second=0, microsecond=0)

def _extract_phone(text: str) -> Optional[str]:
    t = (text or "").strip()
    for rx in PHONE_REGEXES:
        m = re.search(rx, t)
        if m:
            # normalizează: scoate spații duble, păstrează + și cifre
            p = re.sub(r"[^\d+]", "", m.group(0))
            # formatează prietenos
            if p.startswith("+373") and len(p) >= 8:
                return "+373 " + p[4:]
            return p
    return None

def _has_kw(text: str, kws: List[str]) -> bool:
    t = (text or "").lower()
    return any(kw in t for kw in kws)

def detect_urgent_and_wants_phone(text: str) -> bool:
    """True dacă mesajul sugerează URGENȚĂ + dorește apel/telefon."""
    t = (text or "").lower()
    return _has_kw(t, URGENT_KWS) or (_has_kw(t, CALL_KWS))

def evaluate_urgent_handoff(text: str) -> UrgentDecision:
    now = _ro_now()
    in_hours = _in_business_hours(now)
    phone = _extract_phone(text)
    when = now if in_hours else _next_business_start(now)
    return UrgentDecision(
        escalate=True,
        need_phone=(phone is None),
        when_call=when,
        in_business_hours=in_hours,
        phone_found=phone,
        debug={"now": now.isoformat(), "in_hours": str(in_hours), "phone_found": str(phone)}
    )

def format_urgent_reply_ro(decision: UrgentDecision) -> str:
    """
    Mesaj scurt, uman. Zilele scrise complet (luni, marți, ...).
    Dacă suntem în program: "te sunăm în scurt timp".
    Dacă suntem în afara programului: "te contactăm la începutul programului, <zi, dd.mm> la 09:00".
    """
    now = _ro_now()
    if _in_business_hours(now):
        if decision.phone_found:
            return (
                f"Am notat URGENȚA și numărul {decision.phone_found}. "
                "Te sunăm în scurt timp. Dacă preferi, poți apela direct la +373 62176586."
            )
        else:
            return (
                "Am notat URGENȚA. Te sunăm în scurt timp. "
                "Lasă-mi, te rog, un număr de telefon sau sună direct la +373 62176586."
            )

    # în afara programului: revenim la începutul programului următor
    start = _next_business_start(now)
    when_str = f"{_fmt_day_date_ro(start)} la 09:00"

    if decision.phone_found:
        return (
            f"Am notat URGENȚA și numărul {decision.phone_found}. "
            f"Te contactăm la începutul programului, {when_str}. "
            "Dacă e mai comod, poți apela direct la +373 62176586."
        )
    else:
        return (
            f"Am notat URGENȚA. Te contactăm la începutul programului, {when_str}. "
            "Lasă-ne, te rog, un număr de telefon sau sună direct la +373 62176586."
        )