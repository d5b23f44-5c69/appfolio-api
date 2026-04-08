"""Configuration loader for the AppFolio API server."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("APPFOLIO_DATA_DIR", REPO_ROOT / "data"))
IMAGES_DIR = DATA_DIR / "images"
DB_PATH = DATA_DIR / "cache.db"
_SITES_DEFAULT = Path(__file__).parent / "sites.yaml"
_SITES_EXAMPLE = Path(__file__).parent / "sites.yaml.example"
# Prefer the real sites.yaml if it exists; otherwise fall back to the
# checked-in example so a fresh clone / image build still boots.
SITES_FILE = Path(
    os.environ.get(
        "APPFOLIO_SITES_FILE",
        _SITES_DEFAULT if _SITES_DEFAULT.exists() else _SITES_EXAMPLE,
    )
)

API_KEY = os.environ.get("APPFOLIO_API_KEY", "")


@dataclass
class SiteConfig:
    key: str
    subdomain: str
    property_list: str | None = None
    refresh_minutes: int = 15


def load_sites() -> dict[str, SiteConfig]:
    raw = yaml.safe_load(SITES_FILE.read_text()) or {}
    defaults = raw.get("defaults") or {}
    default_refresh = int(defaults.get("refresh_minutes", 15))
    out: dict[str, SiteConfig] = {}
    for key, cfg in (raw.get("sites") or {}).items():
        out[key] = SiteConfig(
            key=key,
            subdomain=cfg["subdomain"],
            property_list=cfg.get("property_list"),
            refresh_minutes=int(cfg.get("refresh_minutes", default_refresh)),
        )
    return out


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
