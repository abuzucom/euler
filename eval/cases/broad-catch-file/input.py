import json
import logging

logger = logging.getLogger(__name__)


def load_config(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        logger.warning("config problem")
        return {}
