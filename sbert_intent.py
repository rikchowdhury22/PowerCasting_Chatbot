# sbert_intent.py
import os
import numpy as np
from functools import lru_cache
from sentence_transformers import SentenceTransformer
from nlp_setup import normalize
from logger import logger

# Model & threshold configurable via env
MODEL_NAME = os.getenv("SBERT_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
THRESHOLD  = float(os.getenv("SBERT_INTENT_THRESHOLD", "0.65"))

# Keep SBERT focused where we need help most
ENABLED_INTENTS = set(
    s.strip() for s in (os.getenv("SBERT_ENABLED_INTENTS") or
                        "procurement,plant_info,iex,mod,demand,cost per block"
    ).split(",") if s.strip()
)

# sbert_intent.py (add/replace these parts)

_INTENT_PHRASES = {
    "procurement": [
        "procurement price","last price","power purchase cost","ppc","purchase cost",
        "generated energy","energy generation","energy generated",
        "generated cost","generation cost","cost generated","cost generation"
    ],
    "banking": [  # <-- NEW
        "banking","banked units","banking units","banking unit","banked unit",
        "energy banked","banking cost","adjusted units","adjustment charges"
    ],
    "plant_info": [
        "plf","plant load factor","paf","plant availability factor","availability factor",
        "variable cost","aux consumption","auxiliary consumption",
        "max power","min power","rated capacity","technical minimum","plant type"
    ],
    "mod": ["mod price","moment of dispatch price","dispatch price","dispatch rate","dispatch value","despatch price"],
    "iex": ["iex price","indian energy exchange price","market clearing price","clearing price","exchange rate","mcp"],
    "demand": ["demand forecast","load prediction","electricity consumption","expected demand","predicted load"],
    "cost per block": ["cost per block","block price","block rate","rate per block","block cost"]
}

# Load model once
logger.info(f"SBERT: loading model '{MODEL_NAME}' ...")
_MODEL = SentenceTransformer(MODEL_NAME)
logger.info("SBERT: model ready")

# Precompute reference embeddings (L2-normalized) for fast cosine
def _norm_enc(sentences: list[str]) -> np.ndarray:
    embs = _MODEL.encode(sentences, normalize_embeddings=True)
    return np.asarray(embs, dtype=np.float32)

_REF = {intent: _norm_enc(phrs) for intent, phrs in _INTENT_PHRASES.items() if intent in ENABLED_INTENTS}

@lru_cache(maxsize=2048)
def _embed(text_norm: str) -> np.ndarray:
    vec = _MODEL.encode([text_norm], normalize_embeddings=True)[0]
    return np.asarray(vec, dtype=np.float32)

def predict_intent_sbert(raw_text: str) -> tuple[str | None, float]:
    text_norm = normalize(raw_text)
    v = _embed(text_norm)

    # context-aware threshold
    base = THRESHOLD
    # date/time or price-y tokens => a tad easier
    if any(t in text_norm for t in (" at ", ":")) and any(w in text_norm for w in (
        "price","rate","value","cost","ppc","mcp","dispatch","despatch","exchange","clearing"
    )):
        base = max(0.55, base - 0.05)
    # plant-like tokens => a tad easier for plant_info
    plant_cues = ("ntpc","gsecl","npci","npcil","hydro","wind","bagasse","solar","plant","vindhyachal","ukai","kadana")
    if any(p in text_norm for p in plant_cues):
        base = max(0.55, base - 0.03)

    best_intent, best_score = None, -1.0
    for intent, ref_mat in _REF.items():
        score = float(np.max(ref_mat @ v))
        if score > best_score:
            best_intent, best_score = intent, score

    if best_score >= base:
        return best_intent, best_score
    return None, best_score
