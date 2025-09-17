import re
import requests
from logger import logger
from nlp_setup import normalize
from datetime import datetime
from utils import fuzzy_match, ok, err

PLANT_API_URL = "https://api.powercasting.online/plant/"  # trailing slash prevents 307

def _fmt_time(d: datetime) -> str: return d.strftime("%H:%M")
def _fmt_date(d: datetime) -> str: return d.strftime("%Y-%m-%d")

def _success(metric: str, plant: str, d: datetime, value_str: str):
    text = f"The {metric} for {plant} at {_fmt_time(d)} on {_fmt_date(d)} is {value_str}."
    return ok("plant_info", {
        "text": text,
        "metric": metric,
        "plant": plant,
        "timestamp": f"{_fmt_date(d)} {_fmt_time(d)}",
        "value": value_str,
        "unit": ""
    })

def _no_data(metric: str, plant: str, d: datetime):
    text = f"No {metric} data found for {plant} at {_fmt_time(d)} on {_fmt_date(d)}."
    return err("NO_DATA", text, intent="plant_info",
               details={"metric": metric, "plant": plant, "timestamp": f"{_fmt_date(d)} {_fmt_time(d)}"})

def _fetch_fail(metric: str):
    return err("FETCH_FAILED", f"Failed to fetch {metric} data.", intent="plant_info", details={"metric": metric})

FIELD_MAP = {
    "plf":                           ("PLF",             "PLF",                      "percent"),
    "plant load factor":             ("PLF",             "PLF",                      "percent"),
    "paf":                           ("PAF",             "PAF",                      "percent"),
    "plant availability factor":     ("PAF",             "PAF",                      "percent"),
    "variable cost":                 ("Variable_Cost",   "variable cost",            "currency_per_unit"),
    "var cost":                      ("Variable_Cost",   "variable cost",            "currency_per_unit"),
    "aux consumption":               ("Aux_Consumption", "auxiliary consumption",    "percent"),
    "auxiliary consumption":         ("Aux_Consumption", "auxiliary consumption",    "percent"),
    "aux usage":                     ("Aux_Consumption", "auxiliary consumption",    "percent"),
    "auxiliary usage":               ("Aux_Consumption", "auxiliary consumption",    "percent"),
    "max power":                     ("Max_Power",       "max power",                "mw"),
    "min power":                     ("Min_Power",       "min power",                "mw"),
    "rated capacity":                ("Rated_Capacity",  "rated capacity",           "mw"),
    "technical minimum":             ("Technical_Minimum","technical minimum",        "percent"),
    "type":                          ("Type",            "type",                     "raw"),
}

def _format_value(value, unit_type: str) -> str:
    def _to_float(v):
        try:
            return float(str(v).strip().rstrip("%").replace(",", ""))
        except Exception:
            return None

    if unit_type == "percent":
        f = _to_float(value)
        if f is None:
            return f"{str(value).strip().rstrip('%')}%"
        if 0.0 <= f <= 1.0:
            f = f * 100.0
        s = f"{f:.2f}".rstrip("0").rstrip(".")
        return f"{s}%"

    if unit_type == "currency_per_unit":
        f = _to_float(value)
        if f is None:
            return f"₹{value}"
        s = f"{f:.2f}".rstrip("0").rstrip(".")
        return f"₹{s} per unit"

    if unit_type == "mw":
        f = _to_float(value)
        if f is None:
            return f"{value} MW"
        s = f"{f:.2f}".rstrip("0").rstrip(".")
        return f"{s} MW"

    return str(value)

def _pick_requested_field(message_norm: str):
    for k, (api_key, label, unit_type) in FIELD_MAP.items():
        if k in message_norm:
            return api_key, label, unit_type
    return None, None, None

def _extract_plant_name(message_norm: str):
    m = re.search(r"(?:by|for|of)\s+([a-z0-9\s\-&/]+?)(?=\s+(?:on|at)\s+|[\?\.!]|$)", message_norm, re.IGNORECASE)
    return m.group(1).strip() if m else None

def handle_plant_info(date_str, time_obj, original_message):
    metric_fallback = "plant details"
    try:
        ts = datetime.strptime(f"{date_str} {time_obj.strftime('%H:%M:%S')}", "%Y-%m-%d %H:%M:%S")
        try:
            response = requests.get(PLANT_API_URL, timeout=10)
        except Exception as e:
            logger.error(f"Plant API network error: {e}", exc_info=True)
            return _fetch_fail(metric_fallback)

        if response.status_code == 404:
            body = (getattr(response, "text", "") or "").lower()
            if "no" in body and "data" in body and "found" in body:
                return _no_data(metric_fallback, "the requested plant", ts)
            return _fetch_fail(metric_fallback)
        if response.status_code == 204:
            return _no_data(metric_fallback, "the requested plant", ts)
        if not (200 <= response.status_code < 300):
            return _fetch_fail(metric_fallback)

        try:
            data = response.json()
        except Exception as e:
            body = (getattr(response, "text", "") or "")
            if body.strip() in ("", "[]", "{}", "null", "Null", "NULL"):
                return _no_data(metric_fallback, "the requested plant", ts)
            logger.error(f"Plant API JSON parse failed. Body preview: {body[:200]!r}", exc_info=True)
            return _fetch_fail(metric_fallback)

        all_plants = (data.get("must_run", []) or []) + (data.get("other", []) or [])
        if not all_plants:
            return _no_data(metric_fallback, "the requested plant", ts)

        message_norm = normalize(original_message)

        api_key, field_label, unit_type = _pick_requested_field(message_norm)
        if not api_key:
            return err("MISSING_PARAM",
                    "Please specify the parameter (e.g., PLF/PAF/variable cost/aux consumption) and the plant name.\n"
                    "Example: PLF of Koradi on 2025-09-12 at 10:00",
                    intent="plant_info")

        # ✅ NEW: support overview/list-all queries without plant name
        wants_overview = bool(re.search(r"\b(list|all|overview|summary|show all)\b", message_norm))
        mentions_plants = "plant" in message_norm or "plants" in message_norm
        if wants_overview or (mentions_plants and "of" not in message_norm and "for" not in message_norm and "by" not in message_norm):
            rows = []
            for p in all_plants:
                name = p.get("name") or p.get("plant_name") or "Unknown Plant"
                raw = p.get(api_key, None)
                val = _format_value(raw, unit_type) if raw not in (None, "", "null", "NaN") else "N/A"
                rows.append({"plant": name, "value": val})
            return ok("plant_info", {
                "text": f"{field_label.capitalize()} values at {_fmt_time(ts)} on {_fmt_date(ts)}",
                "metric": field_label,
                "timestamp": f"{_fmt_date(ts)} {_fmt_time(ts)}",
                "rows": rows
            })

        plant_query = _extract_plant_name(message_norm)
        if not plant_query:
            return err("PLANT_NAME_MISSING",
                       "Could not identify the plant name. Example: 'PLF of Koradi at 10:00 on 2025-09-12'.",
                       intent="plant_info")

        plant_query_norm = normalize(plant_query.replace('/', ' '))
        best = None
        for plant in all_plants:
            plant_name = plant.get("name", "Unknown Plant")
            if fuzzy_match(normalize(plant_name), plant_query_norm):
                best = plant
                break

        if not best:
            return err("PLANT_NOT_FOUND", f"No plant found matching '{plant_query}'.", intent="plant_info")

        plant_name = best.get("name", "Unknown Plant")
        if api_key not in best or best.get(api_key) in (None, "", "null", "NaN"):
            return _no_data(field_label, plant_name, ts)

        raw_value = best.get(api_key)
        value_str = _format_value(raw_value, unit_type)
        return _success(field_label, plant_name, ts, value_str)

    except Exception as e:
        logger.error(f"Error processing plant info: {e}", exc_info=True)
        return _fetch_fail(metric_fallback)
