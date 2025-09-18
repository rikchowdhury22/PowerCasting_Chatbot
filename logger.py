# logger.py
import traceback, json
import logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

def get_logger(name="app", level=logging.INFO):
    logger = logging.getLogger(name)
    if not logger.handlers:
        h = logging.StreamHandler()
        fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
        h.setFormatter(fmt)
        logger.addHandler(h)
    logger.setLevel(level)
    return logger

def exc_details(e) -> dict:
    return {
        "type": type(e).__name__,
        "msg": str(e),
        "trace": traceback.format_exc(limit=5)
    }
