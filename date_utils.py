import re
from datetime import datetime
from dateutil import parser
from logger import logger

# Month names pattern
_MONTHS = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t|tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
_ORDINALS = re.compile(r'(\b\d{1,2})(st|nd|rd|th)\b', flags=re.I)

def _clean(text: str) -> str:
    t = text.strip()
    t = _ORDINALS.sub(r'\1', t)
    t = re.sub(r'\bnoon\b', '12:00 pm', t, flags=re.I)
    t = re.sub(r'\bmidnight\b', '12:00 am', t, flags=re.I)
    return t

# Concrete date patterns we accept
_PATTERNS = [
    # ISO YYYY-MM-DD
    re.compile(r'\b(20\d{2}-\d{1,2}-\d{1,2})\b'),
    # DD-MM-YYYY or DD/MM/YYYY
    re.compile(r'\b(\d{1,2}[/-]\d{1,2}[/-]20\d{2})\b'),
    # Month DD, YYYY  (e.g., September 30, 2027)
    re.compile(rf'\b{_MONTHS}\s+\d{{1,2}},\s*20\d{{2}}\b', re.I),
    # Month DD YYYY   (e.g., September 30 2027)
    re.compile(rf'\b{_MONTHS}\s+\d{{1,2}}\s+20\d{{2}}\b', re.I),
    # DD Month YYYY   (e.g., 30 September 2027)
    re.compile(rf'\b\d{{1,2}}\s+{_MONTHS}\s+20\d{{2}}\b', re.I),
    
    re.compile(r'\b(20\d{2}-\d{1,2}-\d{1,2})\b'),
    re.compile(r'\b(20\d{2}[/-]\d{1,2}[/-]\d{1,2})\b'),   # NEW: YYYY/MM/DD (or YYYY-MM-DD)
    re.compile(r'\b(\d{1,2}[/-]\d{1,2}[/-]20\d{2})\b'),
    re.compile(rf'\b{_MONTHS}\s+\d{{1,2}},\s*20\d{{2}}\b', re.I),
    re.compile(rf'\b{_MONTHS}\s+\d{{1,2}}\s+20\d{{2}}\b', re.I),
    re.compile(rf'\b\d{{1,2}}\s+{_MONTHS}\s+20\d{{2}}\b', re.I),

    ]

def _parse_to_iso(date_str: str) -> str | None:
    try:
        dt = parser.parse(date_str, dayfirst=True, fuzzy=True, default=datetime(2000,1,1))
        # Only accept years 2000..2099 to avoid weird parses
        if 2000 <= dt.year <= 2099:
            return dt.date().isoformat()
        return None
    except Exception:
        return None

def extract_date(text: str) -> str | None:
    """
    Return ISO YYYY-MM-DD ONLY if an explicit date substring is found.
    If no explicit date is present, return None (DO NOT default to today).
    """
    try:
        t = _clean(text)
        for pat in _PATTERNS:
            m = pat.search(t)
            if m:
                s = m.group(0)
                iso = _parse_to_iso(s)
                if iso:
                    return iso
        return None
    except Exception as e:
        logger.error(f"Date extraction error: {e}")
        return None

# Time patterns (HH:MM[:SS] with optional am/pm, or "7 pm")
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
    NOTE: This helper assumes BOTH parts are present and valid.
    Callers (router) must gate-keep and NOT pass missing values.
    """
    d = datetime.strptime(date_str, "%Y-%m-%d").date()
    return datetime.combine(d, time_obj)
