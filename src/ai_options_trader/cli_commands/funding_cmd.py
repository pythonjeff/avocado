from __future__ import annotations

import json

import typer
from rich import print
from rich.panel import Panel

from ai_options_trader.config import load_settings
from ai_options_trader.funding.features import funding_feature_vector
from ai_options_trader.funding.models import FundingInputs
from ai_options_trader.funding.regime import classify_funding_regime
from ai_options_trader.funding.signals import FUNDING_FRED_SERIES, build_funding_state


def run_funding_snapshot(*, start: str = "2011-01-01", refresh: bool = False, features: bool = False) -> None:
    """
    Shared implementation for funding snapshot/outlook commands.
    Kept as a top-level helper so other CLI aliases (e.g. `lox labs liquidity ...`) can call it safely.
    """
    settings = load_settings()
    state = build_funding_state(settings=settings, start_date=start, refresh=refresh)
    fi = state.inputs

    def _fmt_pct(x: object) -> str:
        return f"{float(x):.2f}%" if isinstance(x, (int, float)) else "n/a"

    def _fmt_bps(x: object) -> str:
        return f"{float(x):+.1f}bp" if isinstance(x, (int, float)) else "n/a"

    def _fmt_ratio(x: object) -> str:
        return f"{100.0*float(x):.0f}%" if isinstance(x, (int, float)) else "n/a"

    # Classify from derived inputs only (no hard-coded levels).
    regime = classify_funding_regime(
        FundingInputs(
            spread_corridor_bps=fi.spread_corridor_bps,
            spike_5d_bps=fi.spike_5d_bps,
            persistence_20d=fi.persistence_20d,
            vol_20d_bps=fi.vol_20d_bps,
            tight_threshold_bps=fi.tight_threshold_bps,
            stress_threshold_bps=fi.stress_threshold_bps,
            persistence_tight=fi.persistence_tight,
            persistence_stress=fi.persistence_stress,
            vol_tight_bps=fi.vol_tight_bps,
            vol_stress_bps=fi.vol_stress_bps,
        )
    )

    corridor_name = fi.spread_corridor_name or "SOFR-EFFR"
    baseline = _fmt_bps(fi.baseline_median_bps)
    tight_thr = _fmt_bps(fi.tight_threshold_bps)
    stress_thr = _fmt_bps(fi.stress_threshold_bps)

    body = "\n".join(
        [
            f"As of: [bold]{state.asof}[/bold]",
            "Core secured rates:",
            f"  SOFR: [bold]{_fmt_pct(fi.sofr)}[/bold] | TGCR: [bold]{_fmt_pct(fi.tgcr)}[/bold] | BGCR: [bold]{_fmt_pct(fi.bgcr)}[/bold]",
            f"  EFFR (DFF): [bold]{_fmt_pct(fi.effr)}[/bold] | IORB: [bold]{_fmt_pct(fi.iorb)}[/bold] | OBFR: [bold]{_fmt_pct(fi.obfr)}[/bold]",
            f"Corridor dislocation ({corridor_name}): [bold]{_fmt_bps(fi.spread_corridor_bps)}[/bold]",
            f"  Baseline (median ~3y): [bold]{baseline}[/bold] | Tight: [bold]{tight_thr}[/bold] | Stress: [bold]{stress_thr}[/bold]",
            f"Backup check (SOFR–EFFR): [bold]{_fmt_bps(fi.spread_sofr_effr_bps)}[/bold]",
            f"Collateral segmentation (BGCR–TGCR): [bold]{_fmt_bps(fi.spread_bgcr_tgcr_bps)}[/bold]",
            f"Spike (rolling 5d max): [bold]{_fmt_bps(fi.spike_5d_bps)}[/bold]",
            f"Persistence (20d > stress): [bold]{_fmt_ratio(fi.persistence_20d)}[/bold] | Vol (20d std): [bold]{_fmt_bps(fi.vol_20d_bps)}[/bold]",
            f"Regime: [bold]{regime.label or regime.name}[/bold]",
            f"Answer: {regime.description}",
            f"Series (FRED): [dim]{', '.join(sorted(set(FUNDING_FRED_SERIES.values()) | set(['IORB'])))}[/dim]",
        ]
    )
    print(Panel.fit(body, title="US Funding (MVP)", border_style="cyan"))

    if features:
        vec = funding_feature_vector(state)
        out = {"asof": vec.asof, **{k: vec.features[k] for k in sorted(vec.features.keys())}}
        print("\nFUNDING FEATURES (floats)")
        print(json.dumps(out, indent=2))


def register(funding_app: typer.Typer) -> None:
    @funding_app.command("snapshot")
    def funding_snapshot(
        start: str = typer.Option("2011-01-01", "--start", help="Start date YYYY-MM-DD"),
        refresh: bool = typer.Option(False, "--refresh", help="Force refresh FRED downloads"),
        features: bool = typer.Option(False, "--features", help="Print ML-friendly scalar feature vector too"),
    ):
        """
        Funding regime snapshot (secured rates MVP).

        Series:
        - SOFR, TGCR, BGCR (core)
        - EFFR (DFF) anchor
        - IORB/IOER (optional; preferred corridor anchor)
        - OBFR (optional cross-check)
        """
        run_funding_snapshot(start=start, refresh=bool(refresh), features=bool(features))

    @funding_app.command("outlook")
    def funding_outlook(
        start: str = typer.Option("2011-01-01", "--start", help="Start date YYYY-MM-DD"),
        refresh: bool = typer.Option(False, "--refresh", help="Force refresh FRED downloads"),
        features: bool = typer.Option(False, "--features", help="Print ML-friendly scalar feature vector too"),
    ):
        """Alias for `snapshot` (back-compat UX)."""
        run_funding_snapshot(start=start, refresh=bool(refresh), features=bool(features))


