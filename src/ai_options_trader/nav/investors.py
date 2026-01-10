from __future__ import annotations

import csv
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

from ai_options_trader.nav.store import _parse_ts, read_nav_sheet


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_investor_flows_path() -> str:
    # Internal "fund ledger" of investor contributions/withdrawals.
    return os.environ.get("AOT_NAV_INVESTOR_FLOWS", "data/nav_investor_flows.csv")


@dataclass(frozen=True)
class InvestorFlow:
    ts: str
    code: str
    amount: float
    note: str


_FIELDS = ["ts", "code", "amount", "note"]


def append_investor_flow(
    *,
    code: str,
    amount: float,
    note: str = "",
    ts: str | None = None,
    path: str | None = None,
) -> str:
    path = path or default_investor_flows_path()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    ts = ts or _utc_now_iso()
    row = {"ts": ts, "code": str(code).strip().upper(), "amount": f"{float(amount):.6f}", "note": note}
    file_exists = Path(path).exists()
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=_FIELDS)
        if not file_exists:
            w.writeheader()
        w.writerow(row)
    return path


def read_investor_flows(*, path: str | None = None) -> list[InvestorFlow]:
    path = path or default_investor_flows_path()
    if not Path(path).exists():
        return []
    with open(path, newline="") as f:
        r = csv.DictReader(f)
        out: list[InvestorFlow] = []
        for row in r:
            out.append(
                InvestorFlow(
                    ts=str(row.get("ts") or ""),
                    code=str(row.get("code") or "").strip().upper(),
                    amount=float(row.get("amount") or 0.0),
                    note=str(row.get("note") or ""),
                )
            )
    out.sort(key=lambda x: _parse_ts(x.ts))
    return out


def _parse_money(x: object) -> float:
    s = str(x if x is not None else "").strip()
    if not s:
        raise ValueError("empty amount")
    s = s.replace("$", "").replace(",", "").strip()
    return float(s)


def _excel_serial_to_iso(x: float) -> str:
    """
    Excel serial date conversion (1900 date system).
    Convention: day 0 is 1899-12-30 in many conversions (accounts for Excel's 1900-leap-year bug).
    """
    base = datetime(1899, 12, 30, tzinfo=timezone.utc)
    dt = base + timedelta(days=float(x))
    return dt.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()


def _normalize_ts(x: object) -> str:
    """
    Accept:
    - ISO timestamps: 2026-01-01T00:00:00+00:00
    - ISO dates: 2026-01-01   (interpreted as midnight UTC)
    - Excel-ish dates: 01/01/2026, 1/1/2026
    - Excel serial numbers: 46031
    """
    s = str(x if x is not None else "").strip()
    if not s:
        raise ValueError("empty date")
    # Excel serial date (common in .xlsx XML).
    try:
        f = float(s)
        if f > 20000:
            return _excel_serial_to_iso(f)
    except Exception:
        pass
    # Fast-path ISO-ish.
    if "T" in s:
        return _parse_ts(s).isoformat()
    # Date only.
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    except Exception:
        pass
    # Common Excel export: MM/DD/YYYY
    for fmt in ("%m/%d/%Y", "%m/%d/%y"):
        try:
            dt2 = datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
            return dt2.isoformat()
        except Exception:
            continue
    raise ValueError(f"unsupported date format: {s!r}")


def _xlsx_first_sheet_table(*, xlsx_path: str) -> list[dict[str, str]]:
    """
    Minimal .xlsx reader (stdlib-only) that extracts the first worksheet as a list of row dicts.
    Supports strings via `xl/sharedStrings.xml` and values in `xl/worksheets/sheet*.xml`.
    """
    import zipfile

    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    path = Path(xlsx_path)
    if not path.exists():
        raise FileNotFoundError(str(path))

    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        sheet_name = next((n for n in names if n.startswith("xl/worksheets/sheet") and n.endswith(".xml")), None)
        if not sheet_name:
            raise ValueError("No worksheet XML found in .xlsx")

        shared: list[str] = []
        if "xl/sharedStrings.xml" in names:
            ss = ET.fromstring(z.read("xl/sharedStrings.xml"))
            shared = [t.text or "" for t in ss.findall(".//m:si/m:t", ns)]

        ws = ET.fromstring(z.read(sheet_name))

        def col_letters(cell_ref: str) -> str:
            out = []
            for ch in cell_ref:
                if ("A" <= ch <= "Z") or ("a" <= ch <= "z"):
                    out.append(ch.upper())
                else:
                    break
            return "".join(out)

        def col_to_idx(col: str) -> int:
            n = 0
            for ch in col:
                n = n * 26 + (ord(ch) - ord("A") + 1)
            return n

        def cell_value(c) -> str:
            t = c.get("t")
            v = c.find("m:v", ns)
            if t == "s" and v is not None and v.text is not None:
                idx = int(v.text)
                return shared[idx] if 0 <= idx < len(shared) else ""
            if t == "inlineStr":
                tnode = c.find("m:is/m:t", ns)
                return tnode.text if tnode is not None and tnode.text is not None else ""
            return v.text if v is not None and v.text is not None else ""

        header: list[str] | None = None
        out_rows: list[dict[str, str]] = []
        for row in ws.findall(".//m:sheetData/m:row", ns):
            cells = row.findall("m:c", ns)
            if not cells:
                continue
            cmap: dict[str, str] = {}
            max_col = ""
            for c in cells:
                ref = c.get("r") or ""
                col = col_letters(ref)
                if not col:
                    continue
                cmap[col] = cell_value(c)
                if not max_col or col_to_idx(col) > col_to_idx(max_col):
                    max_col = col
            if not cmap:
                continue
            width = col_to_idx(max_col) if max_col else 0
            ordered = [""] * width
            for col, val in cmap.items():
                idx = col_to_idx(col) - 1
                if 0 <= idx < width:
                    ordered[idx] = val

            if header is None:
                header = [h.strip() for h in ordered]
                continue
            if not any(v.strip() for v in ordered):
                continue
            d: dict[str, str] = {}
            for i, h in enumerate(header):
                if not h:
                    continue
                d[h] = ordered[i] if i < len(ordered) else ""
            out_rows.append(d)

        return out_rows


def import_investors_csv(
    *,
    csv_path: str,
    investor_flows_path: str | None = None,
    note: str = "import",
    dry_run: bool = False,
    ts_override: str | None = None,
) -> dict:
    """
    Import investor ledger entries from a CSV export.

    Expected columns (case-insensitive):
    - code: investor initials (e.g., JL)
    - amount: USD amount (deposit=positive, withdrawal=negative)
    - joined: join date / timestamp

    Optional:
    - ts: alias for joined
    - note: per-row note (overrides `note` arg)
    - name: ignored (kept for human readability)
    """
    path_in = Path(csv_path)
    if not path_in.exists():
        raise FileNotFoundError(str(path_in))

    rows: list[dict[str, str]]
    field_map: dict[str, str]
    if path_in.suffix.lower() in (".xlsx", ".xlsm"):
        rows = _xlsx_first_sheet_table(xlsx_path=str(path_in))
        field_map = {str(k).strip().lower(): str(k) for k in (rows[0].keys() if rows else []) if k}
    else:
        with open(path_in, newline="") as f:
            r = csv.DictReader(f)
            if not r.fieldnames:
                raise ValueError("CSV has no header row")
            field_map = {str(k).strip().lower(): str(k) for k in r.fieldnames if k}
            rows = list(r)

    # Support both "code" and "Investor" header conventions.
    k_code = field_map.get("code") or field_map.get("investor") or field_map.get("initials")
    k_amt = field_map.get("amount") or field_map.get("usd") or field_map.get("contribution")
    k_joined = field_map.get("joined") or field_map.get("ts") or field_map.get("date")
    k_note = field_map.get("note")
    if not k_code or not k_amt or not k_joined:
        raise ValueError("File must include headers: code/investor, amount, joined/date (or ts)")

    parsed: list[dict] = []
    ts_override_norm = _normalize_ts(ts_override) if ts_override else None
    for row in rows:
        code = str((row.get(k_code) or "")).strip().upper()
        if not code:
            continue
        amount = _parse_money(row.get(k_amt))
        ts = ts_override_norm or _normalize_ts(row.get(k_joined))
        row_note = str(row.get(k_note) or "").strip() if k_note else ""
        parsed.append({"code": code, "amount": amount, "ts": ts, "note": row_note or note})

    parsed.sort(key=lambda x: _parse_ts(x["ts"]))

    written = 0
    out_path = investor_flows_path or default_investor_flows_path()
    for p in parsed:
        if dry_run:
            written += 1
            continue
        append_investor_flow(code=p["code"], amount=float(p["amount"]), note=p["note"], ts=p["ts"], path=out_path)
        written += 1

    return {"rows": written, "path": out_path, "preview": parsed[:5]}


def compute_unitization(
    *,
    nav_sheet_path: str | None = None,
    investor_flows_path: str | None = None,
) -> tuple[float, dict[str, float]]:
    """
    Compute a unitized NAV ledger:
    - Start nav_per_unit at 1.0
    - When investor flow happens at time t: units = amount / nav_per_unit
    - When a NAV snapshot happens at time t: nav_per_unit = equity / total_units (if total_units>0)

    Returns: (latest_nav_per_unit, units_by_investor)
    """
    nav_rows = read_nav_sheet(path=nav_sheet_path)  # sorted
    flows = read_investor_flows(path=investor_flows_path)  # sorted

    # Merge events chronologically.
    events: list[tuple[datetime, str, object]] = []
    for f in flows:
        events.append((_parse_ts(f.ts), "flow", f))
    for r in nav_rows:
        events.append((_parse_ts(r.ts), "nav", r))
    events.sort(key=lambda x: x[0])

    nav_per_unit = 1.0
    units_by: dict[str, float] = {}
    total_units = 0.0

    for _ts, kind, obj in events:
        if kind == "flow":
            f: InvestorFlow = obj  # type: ignore[assignment]
            if nav_per_unit <= 0:
                nav_per_unit = 1.0
            du = float(f.amount) / float(nav_per_unit)
            units_by[f.code] = float(units_by.get(f.code, 0.0)) + du
            total_units += du
        else:
            r = obj  # nav snapshot row
            if total_units > 0:
                nav_per_unit = float(getattr(r, "equity", 0.0)) / float(total_units)
            else:
                nav_per_unit = 1.0

    return float(nav_per_unit), units_by


def investor_report(
    *,
    nav_sheet_path: str | None = None,
    investor_flows_path: str | None = None,
) -> dict:
    nav_rows = read_nav_sheet(path=nav_sheet_path)
    last_equity = float(nav_rows[-1].equity) if nav_rows else 0.0
    nav_per_unit, units_by = compute_unitization(
        nav_sheet_path=nav_sheet_path,
        investor_flows_path=investor_flows_path,
    )
    total_units = sum(units_by.values()) if units_by else 0.0

    # Cost basis per investor is simply sum of their flows (signed).
    flows = read_investor_flows(path=investor_flows_path)
    basis_by: dict[str, float] = {}
    for f in flows:
        basis_by[f.code] = float(basis_by.get(f.code, 0.0)) + float(f.amount)

    out_rows = []
    for code in sorted(units_by.keys()):
        units = float(units_by.get(code, 0.0))
        value = units * float(nav_per_unit)
        basis = float(basis_by.get(code, 0.0))
        pnl = value - basis
        ret = (pnl / basis) if basis != 0 else None
        ownership = (units / total_units) if total_units > 0 else None
        out_rows.append(
            {
                "code": code,
                "units": units,
                "basis": basis,
                "value": value,
                "pnl": pnl,
                "return": ret,
                "ownership": ownership,
            }
        )

    return {
        "asof": nav_rows[-1].ts if nav_rows else None,
        "equity": last_equity,
        "nav_per_unit": nav_per_unit,
        "total_units": total_units,
        "rows": out_rows,
    }

