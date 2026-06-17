import json
import os
from typing import Any, Dict, List, Optional, Tuple

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


def load_mingdi_profiles() -> dict:
    return _load(os.path.join(_CONFIG_DIR, "mingdi_profiles.json"))


def load_modern_whistles() -> dict:
    return _load(os.path.join(_CONFIG_DIR, "modern_whistles.json"))


def load_arrow_profiles() -> dict:
    return _load(os.path.join(_CONFIG_DIR, "arrow_profiles.json"))


def extract_mingdi_shape_profile(shape_name: str) -> Tuple[Dict[str, float], Dict[str, Dict], List[str]]:
    profiles = load_mingdi_profiles()
    shape = profiles.get(shape_name, profiles.get("conical", {}))
    warnings = shape.get("_warnings", [])
    numeric_params: Dict[str, float] = {}
    provenance_info: Dict[str, Dict] = {}
    for key, entry in shape.items():
        if key.startswith("_") or not isinstance(entry, dict) or "value" not in entry:
            continue
        numeric_params[key] = entry["value"]
        provenance_info[key] = {
            "uncertainty": entry.get("uncertainty"),
            "provenance": entry.get("provenance", "unknown"),
        }
    return numeric_params, provenance_info, warnings


def get_modern_whistle_defaults(model_name: Optional[str] = None) -> Dict[str, Any]:
    whistle_data = load_modern_whistles()
    default_name = whistle_data.get("default_model", "fox40_classic")
    resolved_name = model_name if (model_name and model_name in whistle_data.get("models", {})) else default_name
    model = whistle_data["models"].get(resolved_name, whistle_data["models"][default_name])
    spec = model.get("measured_specs", {})
    dims = model.get("dimensions", {})
    sim = model.get("defaults_for_simulation", {})
    return {
        "model_name": resolved_name,
        "display_name": model.get("name", resolved_name),
        "certifications": model.get("certifications", []),
        "mouthpiece_type": model.get("mouthpiece_type", "unknown"),
        "chamber_count": model.get("chamber_count", 1),
        "dimensions": dims,
        "measured_specs": spec,
        "simulation_defaults": sim,
        "whistle_length": sim.get("whistle_length", dims.get("whistle_length_m", 0.052)),
        "whistle_diameter": sim.get("whistle_diameter", dims.get("whistle_diameter_m", 0.022)),
        "mouth_width": sim.get("mouth_width", dims.get("mouth_width_m", 0.0040)),
        "strouhal_jet": sim.get("strouhal_jet", 0.50),
        "dominant_frequency_multiplier": sim.get("dominant_frequency_multiplier", 0.75),
        "harmonic_multipliers": sim.get("harmonic_multipliers", [1.0, 2.0, 3.0, 4.0]),
        "measured_dominant_frequency_hz": spec.get("dominant_frequency_hz"),
        "measured_spl_1m_db": spec.get("spl_1m_db_continuous"),
    }


def list_modern_whistle_models() -> List[Dict[str, str]]:
    data = load_modern_whistles()
    return [
        {
            "id": key,
            "name": entry.get("name", key),
            "frequency_hz": entry.get("measured_specs", {}).get("dominant_frequency_hz"),
            "spl_db": entry.get("measured_specs", {}).get("spl_1m_db_continuous"),
        }
        for key, entry in data.get("models", {}).items()
    ]


def get(path: str, default: Any = None) -> Any:
    parts = path.split(".")
    first = parts[0]
    if first == "aerodynamics":
        root = load_aerodynamics_config()
    elif first == "acoustics":
        root = load_acoustics_config()
    elif first == "mingdi_profiles":
        root = load_mingdi_profiles()
    elif first == "modern_whistles":
        root = load_modern_whistles()
    elif first == "arrow_profiles":
        root = load_arrow_profiles()
    else:
        return default
    cur = root
    for p in parts[1:]:
        if isinstance(cur, dict) and p in cur:
            cur = cur[p]
        else:
            return default
    return cur
