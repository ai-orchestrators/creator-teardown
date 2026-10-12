"""Shared paths, config and helpers for the creator-teardown scripts.

Every path resolves from this file, so the skill runs wherever it is installed.
Your settings live in config/ beside this skill (gitignored). Set the
CREATOR_TEARDOWN_CONFIG environment variable to keep them somewhere else.

config/ holds:
    settings.json   platforms, transcriber, currency, run folder, cost caps
    brand.json      who prepared the report (name, url, logo), all optional
    profile.md      your default brand: who the rebuilds are written for
    profiles/       one <slug>.md per extra brand of yours (optional)
    .env            API keys, written by you, never by the skill
"""
from __future__ import annotations

import base64
import copy
import json
import os
import re
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
DECISIONS_DIR = SKILL_DIR / "decisions"
VIDEO_FORMATS = {"video", "reel", "short"}
PLATFORMS = ("instagram", "tiktok", "youtube", "linkedin")
SPELLINGS = ("as-is", "au", "uk")
KEY_NAMES = ("APIFY_TOKEN", "TYPESAFE_API_KEY", "OPENROUTER_API_KEY", "YOUTUBE_API_KEY")

DEFAULT_SETTINGS = {
    "platforms": list(PLATFORMS),
    "runs_dir": "teardowns",
    "apify_max_cost_usd": 5.0,
    "jev_max_usd": 1.0,
    "transcriber": {"binary": "whisper-cli", "model": None, "language": "en", "extra_args": [], "command": None},
    "currency": {"code": "USD", "symbol": "US$", "usd_rate": 1.0},
    "timezone": None,
    "spelling": "as-is",
    "client_files_dir": None,
}

CURRENCY_SYMBOLS = {"USD": "US$", "AUD": "A$", "NZD": "NZ$", "CAD": "C$", "GBP": "£", "EUR": "€",
                    "SGD": "S$", "INR": "₹", "JPY": "¥"}


class ConfigError(Exception):
    """config/ holds something the scripts cannot use. The message names the file and the fix."""


def config_dir() -> Path:
    override = os.environ.get("CREATOR_TEARDOWN_CONFIG")
    return Path(override).expanduser() if override else SKILL_DIR / "config"


def load_env(path: Path | None = None) -> list[str]:
    """Fill os.environ from config/.env without overriding anything already set.

    Returns the NAMES it loaded, never the values. Keys are never printed or written anywhere.
    """
    env_file = Path(path) if path else config_dir() / ".env"
    if not env_file.is_file():
        return []
    loaded = []
    for line in env_file.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key.startswith("export "):
            key = key[len("export "):].strip()
        value = value.strip().strip("'\"")
        if key and value and not os.environ.get(key):
            os.environ[key] = value
            loaded.append(key)
    return loaded


def key_present(name: str) -> bool:
    load_env()
    return bool(os.environ.get(name))


def read_json(path: Path | str):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: Path | str, payload) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _read_config_json(name: str) -> dict:
    path = config_dir() / name
    if not path.exists():
        return {}
    try:
        data = read_json(path)
    except ValueError as exc:
        raise ConfigError(f"{path} is not valid JSON ({exc}). Fix it or re-run SETUP.md.") from None
    if not isinstance(data, dict):
        raise ConfigError(f"{path} must hold a JSON object. Fix it or re-run SETUP.md.")
    return data


def load_settings() -> dict:
    """config/settings.json over the defaults. Nested objects merge one level deep."""
    settings = copy.deepcopy(DEFAULT_SETTINGS)
    for key, value in _read_config_json("settings.json").items():
        if isinstance(value, dict) and isinstance(settings.get(key), dict):
            settings[key] = {**settings[key], **value}
        else:
            settings[key] = value
    unknown = [p for p in settings.get("platforms") or [] if p not in PLATFORMS]
    if unknown:
        raise ConfigError(f"settings.json platforms has {unknown}; use any of {list(PLATFORMS)}.")
    if settings.get("spelling") not in SPELLINGS:
        raise ConfigError(f"settings.json spelling must be one of {list(SPELLINGS)}.")
    rate = settings["currency"].get("usd_rate")
    if not isinstance(rate, (int, float)) or isinstance(rate, bool) or rate <= 0:
        raise ConfigError("settings.json currency.usd_rate must be a number above 0 (1 US dollar in your currency).")
    if settings.get("client_files_dir") is not None and not isinstance(settings["client_files_dir"], str):
        raise ConfigError("settings.json client_files_dir must be a folder path, or null.")
    for key in ("apify_max_cost_usd", "jev_max_usd"):
        if not isinstance(settings.get(key), (int, float)) or settings[key] <= 0:
            raise ConfigError(f"settings.json {key} must be a number above 0.")
    return settings


def brand_profiles() -> dict[str, Path]:
    """Your brands: config/profile.md as "default", plus config/profiles/<slug>.md for any others."""
    found = {}
    if (config_dir() / "profile.md").is_file():
        found["default"] = config_dir() / "profile.md"
    for path in sorted((config_dir() / "profiles").glob("*.md")):
        found[path.stem] = path
    return found


def resolve_config_path(value) -> Path | None:
    """A path from config: absolute, ~, or relative to the config folder."""
    if not value:
        return None
    path = Path(str(value)).expanduser()
    return path if path.is_absolute() else config_dir() / path


def image_data_uri(value) -> str:
    """A small local image as a data URI, so the report stays one self-contained file."""
    path = resolve_config_path(value)
    if not path or not path.is_file():
        return ""
    suffix = path.suffix.lower().lstrip(".")
    kind = {"svg": "svg+xml", "jpg": "jpeg"}.get(suffix, suffix)
    if kind not in ("png", "jpeg", "gif", "webp", "svg+xml"):
        return ""
    return f"data:image/{kind};base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def load_brand() -> dict:
    """Who prepared the report: config/brand.json {name, url, logo, jev_mark}. Missing = nothing shown."""
    brand = _read_config_json("brand.json")
    return {"name": str(brand.get("name") or ""), "url": str(brand.get("url") or ""),
            "logo": image_data_uri(brand.get("logo")), "jev_mark": image_data_uri(brand.get("jev_mark"))}


def currency_symbol_rate(currency: dict | None = None) -> tuple[str, float, bool]:
    """(symbol, how many units of it one US dollar buys, is it US$)."""
    cur = {**DEFAULT_SETTINGS["currency"], **(currency or {})}
    code = str(cur.get("code") or "USD").upper()
    if code == "USD":
        return "US$", 1.0, True
    symbol = cur.get("symbol")
    if not symbol or symbol == "US$":
        symbol = CURRENCY_SYMBOLS.get(code, code + " ")
    return str(symbol), float(cur.get("usd_rate") or 1), False


def format_money(usd, currency: dict | None = None) -> str:
    """US$ only by default. Any other currency shows first, with US$ beside it."""
    usd = float(usd or 0)
    symbol, rate, is_usd = currency_symbol_rate(currency)
    return f"US${usd:.2f}" if is_usd else f"{symbol}{usd * rate:.2f} (US${usd:.2f})"


def safe_id(raw: str) -> str:
    """Post ids become folder names, so strip anything that could escape the work dir."""
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(raw)).strip(".-")
    return cleaned or "post"


def die(message: str, code: int = 1) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    sys.exit(code)
