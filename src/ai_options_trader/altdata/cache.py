from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def cache_root() -> Path:
    root = Path(os.environ.get("AOT_CACHE_DIR", "data/cache"))
    root.mkdir(parents=True, exist_ok=True)
    return root / "altdata"


def cache_path(key: str) -> Path:
    p = cache_root() / f"{key}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def read_cache(path: Path, *, max_age: timedelta) -> Any | None:
    try:
        if not path.exists():
            return None
        age = _utc_now() - datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        if age > max_age:
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def write_cache(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")

