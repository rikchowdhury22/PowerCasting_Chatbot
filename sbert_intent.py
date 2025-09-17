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
    (os.getenv("SBERT_ENABLED_INTENTS") or "procurement,plant_info,iex,mod,demand,cost per block")
    .replace(" ", "").split(",")
)

# Canonical phrases per intent (seed from your Q&A coverage)
_INTENT_PHRASES = {
    "procurement": [
        "procurement price", "last price", "power purchase cost",
        "generated energy", "energy generated", "energy generation",
        "banking unit", "banked unit", "energy banked", "banking contribution",
        "generated cost", "generation cost", "cost generated", "cost per plant"
    ],
    "plant_info": [
        "plf", "plant load factor", "paf", "plant availability factor",
        "variable cost", "aux consumption", "auxiliary consumption",
        "max power", "min power", "rated capacity", "technical minimum", "plant type"
    ],
    "mod": ["mod price", "moment of dispatch price", "dispatch rate"],
    "iex": ["iex price", "indian energy exchange price", "market clearing price", "exchange rate"],
    "demand": ["demand forecast", "load prediction", "electricity consumption"],
    "cost per block": ["cost per block", "block rate", "rate per block"]
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
    """
    Returns (intent, score) or (None, best_score_below_threshold).
    """
    text_norm = normalize(raw_text)
    v = _embed(text_norm)
    best_intent, best_score = None, -1.0

    for intent, ref_mat in _REF.items():
        # cosine similarity since both are normalized: dot = cosine
        # ref_mat: (K, D), v: (D,)
        sims = ref_mat @ v
        score = float(np.max(sims))
        if score > best_score:
            best_intent, best_score = intent, score

    if best_score >= THRESHOLD:
        return best_intent, best_score
    return None, best_score
