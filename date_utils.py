import re
from datetime import datetime
from dateutil import parser
from logger import logger

# Month names pattern (for textual dates)
_MONTHS = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t|tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
_ORDINALS = re.compile(r'(\b\d{1,2})(st|nd|rd|th)\b', flags=re.I)

def _clean(text: str) -> str:
    t = (text or "").strip()
    t = _ORDINALS.sub(r'\1', t)
    t = re.sub(r'\bnoon\b', '12:00 pm', t, flags=re.I)
    t = re.sub(r'\bmidnight\b', '12:00 am', t, flags=re.I)
    return t

def _try_build(y: int, m: int, d: int):
    try:
        return datetime(y, m, d)
    except ValueError:
        return None

def extract_date(text: str) -> str | None:
    """
    Deterministic date extraction priority:
      1) YYYY-MM-DD or YYYY/MM/DD  -> strict Year-Month-Day
      2) DD-MM-YYYY or DD/MM/YYYY  -> strict Day-Month-Year
      3) Textual month forms (Month DD, YYYY / DD Month YYYY) via dateutil
    Returns ISO 'YYYY-MM-DD' or None.
    """
    try:
        t = _clean(text)

        # 1) YYYY-MM-DD or YYYY/MM/DD  (strict year-month-day)
        m = re.search(r'\b(20\d{2})[/-](\d{1,2})[/-](\d{1,2})\b', t)
        if m:
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            dt = _try_build(y, mo, d)
            if dt:
                return dt.date().isoformat()

        # 2) DD-MM-YYYY or DD/MM/YYYY  (strict day-month-year)
        m = re.search(r'\b(\d{1,2})[/-](\d{1,2})[/-](20\d{2})\b', t)
        if m:
            d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
            dt = _try_build(y, mo, d)
            if dt:
                return dt.date().isoformat()

        # 3) Textual month formats
        #    e.g., "September 30, 2027", "30 September 2027", "Sep 30 2027"
        m = re.search(rf'\b{_MONTHS}\s+\d{{1,2}},?\s+20\d{{2}}\b', t, re.I) or \
            re.search(rf'\b\d{{1,2}}\s+{_MONTHS}\s+20\d{{2}}\b', t, re.I)
        if m:
            dt = parser.parse(m.group(0), dayfirst=True, fuzzy=True, default=datetime(2000, 1, 1))
            if 2000 <= dt.year <= 2099:
                return dt.date().isoformat()

        # Nothing found
        return None
    except Exception as e:
        logger.error(f"Date extraction error: {e}")
        return None

# ---- Time extraction (unchanged) ----
_TIME_PATS = [
    re.compile(r'\b(\d{1,2}:\d{2}:\d{2})\s*([ap]\.?m\.?)?\b', re.I),
    re.compile(r'\b(\d{1,2}:\d{2})\s*([ap]\.?m\.?)?\b', re.I),
    re.compile(r'\b(\d{1,2})\s*([ap]\.?m\.?)\b', re.I),
]

def extract_time(text: str):
    """Return a datetime.time if found, else None. Supports 24h, am/pm, seconds, 'noon', 'midnight'."""
    try:
        t = _clean(text)
        for pat in _TIME_PATS:
            m = pat.search(t)
            if m:
                candidate = " ".join([p for p in m.groups() if p])
                dt = parser.parse(candidate)
                return dt.time().replace(microsecond=0)
        return None
    except Exception as e:
        logger.error(f"Time extraction error: {e}")
        return None

def build_timestamp(date_str: str, time_obj):
    """
    Combine to a naive datetime.
    Callers must ensure BOTH parts are present and valid.
    """
    d = datetime.strptime(date_str, "%Y-%m-%d").date()
    return datetime.combine(d, time_obj)
