import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict

DEFAULT_CONFIG: Dict[str, Any] = {
    "external_dependencies": {
        "llm_api": {
            "base_url": "https://api.openai.com/v1",
            "api_key": "",
            "models": {"small": "gpt-4o-mini", "medium": "gpt-4o", "large": "gpt-4o"},
            "timeout": 120.0,
        },
        # Path to draw.io / diagrams.net desktop executable used for exports.
        "drawioExe": r"C:\\Program Files\\draw.io\\draw.io.exe",
    },
    "ui": {
        "fontFamily": "Cascadia Code, 思源等宽",
        "window": {
            "width": 620,
            "height": 860,
        },
        "palette": {
            "grays": [
                "#212529",
                "#343a40",
                "#495057",
                "#6c757d",
                "#adb5bd",
                "#ced4da",
                "#dee2e6",
                "#e9ecef",
                "#f8f9fa",
            ],
            "lightColors": [
                "#F94144",
                "#F9C74F",
                "#90BE6D",
                "#54a4ea",
                "#D1A2E6",
                "#F3722C",
                "#43AA8B",
                "#277DA1",
                "#F8961E",
                "#F9844A",
                "#4D908E",
            ],
            "darkColors": [
                "#C73335",
                "#C9A23F",
                "#739957",
                "#427eaf",
                "#9a78a9",
                "#C15A22",
                "#35876F",
                "#1F6481",
                "#C77618",
                "#C66A3C",
                "#3D7371",
            ],
            "highlightColors": ["#ff6565", "#ededed", "#68a8fc"],
        },
    },
    "storage": {
        "maxItemsPerGroup": 300,
    },
    "plugins": {
        "dictionary": {
            # Path to the primary .mdx file. Override in config.yaml to your install.
            "mdxPath": r"D:\\Dictionaries\\OALD9\\oald9.mdx",
            # Optional: custom stylesheet used to render dictionary HTML.
            "cssPath": r"D:\\Dictionaries\\OALD9\\oald9.css",
        },
    },
}


def _merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    result = deepcopy(base)
    for key, val in (override or {}).items():
        if isinstance(val, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], val)
        else:
            result[key] = val
    return result


def _load_from_file(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    # Try PyYAML if available; fall back to JSON (valid YAML subset).
    try:
        import yaml  # type: ignore

        return yaml.safe_load(text) or {}
    except Exception:
        try:
            return json.loads(text)
        except Exception:
            return {}


def load_config(path: Path | None = None) -> Dict[str, Any]:
    cfg_path = path or Path(__file__).resolve().parent / "config.yaml"
    file_cfg = _load_from_file(cfg_path)
    return _merge(DEFAULT_CONFIG, file_cfg)


def get_palette_config(path: Path | None = None) -> Dict[str, Any]:
    cfg = load_config(path)
    ui_cfg = cfg.get("ui", {})
    default_ui = DEFAULT_CONFIG.get("ui", {})
    return ui_cfg.get("palette", default_ui.get("palette", {}))


def get_llm_settings(path: Path | None = None) -> Dict[str, Any]:
    cfg = load_config(path)
    ext = cfg.get("external_dependencies", {})
    default_ext = DEFAULT_CONFIG.get("external_dependencies", {})
    return ext.get("llm_api", default_ext.get("llm_api", {}))


def get_openai_settings(path: Path | None = None) -> Dict[str, Any]:
    """Backward-compatible alias for llm_api settings."""
    return get_llm_settings(path)


def get_dictionary_settings(path: Path | None = None) -> Dict[str, Any]:
    cfg = load_config(path)
    plugins_cfg = cfg.get("plugins", {})
    default_plugins = DEFAULT_CONFIG.get("plugins", {})
    return plugins_cfg.get("dictionary", default_plugins.get("dictionary", {}))


def get_tools_settings(path: Path | None = None) -> Dict[str, Any]:
    cfg = load_config(path)
    ext = cfg.get("external_dependencies", {})
    default_ext = DEFAULT_CONFIG.get("external_dependencies", {})
    return {"drawioExe": ext.get("drawioExe", default_ext.get("drawioExe"))}


def get_storage_settings(path: Path | None = None) -> Dict[str, Any]:
    cfg = load_config(path)
    return cfg.get("storage", DEFAULT_CONFIG.get("storage", {}))
