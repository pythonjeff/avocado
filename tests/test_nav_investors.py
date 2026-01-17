from __future__ import annotations

from pathlib import Path

from ai_options_trader.nav.investors import append_investor_flow, investor_report
from ai_options_trader.nav.store import append_nav_snapshot


def test_investor_unitization_basic(tmp_path: Path):
    sheet = str(tmp_path / "nav_sheet.csv")
    inv_flows = str(tmp_path / "nav_investor_flows.csv")

    # Two investors deposit before first snapshot.
    append_investor_flow(ts="2026-01-01T00:00:00+00:00", code="JL", amount=75.0, note="seed", path=inv_flows)
    append_investor_flow(ts="2026-01-01T00:00:00+00:00", code="TG", amount=100.0, note="seed", path=inv_flows)

    # First snapshot: equity is sum of deposits.
    append_nav_snapshot(
        ts="2026-01-01T12:00:00+00:00",
        equity=175.0,
        cash=175.0,
        buying_power=175.0,
        positions_count=0,
        note="start",
        sheet_path=sheet,
        flows_path=str(tmp_path / "unused.csv"),
    )

    # Account grows to 210 with no new investor flows => nav_per_unit increases.
    append_nav_snapshot(
        ts="2026-02-01T00:00:00+00:00",
        equity=210.0,
        cash=210.0,
        buying_power=210.0,
        positions_count=0,
        note="up",
        sheet_path=sheet,
        flows_path=str(tmp_path / "unused.csv"),
    )

    rep = investor_report(nav_sheet_path=sheet, investor_flows_path=inv_flows)
    assert rep["equity"] == 210.0
    rows = {r["code"]: r for r in rep["rows"]}

    # Ownership should be proportional to deposits (since both deposited at same nav_per_unit).
    assert abs(rows["JL"]["ownership"] - (75.0 / 175.0)) < 1e-9
    assert abs(rows["TG"]["ownership"] - (100.0 / 175.0)) < 1e-9

    # Values should sum (approximately) to equity.
    total_value = sum(r["value"] for r in rep["rows"])
    assert abs(total_value - 210.0) < 1e-6


def test_investor_flow_between_nav_snapshots_does_not_distort_existing_investors(tmp_path: Path):
    """
    If an investor contributes between NAV snapshots, units should be issued at the latest known nav_per_unit,
    and the next NAV snapshot should incorporate the cash so existing investors are not diluted.
    """
    sheet = str(tmp_path / "nav_sheet.csv")
    inv_flows = str(tmp_path / "nav_investor_flows.csv")

    # Seed JL with $100 and take first NAV snapshot.
    append_investor_flow(ts="2026-01-01T00:00:00+00:00", code="JL", amount=100.0, note="seed", path=inv_flows)
    append_nav_snapshot(
        ts="2026-01-01T12:00:00+00:00",
        equity=100.0,
        cash=100.0,
        buying_power=100.0,
        positions_count=0,
        note="start",
        sheet_path=sheet,
        flows_path=str(tmp_path / "unused.csv"),
    )

    # TG contributes $100 after the snapshot.
    append_investor_flow(ts="2026-01-01T12:00:01+00:00", code="TG", amount=100.0, note="add", path=inv_flows)

    # Next NAV snapshot includes the cash (equity increases by $100; no PnL).
    append_nav_snapshot(
        ts="2026-01-01T18:00:00+00:00",
        equity=200.0,
        cash=200.0,
        buying_power=200.0,
        positions_count=0,
        note="after deposit",
        sheet_path=sheet,
        flows_path=str(tmp_path / "unused.csv"),
    )

    rep = investor_report(nav_sheet_path=sheet, investor_flows_path=inv_flows)
    rows = {r["code"]: r for r in rep["rows"]}
    # Both should have basis==value and ~0 pnl immediately after the deposit-driven snapshot.
    assert abs(rows["JL"]["pnl"]) < 1e-6
    assert abs(rows["TG"]["pnl"]) < 1e-6


def test_investor_import_xlsx_excel_serial_dates(tmp_path: Path):
    # Build a minimal .xlsx (zip) that our stdlib reader can parse.
    xlsx = tmp_path / "investors.xlsx"
    import zipfile

    shared_strings = [
        "Investor",
        "Amount",
        "Date",
        "JL",
    ]
    shared_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="4" uniqueCount="4">'
        + "".join(f"<si><t>{s}</t></si>" for s in shared_strings)
        + "</sst>"
    )
    # Row 1: headers (shared strings 0,1,2); Row 2: JL, 150, 46031
    sheet_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        "<sheetData>"
        '<row r="1">'
        '<c r="A1" t="s"><v>0</v></c>'
        '<c r="B1" t="s"><v>1</v></c>'
        '<c r="C1" t="s"><v>2</v></c>'
        "</row>"
        '<row r="2">'
        '<c r="A2" t="s"><v>3</v></c>'
        '<c r="B2"><v>150</v></c>'
        '<c r="C2"><v>46031</v></c>'
        "</row>"
        "</sheetData>"
        "</worksheet>"
    )
    with zipfile.ZipFile(xlsx, "w") as z:
        z.writestr("xl/sharedStrings.xml", shared_xml)
        z.writestr("xl/worksheets/sheet1.xml", sheet_xml)

    inv_flows = str(tmp_path / "nav_investor_flows.csv")
    rep = append_investor_flow  # keep lint quiet about unused imports
    from ai_options_trader.nav.investors import import_investors_csv, read_investor_flows

    out = import_investors_csv(csv_path=str(xlsx), investor_flows_path=inv_flows, note="seed")
    assert out["rows"] == 1
    flows = read_investor_flows(path=inv_flows)
    assert len(flows) == 1
    assert flows[0].code == "JL"
    assert abs(flows[0].amount - 150.0) < 1e-9
    # Should have been converted to an ISO timestamp.
    assert "T" in flows[0].ts


def test_investor_import_ts_override(tmp_path: Path):
    inv_csv = tmp_path / "investors.csv"
    inv_csv.write_text("code,amount,joined\nJL,100,2026-01-01\nTG,200,2026-01-02\n")

    inv_flows = str(tmp_path / "nav_investor_flows.csv")
    from ai_options_trader.nav.investors import import_investors_csv, read_investor_flows

    out = import_investors_csv(csv_path=str(inv_csv), investor_flows_path=inv_flows, ts_override="2026-02-01", note="seed")
    assert out["rows"] == 2
    flows = read_investor_flows(path=inv_flows)
    assert len(flows) == 2
    assert flows[0].ts.startswith("2026-02-01")
    assert flows[1].ts.startswith("2026-02-01")

