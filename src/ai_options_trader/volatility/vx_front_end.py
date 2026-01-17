from __future__ import annotations

import csv
import ssl
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable


_CBOE_SETTLEMENT_CSV_URL = "https://www.cboe.com/us/futures/market_statistics/settlement/csv/?dt={dt}"


def _parse_ymd(s: str) -> date:
    return datetime.strptime(str(s).strip()[:10], "%Y-%m-%d").date()


def _utc_today() -> date:
    return datetime.now(timezone.utc).date()


def _cache_path_for_dt(dt: date) -> Path:
    p = Path("data/cache/cboe_settlement") / f"settlement_{dt.isoformat()}.csv"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


@dataclass(frozen=True)
class VXFrontEnd:
    dt: date
    m1_symbol: str
    m1_expiration: date
    m1_settle: float
    m2_symbol: str
    m2_expiration: date
    m2_settle: float
    contango_pct: float  # (M2/M1 - 1) * 100; negative => backwardation

    # Optional: spot vs M1 basis (if caller provides spot VIX)
    spot_vix: float | None = None
    spot_minus_m1: float | None = None
    spot_minus_m1_pct: float | None = None

    source: str = "cboe:settlement_csv"


def fetch_cboe_settlement_csv_text(*, dt: date, refresh: bool = False, cache_max_age: timedelta = timedelta(hours=12)) -> str:
    """
    Fetch the Cboe daily settlement CSV for a given date.

    URL pattern observed:
      https://www.cboe.com/us/futures/market_statistics/settlement/csv/?dt=YYYY-MM-DD

    We cache the raw CSV to `data/cache/cboe_settlement/`.
    """
    cache_path = _cache_path_for_dt(dt)
    if cache_path.exists() and not refresh:
        try:
            age = datetime.now(timezone.utc) - datetime.fromtimestamp(cache_path.stat().st_mtime, tz=timezone.utc)
            if age <= cache_max_age:
                return cache_path.read_text(encoding="utf-8")
        except Exception:
            pass

    # stdlib-only fetch (avoid adding dependencies); use a browser-ish UA.
    import urllib.request

    url = _CBOE_SETTLEMENT_CSV_URL.format(dt=dt.isoformat())
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    # Some environments can have certificate chain issues; create a normal default context.
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
        raw = resp.read()
    text = raw.decode("utf-8", errors="replace")
    try:
        cache_path.write_text(text, encoding="utf-8")
    except Exception:
        pass
    return text


def _parse_settlement_rows(csv_text: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    r = csv.DictReader((csv_text or "").splitlines())
    for row in r:
        if not isinstance(row, dict):
            continue
        rows.append({str(k).strip(): str(v).strip() for k, v in row.items() if k is not None})
    return rows


def parse_vx_front_end_from_settlement_csv(
    *,
    dt: date,
    csv_text: str,
    spot_vix: float | None = None,
) -> VXFrontEnd:
    """
    Parse VX front-end term structure from a single daily settlement CSV.

    The CSV currently has columns: Product, Symbol, Expiration Date, Price

    We use the monthly contracts, which appear as symbols like:
      - VX/F6, VX/G6, ...
    and ignore weekly variants like:
      - VX02/F6, VX04/F6, ...
    """
    rows = _parse_settlement_rows(csv_text)
    if not rows:
        raise ValueError("Empty settlement CSV")

    def _get(row: dict[str, str], k: str) -> str:
        return str(row.get(k, "")).strip()

    vx = [r for r in rows if _get(r, "Product").upper() == "VX"]
    if not vx:
        raise ValueError("No VX rows found in settlement CSV")

    # Monthly contracts have symbol form "VX/{code}{digit}" (no weekly number prefix).
    monthlies = [r for r in vx if _get(r, "Symbol").upper().startswith("VX/")]
    use = monthlies or vx  # fallback: if format changes, at least try

    parsed = []
    for r0 in use:
        sym = _get(r0, "Symbol").upper()
        exp_s = _get(r0, "Expiration Date")
        px_s = _get(r0, "Price")
        if not sym or not exp_s or not px_s:
            continue
        try:
            exp = _parse_ymd(exp_s)
            px = float(px_s)
        except Exception:
            continue
        parsed.append((exp, sym, px))

    if len(parsed) < 2:
        raise ValueError("Not enough VX contracts to compute M1/M2")

    parsed.sort(key=lambda x: x[0])
    m1_exp, m1_sym, m1_px = parsed[0]
    m2_exp, m2_sym, m2_px = parsed[1]
    contango = (m2_px / m1_px - 1.0) * 100.0 if m1_px != 0 else 0.0

    spot_minus = None
    spot_minus_pct = None
    if spot_vix is not None and m1_px != 0:
        spot_minus = float(spot_vix) - float(m1_px)
        spot_minus_pct = (float(spot_vix) / float(m1_px) - 1.0) * 100.0

    return VXFrontEnd(
        dt=dt,
        m1_symbol=m1_sym,
        m1_expiration=m1_exp,
        m1_settle=float(m1_px),
        m2_symbol=m2_sym,
        m2_expiration=m2_exp,
        m2_settle=float(m2_px),
        contango_pct=float(contango),
        spot_vix=(float(spot_vix) if spot_vix is not None else None),
        spot_minus_m1=spot_minus,
        spot_minus_m1_pct=spot_minus_pct,
    )


def iter_recent_dates(*, lookback_days: int) -> Iterable[date]:
    """
    Yield calendar dates (UTC) going backwards. Caller can skip failures/non-trading days.
    """
    d0 = _utc_today()
    for k in range(int(max(1, lookback_days))):
        yield d0 - timedelta(days=k)

