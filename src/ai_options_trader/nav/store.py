from __future__ import annotations

import csv
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from ai_options_trader.utils.dates import parse_timestamp, utc_now_iso


def _utc_now_iso() -> str:
    return utc_now_iso()


def _parse_ts(s: str) -> datetime:
    return parse_timestamp(s)


def default_nav_sheet_path() -> str:
    # Spreadsheet-friendly CSV of snapshots + returns.
    return os.environ.get("AOT_NAV_SHEET", "data/nav_sheet.csv")


def default_nav_flows_path() -> str:
    # CSV of user contributions/withdrawals (signed amounts).
    return os.environ.get("AOT_NAV_FLOWS", "data/nav_flows.csv")


@dataclass(frozen=True)
class CashFlow:
    ts: str
    amount: float
    note: str


@dataclass(frozen=True)
class NavSnapshot:
    ts: str
    equity: float
    cash: float
    buying_power: float
    positions_count: int
    net_flow_since_prev: float | None
    pnl_since_prev: float | None
    twr_since_prev: float | None
    twr_cum: float
    note: str


_FLOW_FIELDS = ["ts", "amount", "note"]
_NAV_FIELDS = [
    "ts",
    "equity",
    "cash",
    "buying_power",
    "positions_count",
    "net_flow_since_prev",
    "pnl_since_prev",
    "twr_since_prev",
    "twr_cum",
    "note",
]


def append_cashflow(*, ts: str | None = None, amount: float, note: str = "", path: str | None = None) -> str:
    path = path or default_nav_flows_path()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    ts = ts or _utc_now_iso()
    row = {"ts": ts, "amount": f"{float(amount):.6f}", "note": note}
    file_exists = Path(path).exists()
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=_FLOW_FIELDS)
        if not file_exists:
            w.writeheader()
        w.writerow(row)
    return path


def read_cashflows(*, path: str | None = None) -> list[CashFlow]:
    path = path or default_nav_flows_path()
    if not Path(path).exists():
        return []
    with open(path, newline="") as f:
        r = csv.DictReader(f)
        out: list[CashFlow] = []
        for row in r:
            out.append(
                CashFlow(
                    ts=str(row.get("ts") or ""),
                    amount=float(row.get("amount") or 0.0),
                    note=str(row.get("note") or ""),
                )
            )
    out.sort(key=lambda x: _parse_ts(x.ts))
    return out


def read_nav_sheet(*, path: str | None = None) -> list[NavSnapshot]:
    path = path or default_nav_sheet_path()
    if not Path(path).exists():
        return []
    with open(path, newline="") as f:
        r = csv.DictReader(f)
        out: list[NavSnapshot] = []
        for row in r:
            def _f(k: str) -> float:
                return float(row.get(k) or 0.0)

            def _optf(k: str) -> float | None:
                v = row.get(k)
                if v is None or str(v).strip() == "":
                    return None
                return float(v)

            out.append(
                NavSnapshot(
                    ts=str(row.get("ts") or ""),
                    equity=_f("equity"),
                    cash=_f("cash"),
                    buying_power=_f("buying_power"),
                    positions_count=int(float(row.get("positions_count") or 0)),
                    net_flow_since_prev=_optf("net_flow_since_prev"),
                    pnl_since_prev=_optf("pnl_since_prev"),
                    twr_since_prev=_optf("twr_since_prev"),
                    twr_cum=_f("twr_cum"),
                    note=str(row.get("note") or ""),
                )
            )
    out.sort(key=lambda x: _parse_ts(x.ts))
    return out


def _flows_between(*, flows: Iterable[CashFlow], after_ts: str | None, up_to_ts: str) -> list[CashFlow]:
    end = _parse_ts(up_to_ts)
    start = _parse_ts(after_ts) if after_ts else None
    out = []
    for f in flows:
        dt = _parse_ts(f.ts)
        if start is not None and not (dt > start):
            continue
        if dt <= end:
            out.append(f)
    return out


def append_nav_snapshot(
    *,
    ts: str | None = None,
    equity: float,
    cash: float,
    buying_power: float,
    positions_count: int,
    note: str = "",
    sheet_path: str | None = None,
    flows_path: str | None = None,
) -> tuple[str, NavSnapshot]:
    """
    Append a NAV snapshot and compute returns net of user flows.

    Return computation:
    - net_flow_since_prev = sum(flows between prev_snapshot_ts (exclusive) and this ts (inclusive))
    - pnl_since_prev = equity - prev_equity - net_flow_since_prev
    - twr_since_prev = pnl_since_prev / prev_equity   (if prev_equity > 0)
    - twr_cum compounds twr_since_prev over snapshots
    """
    sheet_path = sheet_path or default_nav_sheet_path()
    flows_path = flows_path or default_nav_flows_path()
    Path(sheet_path).parent.mkdir(parents=True, exist_ok=True)
    ts = ts or _utc_now_iso()

    prev_rows = read_nav_sheet(path=sheet_path)
    prev = prev_rows[-1] if prev_rows else None

    flows = read_cashflows(path=flows_path)
    flows_since_prev = _flows_between(flows=flows, after_ts=prev.ts if prev else None, up_to_ts=ts)
    net_flow = sum(f.amount for f in flows_since_prev) if prev else None

    pnl: float | None = None
    twr: float | None = None
    if prev is not None and prev.equity > 0:
        net_flow0 = float(net_flow or 0.0)
        pnl = float(equity) - float(prev.equity) - net_flow0
        twr = pnl / float(prev.equity)
        twr_cum = (1.0 + float(prev.twr_cum)) * (1.0 + float(twr)) - 1.0
    else:
        twr_cum = float(prev.twr_cum) if prev is not None else 0.0

    snap = NavSnapshot(
        ts=ts,
        equity=float(equity),
        cash=float(cash),
        buying_power=float(buying_power),
        positions_count=int(positions_count),
        net_flow_since_prev=(float(net_flow) if net_flow is not None else None),
        pnl_since_prev=pnl,
        twr_since_prev=twr,
        twr_cum=float(twr_cum),
        note=note,
    )

    file_exists = Path(sheet_path).exists()
    with open(sheet_path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=_NAV_FIELDS)
        if not file_exists:
            w.writeheader()
        w.writerow(
            {
                "ts": snap.ts,
                "equity": f"{snap.equity:.6f}",
                "cash": f"{snap.cash:.6f}",
                "buying_power": f"{snap.buying_power:.6f}",
                "positions_count": str(snap.positions_count),
                "net_flow_since_prev": "" if snap.net_flow_since_prev is None else f"{snap.net_flow_since_prev:.6f}",
                "pnl_since_prev": "" if snap.pnl_since_prev is None else f"{snap.pnl_since_prev:.6f}",
                "twr_since_prev": "" if snap.twr_since_prev is None else f"{snap.twr_since_prev:.8f}",
                "twr_cum": f"{snap.twr_cum:.8f}",
                "note": snap.note,
            }
        )

    return sheet_path, snap

