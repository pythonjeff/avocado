"""
Quiver dataset loader.

v0 is offline: it expects CSV exports from quiverquant.com to land in
data/cache/quiver/. Each dataset has a canonical filename and a Quiver URL
where the CSV can be downloaded. The loader is forgiving about column names
because Quiver's exports have changed shape over the years and we want the
readers above to keep working when columns drift.

When a Quiver API key is configured (QUIVER_API_KEY env var), fetch_*_live()
functions hit the live API and return DataFrames in the same shape so the
reader modules keep working unchanged.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pandas as pd

QUIVER_API_BASE = "https://api.quiverquant.com/beta"


def get_api_key() -> Optional[str]:
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    return os.environ.get("QUIVER_API_KEY") or None


def fetch_trump_live(api_key: str) -> Optional[pd.DataFrame]:
    """Fetch Trump stock trades from the Quiver bulk endpoint."""
    import requests

    url = f"{QUIVER_API_BASE}/bulk/trumpstocktrades"
    try:
        resp = requests.get(
            url,
            headers={"accept": "application/json", "Authorization": f"Token {api_key}"},
            timeout=15,
        )
        resp.raise_for_status()
    except Exception as exc:
        raise RuntimeError(f"Quiver API error: {exc}") from exc

    data = resp.json()
    if not data:
        return None
    return pd.DataFrame(data)


def fetch_congress_live(api_key: str) -> Optional[pd.DataFrame]:
    """Fetch recent congressional trades from the Quiver live API."""
    import requests

    url = f"{QUIVER_API_BASE}/live/congresstrading"
    try:
        resp = requests.get(
            url,
            headers={"accept": "application/json", "Authorization": f"Token {api_key}"},
            timeout=15,
        )
        resp.raise_for_status()
    except Exception as exc:
        raise RuntimeError(f"Quiver API error: {exc}") from exc

    data = resp.json()
    if not data:
        return None
    df = pd.DataFrame(data)
    return _normalize_columns(df)


# ─────────────────────────────────────────────────────────────────────────────
# Dataset catalog — what v0 reads, where to get it, what it powers
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class QuiverDataset:
    key: str                # internal id used by the readers
    filename: str           # expected CSV filename under data/cache/quiver/
    label: str              # human-readable name
    url: str                # quiverquant.com page where the CSV is downloaded
    insight: str            # one-line why-we-pull-this for the catalog panel


CATALOG: list[QuiverDataset] = [
    QuiverDataset(
        key="congress",
        filename="congress_trading.csv",
        label="Congressional Trading",
        url="https://www.quiverquant.com/congresstrading/",
        insight="Lawmakers' periodic transaction reports — cluster-buys and committee overlap with sector.",
    ),
    QuiverDataset(
        key="contracts",
        filename="gov_contracts.csv",
        label="Government Contracts",
        url="https://www.quiverquant.com/sources/govcontracts",
        insight="Federal contract awards by ticker — flags revenue surprises before they hit the tape.",
    ),
    QuiverDataset(
        key="insider",
        filename="insider_trading.csv",
        label="Insider Trading (Form 4)",
        url="https://www.quiverquant.com/insiders/",
        insight="Open-market insider buys; cluster buys across officers are the high-signal subset.",
    ),
    QuiverDataset(
        key="wsb",
        filename="wsb_mentions.csv",
        label="r/WallStreetBets Mentions",
        url="https://www.quiverquant.com/sources/wallstreetbets",
        insight="Retail crowd attention — mention deltas catch building short-squeeze setups.",
    ),
    QuiverDataset(
        key="otc_short",
        filename="otc_short_volume.csv",
        label="Off-Exchange Short Volume",
        url="https://www.quiverquant.com/shortdata/",
        insight="OTC short-volume share — spikes flag dark-pool positioning ahead of price moves.",
    ),
]


def catalog_by_key(key: str) -> Optional[QuiverDataset]:
    for d in CATALOG:
        if d.key == key:
            return d
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Filesystem layout
# ─────────────────────────────────────────────────────────────────────────────

def quiver_dir() -> Path:
    """Where Quiver CSV exports live. Created on demand."""
    root = Path(os.environ.get("LOX_QUIVER_DIR", "data/cache/quiver"))
    root.mkdir(parents=True, exist_ok=True)
    return root


def dataset_path(key: str) -> Optional[Path]:
    ds = catalog_by_key(key)
    if ds is None:
        return None
    return quiver_dir() / ds.filename


# ─────────────────────────────────────────────────────────────────────────────
# Read
# ─────────────────────────────────────────────────────────────────────────────

def load(key: str) -> Optional[pd.DataFrame]:
    """Load a dataset by key. Returns None if the CSV isn't present yet."""
    p = dataset_path(key)
    if p is None or not p.exists():
        return None
    try:
        df = pd.read_csv(p)
    except Exception:
        return None
    if df.empty:
        return None
    return _normalize_columns(df)


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Lowercase + underscore column names so readers don't have to guess case."""
    df = df.copy()
    df.columns = [str(c).strip().lower().replace(" ", "_").replace("-", "_") for c in df.columns]
    return df


def available_keys() -> list[str]:
    """Keys whose CSVs are present on disk right now."""
    return [d.key for d in CATALOG if (quiver_dir() / d.filename).exists()]


def missing_keys() -> list[str]:
    return [d.key for d in CATALOG if not (quiver_dir() / d.filename).exists()]
