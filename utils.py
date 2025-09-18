# utils.py
import os, json, time, requests
from typing import Any, Dict, Optional, Tuple
from difflib import SequenceMatcher
from nlp_setup import normalize

DEFAULT_TIMEOUT = (5, 15)  # (connect, read)
RETRY_BACKOFFS = [0.5, 1.0, 2.0]

class FetchError(Exception):
    def __init__(self, message: str, *, status: Optional[int]=None, payload: Optional[Any]=None):
        super().__init__(message)
        self.status = status
        self.payload = payload

def safe_fetch_json(
    url: str,
    *,
    params: Optional[Dict[str, Any]]=None,
    headers: Optional[Dict[str, str]]=None,
    timeout: Tuple[int,int]=DEFAULT_TIMEOUT
) -> Dict[str, Any]:
    last_err = None
    for i, backoff in enumerate([0] + RETRY_BACKOFFS):
        if backoff:
            time.sleep(backoff)
        try:
            resp = requests.get(url, params=params or {}, headers=headers or {}, timeout=timeout)
            if resp.status_code >= 400:
                raise FetchError(f"HTTP {resp.status_code} from {url}", status=resp.status_code, payload=resp.text)
            try:
                return resp.json()
            except Exception as je:
                raise FetchError("Invalid JSON payload", payload=resp.text) from je
        except Exception as e:
            last_err = e
    if isinstance(last_err, FetchError):
        raise last_err
    raise FetchError(f"Network/unknown error for {url}", payload=str(last_err))

def require_keys(d: Dict[str, Any], keys):
    missing = [k for k in keys if k not in d]
    if missing:
        raise FetchError(f"Response missing keys: {missing}", payload=list(d.keys()))

# --- Existing helpers (kept from old file) ---
def fuzzy_match(a: str, b: str, threshold: float = 0.75) -> bool:
    a1, b1 = normalize(a or ""), normalize(b or "")
    if not a1 or not b1:
        return False
    if a1 == b1 or a1 in b1 or b1 in a1:
        return True
    return SequenceMatcher(None, a1, b1).ratio() >= threshold

def ok(intent: str, data: Dict[str, Any], meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {"ok": True, "intent": intent, "data": data, "meta": meta or {}}

def err(code: str, message: str, *, intent: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None, meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {"ok": False, "intent": intent, "error": {"code": code, "message": message, "details": details or {}}, "meta": meta or {}}
