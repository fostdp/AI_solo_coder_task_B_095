import json
import os
from typing import Any, Dict

_BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_CONFIG_DIR = os.path.join(_BASE_DIR, "config")

_cache: Dict[str, dict] = {}


def _load(path: str) -> dict:
    if path in _cache:
        return _cache[path]
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    _cache[path] = data
    return data


def load_aerodynamics_config() -> dict:
    return _load(os.path.join(_CONFIG_DIR, "aerodynamics.json"))


def load_acoustics_config() -> dict:
    return _load(os.path.join(_CONFIG_DIR, "acoustics.json"))


def get(path: str, default: Any = None) -> Any:
    parts = path.split(".")
    first = parts[0]
    if first == "aerodynamics":
        root = load_aerodynamics_config()
    elif first == "acoustics":
        root = load_acoustics_config()
    else:
        return default
    cur = root
    for p in parts[1:]:
        if isinstance(cur, dict) and p in cur:
            cur = cur[p]
        else:
            return default
    return cur
