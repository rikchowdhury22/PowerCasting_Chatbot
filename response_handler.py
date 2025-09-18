import os
import requests
from urllib.parse import urljoin
from datetime import datetime, timedelta

from logger import logger
from date_utils import build_timestamp
from utils import ok, err

# ---------------------------
# Config
# ---------------------------
POWCAST_API_BASE = os.getenv("POWCAST_API_BASE")  # REQUIRED
HTTP_TIMEOUT = float(os.getenv("POWCAST_HTTP_TIMEOUT", "10"))
IEX_WINDOW_MINUTES = int(os.getenv("IEX_WINDOW_MINUTES", "1"))
DEMAND_WINDOW_MINUTES = int(os.getenv("DEMAND_WINDOW_MINUTES", "1"))

# ---------------------------
# Helpers
# ---------------------------
DT_FMT_SEC = "%Y-%m-%d %H:%M:%S"
DT_FMT_MIN = "%Y-%m-%d %H:%M"

def fmt_sec(d: datetime) -> str: return d.strftime(DT_FMT_SEC)
def fmt_min(d: datetime) -> str: return d.strftime(DT_FMT_MIN)

def api_url(path: str) -> str:
    if not POWCAST_API_BASE:
        raise RuntimeError("POWCAST_API_BASE is not set. Export it or add to your .env.")
    base = POWCAST_API_BASE if POWCAST_API_BASE.endswith("/") else POWCAST_API_BASE + "/"
    return urljoin(base, path.lstrip("/"))

def api_get(path: str, params: dict):
    url = api_url(path)
    logger.debug(f"➡️ GET {url} | params={params}")
    resp = requests.get(url, params=params, timeout=HTTP_TIMEOUT)
    logger.debug(f"⬅️ {resp.status_code} {resp.text[:500] if resp.text else ''}")
    return resp

def _looks_empty_text(s: str) -> bool:
    return s.strip() in ("", "[]", "{}", "null", "Null", "NULL")

def _safe_json(resp):
    """
    Returns (ok, payload, no_data):
      - ok=False => fetch-fail (timeouts, 5xx, bad JSON with non-empty body, etc.)
      - ok=True & no_data=True => 'No data' (204/404/410 or empty body)
      - ok=True & no_data=False => payload is parsed JSON
    """
    try:
        # Treat empty or not-found responses as 'no data'
        if resp.status_code in (204, 404, 410):
            return True, None, True

        # Any other non-2xx is a fetch failure
        if not (200 <= resp.status_code < 300):
            return False, None, False

        try:
            payload = resp.json()
        except Exception:
            body = getattr(resp, "text", "") or ""
            # Empty-ish body? Consider it 'no data'
            if _looks_empty_text(body):
                return True, None, True
            # Non-empty but not JSON → fetch fail
            logger.error(f"JSON parse failed (2xx). Body preview: {body[:200]!r}")
            return False, None, False

        if payload is None: return True, None, True
        if isinstance(payload, (list, tuple)) and len(payload) == 0: return True, None, True
        if isinstance(payload, dict) and len(payload) == 0: return True, None, True
        return True, payload, False

    except Exception as e:
        logger.error(f"_safe_json unexpected error: {e}", exc_info=True)
        return False, None, False

def _extract_by_keys(obj, keys):
    """Walk dict / dict['data'] / list to find the first non-empty value for given keys."""
    def _is_missing(v):
        if v is None: return True
        if isinstance(v, str) and v.strip().lower() in {"", "nan", "none", "null"}:
            return True
        return False

    def _walk(x):
        if isinstance(x, dict):
            for k in keys:
                if k in x and not _is_missing(x[k]):
                    return x[k]
            d = x.get("data")
            if isinstance(d, list):
                for row in d:
                    v = _walk(row)
                    if v is not None: return v
            elif isinstance(d, dict):
                return _walk(d)
        elif isinstance(x, list):
            for row in x:
                v = _walk(row)
                if v is not None: return v
        return None

    return _walk(obj)

# ---------------------------
# Dynamic Response Handler (structured JSON)
# ---------------------------
def generate_response(intent, date_str, time_obj, original_message=""):
    try:
        ts = build_timestamp(date_str, time_obj)  # naive datetime used by your APIs

        def _success(metric: str, d: datetime, value, unit: str = "", source: str | None = None):
            unit = unit.strip()
            unit_suffix = f" {unit}" if unit else ""
            text = f"The {metric} at {d.strftime('%H:%M')} on {d.strftime('%Y-%m-%d')} is {value}{unit_suffix}."
            return ok(intent, {
                "text": text,
                "metric": metric,
                "timestamp": d.strftime("%Y-%m-%d %H:%M:%S"),
                "value": value,
                "unit": unit
            }, meta={"source": source} if source else None)

        def _not_found(metric: str, d: datetime):
            text = f"No {metric} data found for {d.strftime('%H:%M')} on {d.strftime('%Y-%m-%d')}."
            return err("NO_DATA", text, intent=intent,
                       details={"metric": metric, "timestamp": d.strftime("%Y-%m-%d %H:%M:%S")})

        def _fetch_fail(metric: str):
            return err("FETCH_FAILED", f"Failed to fetch {metric} data.", intent=intent,
                       details={"metric": metric})

        # ---------- MOD ----------
        if intent == "mod":
            metric = "MOD price"
            try:
                resp = api_get("/procurement", {"start_date": ts.strftime("%Y-%m-%d %H:%M:%S"), "price_cap": "10"})
                ok_json, payload, no_data = _safe_json(resp)
                if not ok_json: return _fetch_fail(metric)
                if no_data:     return _not_found(metric, ts)

                last_price = _extract_by_keys(payload, keys=("Last_Price","last_price","price","value","last_trade_price"))
                if last_price is None: return _not_found(metric, ts)

                try:
                    p = float(str(last_price).strip())
                    price_str = f"₹{p:.2f}".rstrip("0").rstrip(".")
                except Exception:
                    price_str = f"₹{last_price}"
                return _success(metric, ts, price_str, "per unit", source="procurement")
            except Exception as e:
                logger.error(f"{metric} API error: {e}", exc_info=True)
                return _fetch_fail(metric)

        # ---------- IEX (exact tick) ----------
        elif intent == "iex":
            metric = "IEX market rate"
            try:
                start_dt = ts.replace(second=0, microsecond=0)
                end_dt   = start_dt + timedelta(minutes=IEX_WINDOW_MINUTES or 1)
                resp = api_get("/iex/range", {"start_date": start_dt.strftime("%Y-%m-%d %H:%M"),
                                              "end_date":   end_dt.strftime("%Y-%m-%d %H:%M")})
                ok_json, payload, no_data = _safe_json(resp)
                if not ok_json: return _fetch_fail(metric)
                if no_data:     return _not_found(metric, start_dt)

                rows = (payload or {}).get("data", []) if isinstance(payload, dict) else payload or []
                exact = None
                for item in rows:
                    try:
                        api_ts = datetime.strptime(item["TimeStamp"], DT_FMT_SEC)
                        if api_ts == start_dt:
                            exact = item
                            break
                    except Exception as e:
                        logger.warning(f"IEX row skipped (timestamp parse): {e}")

                if exact is None: return _not_found(metric, start_dt)

                val = (exact.get("predicted") or exact.get("price") or exact.get("iex_price") or exact.get("mcp") or exact.get("value"))
                if val is None:   return _not_found(metric, start_dt)

                try:
                    v = float(str(val).strip())
                    val_str = f"₹{v:.2f}".rstrip("0").rstrip(".")
                except Exception:
                    val_str = f"₹{val}"
                return _success(metric, start_dt, val_str, "per unit", source="IEX")
            except Exception as e:
                logger.error(f"{metric} API error: {e}", exc_info=True)
                return _fetch_fail(metric)

        # ---------- Demand (next day same time, exact tick) ----------
        elif intent == "demand":
            metric = "demand"
            try:
                day_after = datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=1)
                target_ts = build_timestamp(day_after.strftime("%Y-%m-%d"), time_obj)

                start_dt = target_ts.replace(second=0, microsecond=0)
                end_dt   = start_dt + timedelta(minutes=DEMAND_WINDOW_MINUTES)

                resp = api_get("/demand/range", {"start_date": start_dt.strftime("%Y-%m-%d %H:%M:%S"),
                                                 "end_date":   end_dt.strftime("%Y-%m-%d %H:%M:%S")})
                ok_json, payload, no_data = _safe_json(resp)
                if not ok_json: return _fetch_fail(metric)
                if no_data:     return _not_found(metric, start_dt)

                if isinstance(payload, dict):
                    rows = payload.get("demand")
                    if rows is None:
                        rows = payload.get("data", [])
                else:
                    rows = payload or []

                exact = None
                for item in rows:
                    try:
                        api_ts = datetime.strptime(item["TimeStamp"], DT_FMT_SEC)
                        if api_ts == start_dt:
                            exact = item
                            break
                    except Exception as e:
                        logger.warning(f"Demand row skipped (timestamp parse): {e}")

                if exact is None: return _not_found(metric, start_dt)

                def _pick(d, *keys):
                    for k in keys:
                        v = d.get(k)
                        if v not in (None, "", "null", "NaN"):
                            return v
                    return None

                def _num_str(x):
                    try:
                        n = float(str(x).strip())
                        return f"{n:.2f}".rstrip("0").rstrip(".")
                    except Exception:
                        return str(x)

                pred_raw   = _pick(exact, "predicted", "Demand(Pred)", "forecast", "value")
                actual_raw = _pick(exact, "actual", "Demand(Actual)", "observed")
                pred = _num_str(pred_raw) if pred_raw is not None else None
                act  = _num_str(actual_raw) if actual_raw is not None else None

                if pred is not None and act is not None:
                    return _success(metric, start_dt, f"Predicted: {pred} kWh & Actual: {act} kWh")
                if pred is not None:
                    return _success(metric, start_dt, f"{pred} kWh (predicted)")
                if act is not None:
                    return _success(metric, start_dt, f"{act} kWh (actual)")
                return _not_found(metric, start_dt)
            except Exception as e:
                logger.error(f"{metric} API error: {e}", exc_info=True)
                return _fetch_fail(metric)

        # ---------- Plant availability (exact tick) ----------
        elif intent in ("plant", "plant info", "plant availability"):
            metric = "plant availability"
            try:
                start_dt = ts.replace(second=0, microsecond=0)
                end_dt   = start_dt + timedelta(minutes=DEMAND_WINDOW_MINUTES if "DEMAND_WINDOW_MINUTES" in globals() else 1)

                resp = api_get("/plant/range", {"start_date": start_dt.strftime("%Y-%m-%d %H:%M:%S"),
                                                "end_date":   end_dt.strftime("%Y-%m-%d %H:%M:%S")})
                ok_json, payload, no_data = _safe_json(resp)
                if not ok_json: return _fetch_fail(metric)
                if no_data:     return _not_found(metric, start_dt)

                if isinstance(payload, dict):
                    rows = payload.get("plant")
                    if rows is None:
                        rows = payload.get("data", [])
                else:
                    rows = payload or []

                exact = None
                for item in rows:
                    try:
                        api_ts = datetime.strptime(item["TimeStamp"], DT_FMT_SEC)
                        if api_ts == start_dt:
                            exact = item
                            break
                    except Exception as e:
                        logger.warning(f"Plant row skipped (timestamp parse): {e}")

                if exact is None: return _not_found(metric, start_dt)

                def _pick(d, *keys):
                    for k in keys:
                        v = d.get(k)
                        if v not in (None, "", "null", "NaN"):
                            return v
                    return None

                avail_raw = _pick(exact, "availability","Availability","PlantAvailability",
                                  "availability_percent","Availability(%)","percent","value")
                if avail_raw is None: return _not_found(metric, start_dt)

                # normalize to percentage string
                try:
                    valf = float(str(avail_raw).strip().rstrip("%"))
                    pct  = valf * 100.0 if 0.0 <= valf <= 1.0 else valf
                    pct_str = f"{pct:.2f}".rstrip("0").rstrip(".")
                except Exception:
                    s = str(avail_raw).strip().rstrip("%")
                    try:
                        pct = float(s)
                        pct_str = f"{pct:.2f}".rstrip("0").rstrip(".")
                    except Exception:
                        pct_str = s
                return _success(metric, start_dt, f"{pct_str}%", "")
            except Exception as e:
                logger.error(f"{metric} API error: {e}", exc_info=True)
                return _fetch_fail(metric)

        # ---------- Fallback ----------
        return err("UNSUPPORTED_INTENT", "Sorry, I don't have data for that request.", intent=intent)

    except Exception as e:
        logger.error(f"generate_response error: {e}", exc_info=True)
        return err("INTERNAL", "Internal error while processing the request.", intent=intent)
