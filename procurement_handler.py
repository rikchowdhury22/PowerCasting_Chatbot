# procurement_handler.py
from dotenv import load_dotenv

load_dotenv()
import os
import re
from datetime import datetime
import requests
from rapidfuzz import process, fuzz

from logger import logger
from nlp_setup import normalize
from utils import fuzzy_match, ok, err

PROCUREMENT_WINDOW_MINUTES = int(os.getenv("PROCUREMENT_WINDOW_MINUTES", "15"))


def _snap_time(time_obj, minutes: int):
    """Floor time to previous multiple of `minutes`."""
    if not time_obj or minutes <= 1:
        return time_obj
    total = time_obj.hour * 60 + time_obj.minute
    snapped = (total // minutes) * minutes
    return time_obj.replace(hour=snapped // 60, minute=snapped % 60, second=0, microsecond=0)


def _extract_all_plants(data: dict):
    """
    Accept both procurement payload shapes/casings:
      - {"Must_Run": [...], "Remaining_Plants": [...]}
      - {"must_run": [...], "other": [...]}
      - or {"data": [...]} (fallback)
    """
    if not isinstance(data, dict):
        return []
    mr = data.get("Must_Run") or data.get("must_run") or []
    rp = data.get("Remaining_Plants") or data.get("other") or []
    if isinstance(mr, list) or isinstance(rp, list):
        return (mr or []) + (rp or [])
    rows = data.get("data")
    return rows if isinstance(rows, list) else []


def handle_procurement_info(original_message, date_str, time_obj):
    try:
        # 1) Snap time to bucket
        time_obj = _snap_time(time_obj, PROCUREMENT_WINDOW_MINUTES)
        start_timestamp = f"{date_str} {time_obj.strftime('%H:%M:%S')}"

        # 2) Fetch
        base_url = "https://api.powercasting.online/procurement"
        params = {"start_date": start_timestamp, "price_cap": 10}
        try:
            response = requests.get(base_url, params=params, timeout=10)
        except Exception as e:
            logger.error(f"Procurement API network error: {e}", exc_info=True)
            return err("FETCH_FAILED", "Failed to fetch procurement data.",
                       intent="procurement",
                       details={"timestamp": start_timestamp, "reason": "network error"})

        # 3) Status handling
        if response.status_code in (204, 404, 410):
            return err("NO_DATA",
                       f"No procurement data found for {time_obj.strftime('%H:%M')} on {date_str}.",
                       intent="procurement",
                       details={"timestamp": start_timestamp})
        if not (200 <= response.status_code < 300):
            return err("FETCH_FAILED", "Failed to fetch procurement data.",
                       intent="procurement",
                       details={"timestamp": start_timestamp, "status": response.status_code})

        # 4) Parse JSON
        try:
            data = response.json()
        except Exception:
            return err("FETCH_FAILED", "Failed to fetch procurement data.",
                       intent="procurement",
                       details={"timestamp": start_timestamp, "reason": "invalid json"})

        if not data or (isinstance(data, dict) and not data) or (isinstance(data, list) and not data):
            return err("NO_DATA",
                       f"No procurement data found for {time_obj.strftime('%H:%M')} on {date_str}.",
                       intent="procurement",
                       details={"timestamp": start_timestamp})

        # 5) Build plant list safely
        all_plants = _extract_all_plants(data)
        # Compute Generated_Cost consistently if we have plants
        if isinstance(all_plants, list) and all_plants:
            for plant in all_plants:
                vc = plant.get("Variable_Cost", 0.0)
                gen = plant.get("generated_energy", 0.0)
                try:
                    plant["Generated_Cost"] = round((float(vc or 0) * float(gen or 0)), 2)
                except Exception:
                    plant["Generated_Cost"] = 0.0

        # 6) Field selection
        message_norm = normalize(original_message)

        field_map = {
            # banking
            "banking": "Banking_Unit", "banking unit": "Banking_Unit",
            "banked": "Banking_Unit", "banked unit": "Banking_Unit",
            "banking contribution": "Banking_Unit", "demand banked": "Banking_Unit",
            "energy banked": "Banking_Unit",

            # energy
            "generated energy": "generated_energy", "energy generated": "generated_energy",
            "energy generation": "generated_energy", "energy": "generated_energy",

            # total cost (derived)
            "generated cost": "Generated_Cost", "generation cost": "Generated_Cost",
            "cost generated": "Generated_Cost", "cost generation": "Generated_Cost",

            # per-unit price
            "procurement price": "Last_Price", "last price": "Last_Price",
            "power purchase cost": "Last_Price", "ppc": "Last_Price", "purchase cost": "Last_Price",
            "iex cost": "Last_Price",
        }
        field_keys = tuple(sorted(field_map.keys(), key=len, reverse=True))

        def _pick_field(msg_norm: str) -> str | None:
            for k in field_keys:
                if k in msg_norm:
                    return field_map[k]
            best = process.extractOne(msg_norm, field_keys, scorer=fuzz.partial_ratio)
            if best and best[1] >= 85:
                return field_map[best[0]]
            return None

        requested_field = _pick_field(message_norm)
        if not requested_field:
            return err("MISSING_PARAM",
                       "Please specify what you need (e.g., 'procurement price' / 'ppc', 'generated energy', 'banking unit', or 'generated cost') along with date & time.",
                       intent="procurement")

        # 7) If field is at top level (rare but supported)
        if isinstance(data, dict) and requested_field in data:
            val = data[requested_field]
            text = f"{requested_field.replace('_', ' ').capitalize()} at {start_timestamp}: {val}"
            return ok("procurement", {"text": text, "timestamp": start_timestamp,
                                      "field": requested_field, "value": val})

        # 8) Per-plant: look for "... by/for/of {plant}"
        m = re.search(r"(?:by|for|of)\s+([a-z0-9\s\-&/]+?)(?=\s+(?:on|at)\s+|[\?\.!]|$)", original_message, flags=re.I)
        if m and isinstance(all_plants, list) and all_plants:
            plant_query = normalize(m.group(1).replace('/', ' '))
            for plant in all_plants:
                pname = plant.get("plant_name") or plant.get("name") or ""
                if fuzzy_match(normalize(pname), plant_query):
                    if requested_field not in plant:
                        return err("NO_DATA",
                                   f"{requested_field.replace('_', ' ').capitalize()} not available for {pname} at {start_timestamp}.",
                                   intent="procurement",
                                   details={"plant": pname, "field": requested_field, "timestamp": start_timestamp})
                    val = plant[requested_field]
                    text = (f"{requested_field.replace('_', ' ').capitalize()} for {pname} "
                            f"at {start_timestamp}: {val}")
                    return ok("procurement", {"text": text, "timestamp": start_timestamp,
                                              "plant": pname, "field": requested_field, "value": val})

            return err("PLANT_NOT_FOUND", f"No plant found matching '{m.group(1)}'.", intent="procurement")

        # 9) Otherwise, compact list for the field
        if isinstance(all_plants, list) and all_plants:
            rows = [{"plant": (p.get("plant_name") or p.get("name") or "Unknown Plant"),
                     "value": p.get(requested_field, "N/A")} for p in all_plants]
            return ok("procurement", {
                "text": f"{requested_field.replace('_', ' ').capitalize()} values at {start_timestamp}",
                "timestamp": start_timestamp,
                "field": requested_field,
                "rows": rows
            })

        # If we reach here, we had a response but no rows matched any known shape
        return err("NO_DATA",
                   f"No procurement data found for {time_obj.strftime('%H:%M')} on {date_str}.",
                   intent="procurement",
                   details={"timestamp": start_timestamp})

    except Exception as e:
        logger.error(f"Procurement API error: {e}", exc_info=True)
        return err("INTERNAL", "Error fetching procurement data.", intent="procurement")
