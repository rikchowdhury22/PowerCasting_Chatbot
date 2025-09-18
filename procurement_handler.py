import re
import requests
from datetime import datetime
from logger import logger
from nlp_setup import normalize
from urllib.parse import quote
from utils import fuzzy_match, ok, err
from rapidfuzz import process, fuzz

def handle_procurement_info(original_message, date_str, time_obj):
    try:
        start_timestamp = f"{date_str} {time_obj.strftime('%H:%M:%S')}"
        url = f"https://api.powercasting.online/procurement?start_date={quote(start_timestamp)}&price_cap=10"
        response = requests.get(url)

        if response.status_code != 200:
            return err("FETCH_FAILED", "Failed to fetch procurement data.",
                       intent="procurement", details={"timestamp": start_timestamp})

        data = response.json()
        all_plants = (data.get("Must_Run", []) or []) + (data.get("Remaining_Plants", []) or [])
        if not all_plants:
            return err("NO_DATA", "No procurement data available for the given time.",
                       intent="procurement", details={"timestamp": start_timestamp})

        # Compute Generated_Cost consistently
        for plant in all_plants:
            vc = plant.get("Variable_Cost", 0.0)
            gen = plant.get("generated_energy", 0.0)
            plant["Generated_Cost"] = round((vc or 0) * (gen or 0), 2)

        message = normalize(original_message)

        # Map user phrases -> API fields
        field_map = {
            # banking
            "banking": "Banking_Unit",
            "banking unit": "Banking_Unit",
            "banked": "Banking_Unit",
            "banked unit": "Banking_Unit",
            "banking contribution": "Banking_Unit",
            "demand banked": "Banking_Unit",
            "energy banked": "Banking_Unit",

            # energy
            "generated energy": "generated_energy",
            "energy generated": "generated_energy",
            "energy generation": "generated_energy",
            "energy": "generated_energy",

            # total cost
            "generated cost": "Generated_Cost",
            "generation cost": "Generated_Cost",
            "cost generated": "Generated_Cost",
            "cost generation": "Generated_Cost",

            # per-unit price
            "procurement price": "Last_Price",
            "last price": "Last_Price",
            "iex cost": "Last_Price",
            "power purchase cost": "Last_Price",
            "ppc": "Last_Price",
            "purchase cost": "Last_Price",
        }

        # Pre-sort keys once (longest first) to avoid partial shadowing
        _FIELD_KEYS = tuple(sorted(field_map.keys(), key=len, reverse=True))

        def _pick_field(message_norm: str) -> str | None:
            """
            Return the API field name ('Last_Price', 'generated_energy', etc.)
            from a normalized message. Tries exact (substring) first, then fuzzy.
            """
            # Exact (substring) match – longest keys first
            for k in _FIELD_KEYS:
                if k in message_norm:
                    return field_map[k]

            # Fuzzy partial match for small typos (e.g., 'purchse', 'bnking')
            best = process.extractOne(message_norm, _FIELD_KEYS, scorer=fuzz.partial_ratio)
            if best and best[1] >= 85:  # tolerance; tune 80–90 if needed
                return field_map[best[0]]

            return None

        message_norm = normalize(original_message)  # keep or add this line near the top
        requested_field = _pick_field(message_norm)

        if not requested_field:
            return err(
                "MISSING_PARAM",
                "Please specify what you need (e.g., 'procurement price' / 'ppc', 'generated energy', 'banking unit', or 'generated cost') along with date & time.",
                intent="procurement",
            )

        # Whole-payload field at top level?
        if requested_field in data:
            val = data[requested_field]
            text = f"{requested_field.replace('_',' ').capitalize()} at {start_timestamp}: {val}"
            return ok("procurement", {"text": text, "timestamp": start_timestamp,
                                      "field": requested_field, "value": val})

        # Per-plant query: "... by/for/of {plant}"
        match = re.search(r"(?:by|for|of)\s+([a-z0-9\s\-&/]+?)(?=\s+(?:on|at)\s+|[\?\.!]|$)", message)
        if match:
            plant_query = normalize(match.group(1).replace('/', ' '))
            for plant in all_plants:
                pname = plant.get("plant_name") or plant.get("name") or ""
                if fuzzy_match(normalize(pname), plant_query):
                    if requested_field not in plant:
                        return err("NO_DATA",
                                   f"{requested_field.replace('_',' ').capitalize()} not available for {pname} at {start_timestamp}.",
                                   intent="procurement",
                                   details={"plant": pname, "field": requested_field, "timestamp": start_timestamp})
                    val = plant[requested_field]
                    text = (f"{requested_field.replace('_',' ').capitalize()} for {pname} "
                            f"at {start_timestamp}: {val}")
                    return ok("procurement", {"text": text, "timestamp": start_timestamp,
                                              "plant": pname, "field": requested_field, "value": val})
            return err("PLANT_NOT_FOUND", f"No plant found matching '{match.group(1)}'.", intent="procurement")

        # Otherwise: compact list of values for the requested field
        rows = [{"plant": (p.get("plant_name") or p.get("name") or "Unknown Plant"),
                 "value": p.get(requested_field, "N/A")} for p in all_plants]
        return ok("procurement", {
            "text": f"{requested_field.replace('_',' ').capitalize()} values at {start_timestamp}",
            "timestamp": start_timestamp,
            "field": requested_field,
            "rows": rows
        })

    except Exception as e:
        logger.error(f"Procurement API error: {e}", exc_info=True)
        return err("INTERNAL", "Error fetching procurement data.", intent="procurement")
