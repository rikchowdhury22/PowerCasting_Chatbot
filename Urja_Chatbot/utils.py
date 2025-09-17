# utils.py
from nlp_setup import normalize
from difflib import SequenceMatcher
from typing import Any, Dict, Optional

def fuzzy_match(a: str, b: str, threshold: float = 0.75) -> bool:
    a1, b1 = normalize(a or ""), normalize(b or "")
    if not a1 or not b1:
        return False
    if a1 == b1 or a1 in b1 or b1 in a1:
        return True
    return SequenceMatcher(None, a1, b1).ratio() >= threshold

# --- NEW: uniform response helpers ---
def ok(intent: str, data: Dict[str, Any], meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {"ok": True, "intent": intent, "data": data, "meta": meta or {}}

def err(code: str, message: str, *, intent: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None, meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {"ok": False, "intent": intent, "error": {"code": code, "message": message, "details": details or {}}, "meta": meta or {}}
