# banking_handler.py
import os
from datetime import datetime, timedelta
from urllib.parse import urljoin
import requests

from logger import logger
from utils import ok, err, cache_get, cache_set  # <-- cache helpers

POWCAST_API_BASE = os.getenv("POWCAST_API_BASE")
HTTP_TIMEOUT = float(os.getenv("POWCAST_HTTP_TIMEOUT", "10"))
BANKING_WINDOW_MINUTES = int(os.getenv("BANKING_WINDOW_MINUTES", "15"))

DT_FMT_MIN = "%Y-%m-%d %H:%M"
DT_FMT_SEC = "%Y-%m-%d %H:%M:%S"

def _api_url(path: str) -> str:
    if not POWCAST_API_BASE:
        raise RuntimeError("POWCAST_API_BASE is not set. Add it to your .env.")
    base = POWCAST_API_BASE if POWCAST_API_BASE.endswith("/") else POWCAST_API_BASE + "/"
    return urljoin(base, path.lstrip("/"))

def _snap_time_to_minutes(t: datetime, minutes: int) -> datetime:
    if minutes <= 1:
        return t.replace(second=0, microsecond=0)
    total = t.hour * 60 + t.minute
    snapped = (total // minutes) * minutes
    return t.replace(hour=snapped // 60, minute=snapped % 60, second=0, microsecond=0)

def _looks_empty(s: str) -> bool:
    return (s or "").strip().lower() in {"", "[]", "{}", "null", "none"}

def _fetch_rows_for(ts_minute: datetime):
    """Fetch rows for the exact snapped minute; return list (possibly empty)."""
    start = ts_minute.strftime(DT_FMT_MIN)
    end   = ts_minute.strftime(DT_FMT_MIN)

    # cache hit?
    ck = f"banking:{start}"
    cached = cache_get(ck)
    if cached is not None:
        return cached, start  # cached is already parsed rows (list)

    url = _api_url("/consolidated-part/all")
    params = {"start_date": start, "end_date": end}
    logger.debug(f"➡️ GET {url} | params={params}")
    resp = requests.get(url, params=params, timeout=HTTP_TIMEOUT)
    body = (resp.text or "")[:500]
    logger.debug(f"⬅️ {resp.status_code} {body}")

    rows = []
    if resp.status_code in (204, 404, 410):
        cache_set(ck, rows, ttl_sec=BANKING_WINDOW_MINUTES * 60)
        return rows, start
    if not (200 <= resp.status_code < 300):
        # don't cache hard failures
        raise RuntimeError(f"HTTP {resp.status_code} for banking {start}")

    try:
        payload = resp.json()
    except Exception:
        if _looks_empty(getattr(resp, "text", "")):
            cache_set(ck, rows, ttl_sec=BANKING_WINDOW_MINUTES * 60)
            return rows, start
        raise RuntimeError("Invalid JSON for banking")

    if isinstance(payload, dict):
        rows = payload.get("data") or []
    elif isinstance(payload, list):
        rows = payload
    else:
        rows = []

    cache_set(ck, rows, ttl_sec=BANKING_WINDOW_MINUTES * 60)
    return rows, start

def _extract_fields(rec: dict):
    def _pick(d, *keys, default=0):
        for k in keys:
            v = d.get(k)
            if v not in (None, "", "null", "NaN"):
                return v
        return default
    return {
        "adjusted_units":     _pick(rec, "adjusted_units"),
        "adjustment_charges": _pick(rec, "adjustment_charges"),
        "banked_units":       _pick(rec, "banked_units", "banking_units"),
        "banking_cost":       _pick(rec, "banking_cost"),
    }

def handle_banking_info(date_str: str, time_obj, original_message: str):
    """
    Returns a unified payload:
      intent=banking
      data: { text, timestamp, adjusted_units, adjustment_charges, banked_units, banking_cost }
    Smart-retries previous block if exact minute has no data.
    """
    try:
        # 1) Build snapped timestamp
        ts = datetime.strptime(f"{date_str} {time_obj.strftime('%H:%M:%S')}", DT_FMT_SEC)
        ts = _snap_time_to_minutes(ts, BANKING_WINDOW_MINUTES)

        # 2) First attempt: exact snapped minute
        rows, used_start = _fetch_rows_for(ts)
        used_ts = datetime.strptime(used_start, DT_FMT_MIN)

        # 3) Smart retry: previous block if empty
        retried = False
        if not rows:
            prev_ts = ts - timedelta(minutes=BANKING_WINDOW_MINUTES)
            rows, used_start = _fetch_rows_for(prev_ts)
            used_ts = datetime.strptime(used_start, DT_FMT_MIN)
            retried = True

        if not rows:
            hint = (f"Try a nearby block like "
                    f"{(ts - timedelta(minutes=BANKING_WINDOW_MINUTES)).strftime('%H:%M')} "
                    f"or {(ts + timedelta(minutes=BANKING_WINDOW_MINUTES)).strftime('%H:%M')}.")
            return err("NO_DATA",
                       f"No banking data found for {ts.strftime(DT_FMT_MIN)}. {hint}",
                       intent="banking",
                       details={"timestamp": ts.strftime(DT_FMT_MIN)})

        # 4) We expect one aggregate row per minute
        rec = rows[0] if isinstance(rows, list) and rows else rows
        fields = _extract_fields(rec)

        suffix = f" (using previous block {used_ts.strftime('%H:%M')})" if retried else ""
        text = (
            f"Banking at {used_ts.strftime('%H:%M')} on {used_ts.strftime('%Y-%m-%d')}{suffix}: "
            f"Adjusted Units: {fields['adjusted_units']}, "
            f"Adjustment Charges: {fields['adjustment_charges']}, "
            f"Banked Units: {fields['banked_units']}, "
            f"Banking Cost: {fields['banking_cost']}"
        )

        return ok("banking", {
            "text": text,
            "timestamp": used_ts.strftime(DT_FMT_SEC),
            **fields
        })

    except Exception as e:
        logger.error(f"Banking API error: {e}", exc_info=True)
        return err("FETCH_FAILED", "Failed to fetch banking data.", intent="banking")
