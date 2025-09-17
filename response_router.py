from static_qa import match_static_qa
from nlp_setup import preprocess, normalize
from plant_handler import handle_plant_info
from procurement_handler import handle_procurement_info
from intent_handler import get_intent
from response_handler import generate_response
from logger import logger
from date_utils import extract_date, extract_time
from datetime import datetime
from utils import ok, err

def get_response(user_input: str) -> dict:
    # 1) Static answers
    static = match_static_qa(user_input)
    if static:
        return ok("static", {"text": static})

    # 2) NLP preprocessing
    tokens, matched_keywords = preprocess(user_input)
    logger.debug(f"Tokens={tokens} | MatchedKeywords={matched_keywords}")

    # 3) Extract date/time once (explicit only; no silent defaults)
    date_str = extract_date(user_input)
    time_obj = extract_time(user_input)

    # ✅ Hard guard: if message clearly contains plant metrics, handle as plant_info
    norm = normalize(user_input)
    plant_markers = (
        "plf","paf","variable cost","aux consumption","max power","min power",
        "rated capacity","technical minimum","plant type","plant load factor","plant availability factor"
    )
    if any(m in norm for m in plant_markers):
        if not time_obj:
            time_obj = datetime.now().time().replace(second=0, microsecond=0)
        if not date_str:
            date_str = datetime.now().date().isoformat()
        return handle_plant_info(date_str, time_obj, user_input)

    # 4) Plant info (does NOT require strict date/time)
    plant_kw = {
        'plf','paf','variable cost','aux consumption','max power','min power',
        'rated capacity','technical minimum','type','maximum power','minimum power',
        'auxiliary consumption','plant load factor','plant availability factor','aux usage','auxiliary usage','var cost'
    }
    if any(k in matched_keywords for k in plant_kw):
        # Fill reasonable defaults for plant lookups only
        if not time_obj:
            time_obj = datetime.now().time().replace(second=0, microsecond=0)
        if not date_str:
            date_str = datetime.now().date().isoformat()
        return handle_plant_info(date_str, time_obj, user_input)

    # 5) Procurement (requires BOTH date & time)
    procurement_kw = {
    "banking","banking unit","banked","energy generated","banked unit",
    "banking contribution","generated energy","procurement price","energy",
    "demand banked","cost generated","generated cost","generation cost",
    "power purchase cost","ppc","purchase cost","last price"  # <-- add
    }
    if any(k in matched_keywords for k in procurement_kw):
        if not (date_str and time_obj):
            return err("MISSING_DATE_OR_TIME",
                       "Include BOTH a date (YYYY-MM-DD or '30 September 2027') and time (HH:MM).",
                       intent="procurement")
        return handle_procurement_info(user_input, date_str, time_obj)

    # 6) IEX / MOD / Demand / Cost per block (requires BOTH)
    intent = get_intent(tokens, user_input)

    # ✅ Plant info does NOT require explicit date/time (auto-fill)
    if intent == "plant_info":
        if not time_obj:
            time_obj = datetime.now().time().replace(second=0, microsecond=0)
        if not date_str:
            date_str = datetime.now().date().isoformat()
        return handle_plant_info(date_str, time_obj, user_input)
    
    # Handle procurement by intent (not just keyword set)
    if intent == "procurement":
        if not (date_str and time_obj):
            return err("MISSING_DATE_OR_TIME",
                    "Include BOTH a date (YYYY-MM-DD or '30 September 2027') and time (HH:MM).",
                    intent="procurement")
        return handle_procurement_info(user_input, date_str, time_obj)


    if intent in {"iex", "mod", "demand", "cost per block"}:
        if not (date_str and time_obj):
            return err("MISSING_DATE_OR_TIME",
                    "Include BOTH a date (YYYY-MM-DD or '30 September 2027') and time (HH:MM).",
                    intent=intent)
        return generate_response(intent, date_str, time_obj)

    # ✅ NEW: second-pass heuristic for procurement-style phrases
    norm = normalize(user_input)
    _proc_phrases = (
        "generated energy", "energy generated", "energy generation",
        "banking", "banking unit", "banked", "banked unit", "banking contribution", "energy banked",
        "procurement price", "last price",
        "generated cost", "generation cost", "cost generated", "cost generation"
    )
    if any(p in norm for p in _proc_phrases):
        if not (date_str and time_obj):
            return err("MISSING_DATE_OR_TIME",
                    "Include BOTH a date (YYYY-MM-DD or '30 September 2027') and time (HH:MM).",
                    intent="procurement")
        return handle_procurement_info(user_input, date_str, time_obj)

    # Fallback
    if not intent:
        return err("UNRECOGNIZED", "Sorry, I couldn't understand your request.", intent=None)
