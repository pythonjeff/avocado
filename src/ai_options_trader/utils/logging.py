from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from typing import Any
from rich.console import Console

console = Console()

def _to_jsonable(x: Any) -> Any:
    if is_dataclass(x):
        return asdict(x)
    if hasattr(x, "model_dump"):
        return x.model_dump()
    if isinstance(x, (datetime, date)):
        return x.isoformat()
    return x

def log_event(event: str, payload: dict[str, Any]) -> None:
    console.print(f"[bold]{event}[/bold]")
    console.print_json(json.dumps({k: _to_jsonable(v) for k, v in payload.items()}, default=str))
