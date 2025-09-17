import nltk, os, contextlib
from nltk.corpus import stopwords
import string, re, requests, logging
from logger import logger
from nltk.tokenize import word_tokenize
from nltk.stem import WordNetLemmatizer

# ---------------------------
# NLTK setup
# ---------------------------
import nltk, os, contextlib, glob, zipfile, tarfile
from logger import logger
from nltk.corpus import stopwords
from nltk.stem import WordNetLemmatizer

NLTK_LOCAL = os.path.abspath(os.path.join(os.path.dirname(__file__), "nltk_data"))
os.makedirs(NLTK_LOCAL, exist_ok=True)
nltk.data.path.append(NLTK_LOCAL)

REQUIRED = {
    "punkt":     ("tokenizers/punkt",  "tokenizers"),
    "stopwords": ("corpora/stopwords", "corpora"),
    "wordnet":   ("corpora/wordnet",   "corpora"),
}

def _exists(resource_path: str) -> bool:
    try:
        nltk.data.find(resource_path)
        return True
    except LookupError:
        return False

def _download(pkg: str):
    logger.info(f"NLTK: ensuring '{pkg}'...")
    ok = nltk.download(pkg, download_dir=NLTK_LOCAL, quiet=False)
    if not ok:
        logger.warning(f"NLTK: download reported failure for '{pkg}'")

def _extract_archives(pkg: str, base_dir: str):
    """Auto-extract leftover archives for a package (zip/tar.gz) into base_dir."""
    base = os.path.join(NLTK_LOCAL, base_dir)
    os.makedirs(base, exist_ok=True)

    # zip files
    for z in glob.glob(os.path.join(NLTK_LOCAL, "**", f"*{pkg}*.zip"), recursive=True):
        try:
            with zipfile.ZipFile(z, "r") as zf:
                zf.extractall(base)
            logger.info(f"NLTK: extracted '{pkg}' from {os.path.relpath(z, NLTK_LOCAL)}")
        except Exception as e:
            logger.error(f"NLTK: zip extract failed for {z}: {e}")

    # tar.gz files (rare for NLTK, but supported)
    for t in glob.glob(os.path.join(NLTK_LOCAL, "**", f"*{pkg}*.tar.gz"), recursive=True):
        try:
            with tarfile.open(t, "r:gz") as tf:
                tf.extractall(base)
            logger.info(f"NLTK: extracted '{pkg}' from {os.path.relpath(t, NLTK_LOCAL)}")
        except Exception as e:
            logger.error(f"NLTK: tar.gz extract failed for {t}: {e}")

def _cleanup_archives(pkg: str):
    removed = 0
    for pat in (f"*{pkg}*.zip", f"*{pkg}*.tar.gz"):
        for a in glob.glob(os.path.join(NLTK_LOCAL, "**", pat), recursive=True):
            with contextlib.suppress(Exception):
                os.remove(a)
                removed += 1
    if removed:
        logger.debug(f"NLTK cleanup: removed {removed} archive(s) for {pkg}")

def ensure_nltk_packages():
    for pkg, (resource_path, base_dir) in REQUIRED.items():
        # 1) already there?
        if not _exists(resource_path):
            # 2) try official downloader
            _download(pkg)

        # 3) if still missing, try auto-extract from any leftover archives
        if not _exists(resource_path):
            _extract_archives(pkg, base_dir)

        # 4) final verify + clean archives ONLY if resource exists now
        if _exists(resource_path):
            logger.info(f"NLTK: '{pkg}' ready")
            _cleanup_archives(pkg)
        else:
            logger.warning(f"NLTK: '{pkg}' NOT available after attempts")

# ✅ run automatically on import
ensure_nltk_packages()

# (now safe to create lemmatizer / stopwords)
lemmatizer = WordNetLemmatizer()
stop_words = set(stopwords.words("english"))

# ---------------------------
# Normalization
# ---------------------------
def normalize(text):
    text = text.lower()
    text = re.sub(r'\b(\d+)\s*&\s*(\d+)\b', r'\1 and \2', text)

    text = text.replace('&', 'and')
    text = text.replace('&amp', 'and')
    text = text.replace('/', ' ')
    text = text.replace('\n', ' ')
    text = text.replace('-', ' ')

    # Replace known phrases with their normalized forms
    replacements = {
    "plant load factor": "plf",
    "plant availability factor": "paf",
    "auxiliary consumption": "aux consumption",
    "maximum power": "max power",
    "minimum power": "min power",
    "iex price": "iex price",
    "iex cost": "iex price",
    "iex rate": "iex price",
    "banked unit": "banking unit",
    "gen energy": "generated energy",
    # do NOT rewrite "procurement price" to "last_price"
    "energy generated": "generated energy",
    "energy generation": "generated energy",
    "cost generated": "generated cost",
    }
    
    for k, v in sorted(replacements.items(), key=lambda x: -len(x[0])):  # longest first
        text = text.replace(k, v)

    text = re.sub(r'\s+', ' ', text).strip()
    text = re.sub(r'[^\w\s]', '', text)
    text = text.strip(string.punctuation)
    return text

# ---------------------------
# NLP Helpers
# ---------------------------
def preprocess(text):
    try:
        # Clean and normalize the text
        text = normalize(text)
        print("DEBUG cleaned text:", text)

        # Tokenize
        tokens = word_tokenize(text)
        print("DEBUG: Tokens =", tokens)

        # Filtered and lemmatized tokens
        processed_tokens = [
            lemmatizer.lemmatize(tok)
            for tok in tokens
            if tok not in stop_words and len(tok) > 1 and not tok.isnumeric()
        ]

        # Plant-related keywords
        plant_keywords = [
            "plf", "paf", "variable cost", "aux consumption", "max power", "min power",
            "rated capacity", "type", "plant", "plant details", "auxiliary consumption",
            "technical minimum", "maximum power", "minimum power", "plant load factor",
            "plant availability factor", "aux usage", "auxiliary usage", "var cost"
        ]

        # Procurement-related keywords
        procurement_keywords = [
            "banking unit", "banking contribution", "banking", "banked unit",
            "generated energy", "procurement price", "generation energy", "energy generated",
            "energy generation", "demand banked", "energy", "produce", "banked",
            "energy banked", "generated cost", "generation cost", "cost generated",
            "cost generation", "last_price"
        ]

        # Combine all
        all_keywords = plant_keywords + procurement_keywords

        matched_keywords = set()
        for keyword in all_keywords:
            if re.search(rf"\b{re.escape(keyword)}\b", text):
                matched_keywords.add(keyword)

        return processed_tokens, matched_keywords

    except Exception as e:
        logger.error(f"Preprocessing error: {e}")
        return [], set()

__all__ = ['normalize', 'preprocess']
