"""
Shared utilities for labs commands - Tier 1 features.

Provides consistent --features, --json, and --delta functionality across all regime commands.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone, date
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from rich import print as rprint
from rich.panel import Panel
from rich.table import Table


# ─────────────────────────────────────────────────────────────────────────────
# Snapshot Cache for Delta Tracking
# ─────────────────────────────────────────────────────────────────────────────

def _get_cache_dir() -> Path:
    """Get the cache directory for regime snapshots."""
    # Use ~/.lox/snapshots for persistent storage
    cache_dir = Path.home() / ".lox" / "snapshots"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def _snapshot_path(domain: str, dt: date) -> Path:
    """Get path for a snapshot file."""
    return _get_cache_dir() / f"{domain}_{dt.isoformat()}.json"


def save_snapshot(domain: str, snapshot: Dict[str, Any], regime: str) -> None:
    """
    Save current snapshot to cache for delta tracking.
    Called automatically after each regime computation.
    """
    today = date.today()
    path = _snapshot_path(domain, today)
    
    data = {
        "domain": domain,
        "date": today.isoformat(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "regime": regime,
        "snapshot": _serialize_snapshot(snapshot),
    }
    
    try:
        with open(path, "w") as f:
            json.dump(data, f, indent=2, default=str)
    except Exception:
        pass  # Silent fail - caching is best-effort


def load_historical_snapshot(domain: str, days_ago: int) -> Optional[Dict[str, Any]]:
    """
    Load a historical snapshot from N days ago.
    Returns None if not found.
    """
    target_date = date.today() - timedelta(days=days_ago)
    
    # Try exact date first
    path = _snapshot_path(domain, target_date)
    if path.exists():
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception:
            pass
    
    # Try nearby dates (±2 days) in case of weekends/holidays
    for offset in range(1, 3):
        for d in [target_date - timedelta(days=offset), target_date + timedelta(days=offset)]:
            path = _snapshot_path(domain, d)
            if path.exists():
                try:
                    with open(path, "r") as f:
                        data = json.load(f)
                        data["_actual_date"] = d.isoformat()
                        return data
                except Exception:
                    pass
    
    return None


def get_delta_metrics(
    domain: str,
    current_snapshot: Dict[str, Any],
    metric_keys: List[str],
    days_ago: int,
) -> tuple[List[Dict[str, Any]], str | None]:
    """
    Build metrics list with historical values for delta display.
    
    Args:
        domain: Regime domain (e.g., "fiscal")
        current_snapshot: Current snapshot dict
        metric_keys: List of keys to extract (format: "display_name:snapshot_key:unit")
        days_ago: How many days back to look
    
    Returns:
        (metrics_list, previous_regime)
    """
    historical = load_historical_snapshot(domain, days_ago)
    hist_snapshot = historical.get("snapshot", {}) if historical else {}
    prev_regime = historical.get("regime") if historical else None
    
    metrics = []
    for key_spec in metric_keys:
        parts = key_spec.split(":")
        name = parts[0]
        snap_key = parts[1] if len(parts) > 1 else name.lower().replace(" ", "_")
        unit = parts[2] if len(parts) > 2 else ""
        
        current_val = current_snapshot.get(snap_key)
        prev_val = hist_snapshot.get(snap_key)
        
        metrics.append({
            "name": name,
            "current": current_val,
            "previous": prev_val,
            "unit": unit,
        })
    
    return metrics, prev_regime


# ─────────────────────────────────────────────────────────────────────────────
# Feature Export (--features)
# ─────────────────────────────────────────────────────────────────────────────

def export_features(
    domain: str,
    features: Dict[str, Any],
    regime: str,
    asof: str | None = None,
) -> None:
    """
    Export ML-ready feature vector as JSON.
    
    Format:
    {
        "domain": "volatility",
        "regime": "COMPLACENT",
        "asof": "2026-01-20T12:00:00Z",
        "features": { ... }
    }
    """
    output = {
        "domain": domain,
        "regime": regime,
        "asof": asof or datetime.now(timezone.utc).isoformat(),
        "features": _sanitize_features(features),
    }
    print(json.dumps(output, indent=2, default=str))


def _sanitize_features(features: Dict[str, Any]) -> Dict[str, float | None]:
    """Convert all values to ML-friendly floats."""
    sanitized = {}
    for k, v in features.items():
        if v is None:
            sanitized[k] = None
        elif isinstance(v, bool):
            sanitized[k] = 1.0 if v else 0.0
        elif isinstance(v, (int, float)):
            sanitized[k] = float(v) if v == v else None  # NaN check
        elif isinstance(v, str):
            # Skip string features for ML
            continue
        else:
            # Try to convert
            try:
                sanitized[k] = float(v)
            except (TypeError, ValueError):
                continue
    return sanitized


# ─────────────────────────────────────────────────────────────────────────────
# JSON Export (--json)
# ─────────────────────────────────────────────────────────────────────────────

def export_json(
    domain: str,
    snapshot: Dict[str, Any],
    regime: str,
    regime_description: str | None = None,
    asof: str | None = None,
) -> None:
    """
    Export full snapshot as machine-readable JSON.
    
    Format:
    {
        "domain": "volatility",
        "regime": { "label": "...", "description": "..." },
        "asof": "...",
        "snapshot": { ... }
    }
    """
    output = {
        "domain": domain,
        "asof": asof or datetime.now(timezone.utc).isoformat(),
        "regime": {
            "label": regime,
            "description": regime_description or "",
        },
        "snapshot": _serialize_snapshot(snapshot),
    }
    print(json.dumps(output, indent=2, default=str))


def _serialize_snapshot(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """Serialize snapshot for JSON output."""
    result = {}
    for k, v in snapshot.items():
        if v is None:
            result[k] = None
        elif isinstance(v, (bool, int, float, str)):
            result[k] = v
        elif isinstance(v, (list, tuple)):
            result[k] = list(v)
        elif isinstance(v, dict):
            result[k] = _serialize_snapshot(v)
        elif hasattr(v, "isoformat"):
            result[k] = v.isoformat()
        else:
            result[k] = str(v)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Delta View (--delta)
# ─────────────────────────────────────────────────────────────────────────────

def parse_delta_period(delta_str: str) -> int:
    """
    Parse delta period string to days.
    
    Examples:
        "7d" -> 7
        "1w" -> 7
        "1m" -> 30
        "30" -> 30
    """
    delta_str = delta_str.lower().strip()
    
    if delta_str.endswith("d"):
        return int(delta_str[:-1])
    elif delta_str.endswith("w"):
        return int(delta_str[:-1]) * 7
    elif delta_str.endswith("m"):
        return int(delta_str[:-1]) * 30
    else:
        return int(delta_str)


def compute_delta(
    current: float | None,
    previous: float | None,
    as_percent: bool = False,
) -> tuple[float | None, str]:
    """
    Compute delta between current and previous value.
    
    Returns:
        (delta_value, formatted_string)
    """
    if current is None or previous is None:
        return None, "n/a"
    
    delta = current - previous
    
    if as_percent and previous != 0:
        pct = (delta / abs(previous)) * 100
        return delta, f"{delta:+.2f} ({pct:+.1f}%)"
    else:
        return delta, f"{delta:+.2f}"


def format_delta_table(
    title: str,
    metrics: List[Dict[str, Any]],
    delta_days: int,
) -> Table:
    """
    Create a Rich table showing current vs previous values.
    
    Each metric dict should have:
        - name: str
        - current: float | None
        - previous: float | None (optional)
        - unit: str (optional)
    """
    table = Table(title=f"{title} — Δ{delta_days}d", expand=False)
    table.add_column("Metric", style="cyan")
    table.add_column("Current", justify="right")
    table.add_column(f"{delta_days}d Ago", justify="right", style="dim")
    table.add_column("Δ", justify="right")
    table.add_column("Direction", justify="center")
    
    for m in metrics:
        name = m.get("name", "?")
        current = m.get("current")
        previous = m.get("previous")
        unit = m.get("unit", "")
        
        # Format current
        if current is None:
            curr_str = "n/a"
        else:
            curr_str = f"{current:.2f}{unit}"
        
        # Format previous
        if previous is None:
            prev_str = "n/a"
        else:
            prev_str = f"{previous:.2f}{unit}"
        
        # Compute delta
        delta_val, delta_str = compute_delta(current, previous, as_percent=False)
        
        # Direction indicator
        if delta_val is None:
            direction = "—"
        elif delta_val > 0.01:
            direction = "[green]↑[/green]"
        elif delta_val < -0.01:
            direction = "[red]↓[/red]"
        else:
            direction = "[dim]→[/dim]"
        
        table.add_row(name, curr_str, prev_str, delta_str if delta_val is not None else "n/a", direction)
    
    return table


def show_delta_summary(
    domain: str,
    current_regime: str,
    previous_regime: str | None,
    metrics: List[Dict[str, Any]],
    delta_days: int,
) -> None:
    """Show a summary panel with delta information."""
    # Regime change indicator
    if previous_regime is None:
        regime_line = f"[bold]Regime:[/bold] {current_regime}"
    elif previous_regime == current_regime:
        regime_line = f"[bold]Regime:[/bold] {current_regime} [dim](unchanged)[/dim]"
    else:
        regime_line = f"[bold]Regime:[/bold] {current_regime} [yellow](was: {previous_regime})[/yellow]"
    
    # Build table
    table = format_delta_table(domain.title(), metrics, delta_days)
    
    rprint(f"\n{regime_line}\n")
    rprint(table)


# ─────────────────────────────────────────────────────────────────────────────
# Common Output Handler
# ─────────────────────────────────────────────────────────────────────────────

def handle_output_flags(
    *,
    domain: str,
    snapshot: Dict[str, Any],
    features: Dict[str, Any],
    regime: str,
    regime_description: str | None = None,
    asof: str | None = None,
    output_json: bool = False,
    output_features: bool = False,
) -> bool:
    """
    Handle --json and --features flags.
    Also saves snapshot to cache for delta tracking.
    
    Returns True if output was handled (caller should skip normal output).
    """
    # Always save snapshot for delta tracking
    save_snapshot(domain, snapshot, regime)
    
    if output_features:
        export_features(domain, features, regime, asof)
        return True
    
    if output_json:
        export_json(domain, snapshot, regime, regime_description, asof)
        return True
    
    return False


# ─────────────────────────────────────────────────────────────────────────────
# TIER 2: Alert Detection (--alert)
# ─────────────────────────────────────────────────────────────────────────────

# Define extreme regime thresholds per domain
EXTREME_REGIMES: Dict[str, Dict[str, Any]] = {
    "volatility": {
        "extreme_regimes": ["ELEVATED", "SPIKE", "CRISIS"],
        "extreme_metrics": {"VIX": {"high": 25, "critical": 35}},
        "alert_color": "red",
    },
    "rates": {
        "extreme_regimes": ["Inverted curve", "Rates shock"],
        "extreme_metrics": {"curve_2s10s": {"low": -0.5, "critical": -1.0}},
        "alert_color": "yellow",
    },
    "commodities": {
        "extreme_regimes": ["Energy shock", "Commodity spike"],
        "extreme_metrics": {"commodity_pressure_score": {"high": 0.8, "critical": 1.2}},
        "alert_color": "red",
    },
    "monetary": {
        "extreme_regimes": ["Reserve Scarcity", "Liquidity Crisis"],
        "extreme_metrics": {"reserves_z_level": {"low": -2.0, "critical": -3.0}},
        "alert_color": "yellow",
    },
    "fiscal": {
        "extreme_regimes": ["Heavy Funding (stress)", "Auction Stress"],
        "extreme_metrics": {"deficit_pct_gdp": {"high": 7.0, "critical": 10.0}},
        "alert_color": "yellow",
    },
    "funding": {
        "extreme_regimes": ["Stress", "Dislocation", "Crisis"],
        "extreme_metrics": {"spread_corridor_bps": {"high": 5.0, "critical": 15.0}},
        "alert_color": "red",
    },
}


def check_alert_condition(
    domain: str,
    regime: str,
    snapshot: Dict[str, Any],
) -> tuple[bool, str, str]:
    """
    Check if current regime/metrics warrant an alert.
    
    Returns:
        (is_alert, alert_level, alert_message)
        alert_level: "normal", "warning", "critical"
    """
    config = EXTREME_REGIMES.get(domain.lower(), {})
    extreme_regimes = config.get("extreme_regimes", [])
    extreme_metrics = config.get("extreme_metrics", {})
    
    # Check regime name
    regime_lower = regime.lower()
    for extreme in extreme_regimes:
        if extreme.lower() in regime_lower:
            return True, "warning", f"Regime alert: {regime}"
    
    # Check metric thresholds
    for metric_key, thresholds in extreme_metrics.items():
        value = snapshot.get(metric_key)
        if value is None:
            continue
        
        # Check critical threshold
        if "critical" in thresholds:
            critical = thresholds["critical"]
            if (isinstance(critical, (int, float)) and 
                ((thresholds.get("high") and value >= critical) or 
                 (thresholds.get("low") and value <= critical))):
                return True, "critical", f"CRITICAL: {metric_key}={value:.2f} (threshold: {critical})"
        
        # Check warning threshold
        if "high" in thresholds and value >= thresholds["high"]:
            return True, "warning", f"Warning: {metric_key}={value:.2f} (threshold: {thresholds['high']})"
        if "low" in thresholds and value <= thresholds["low"]:
            return True, "warning", f"Warning: {metric_key}={value:.2f} (threshold: {thresholds['low']})"
    
    return False, "normal", "No alerts"


def show_alert_output(
    domain: str,
    regime: str,
    snapshot: Dict[str, Any],
    regime_description: str | None = None,
) -> bool:
    """
    Show alert output if conditions are met.
    Returns True if alert was shown (caller should exit), False if no alert.
    """
    is_alert, level, message = check_alert_condition(domain, regime, snapshot)
    
    if not is_alert:
        # Silent exit for cron jobs - no output means no alert
        return True
    
    # Show alert
    config = EXTREME_REGIMES.get(domain.lower(), {})
    color = config.get("alert_color", "yellow")
    
    if level == "critical":
        color = "red bold"
    
    rprint(f"\n[{color}]🚨 {domain.upper()} ALERT[/{color}]")
    rprint(f"[{color}]{message}[/{color}]")
    rprint(f"Regime: {regime}")
    if regime_description:
        rprint(f"[dim]{regime_description}[/dim]")
    rprint("")
    
    return True


# ─────────────────────────────────────────────────────────────────────────────
# TIER 2: Economic Calendar (--calendar)
# ─────────────────────────────────────────────────────────────────────────────

# Map domains to relevant economic events
# Note: FMP uses "Bill Auction", "Bond Auction" not "Treasury Auction"
DOMAIN_CALENDAR_EVENTS: Dict[str, List[str]] = {
    "volatility": ["FOMC", "CPI", "NFP", "GDP", "PCE", "Jobless Claims"],
    "rates": ["FOMC", "Bill Auction", "Bond Auction", "CPI", "PCE", "GDP", "Fed Balance Sheet"],
    "commodities": ["OPEC", "EIA", "GDP", "PMI", "Trade Balance", "Crude Oil"],
    "monetary": ["FOMC", "Fed Balance Sheet", "Fed", "Bill Auction"],
    "fiscal": ["Bill Auction", "Bond Auction", "Budget", "Debt", "Treasury Refunding"],
    "funding": ["FOMC", "Fed Balance Sheet", "Bill Auction"],
    "inflation": ["CPI", "PCE", "PPI", "Import Prices", "Core PCE"],
    "growth": ["GDP", "NFP", "Retail Sales", "ISM", "PMI", "Jobless Claims", "Employment"],
    "liquidity": ["FOMC", "Fed Balance Sheet", "Bill Auction"],
}


def fetch_economic_calendar(
    domain: str,
    days_ahead: int = 45,  # Increased from 14 to catch events further out
    max_items: int = 10,
) -> List[Dict[str, Any]]:
    """
    Fetch upcoming economic events relevant to the domain.
    Uses FMP economic calendar API.
    """
    from ai_options_trader.config import load_settings
    import requests
    
    settings = load_settings()
    if not settings.fmp_api_key:
        return []
    
    # Get relevant keywords for this domain
    keywords = DOMAIN_CALENDAR_EVENTS.get(domain.lower(), [])
    if not keywords:
        keywords = ["FOMC", "CPI", "GDP", "NFP"]  # Default macro events
    
    try:
        # Fetch calendar from FMP
        url = "https://financialmodelingprep.com/api/v3/economic_calendar"
        params = {
            "apikey": settings.fmp_api_key,
        }
        
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        events = resp.json()
        
        if not isinstance(events, list):
            return []
        
        # Filter by date range and relevance
        now = datetime.now(timezone.utc)
        cutoff = now + timedelta(days=days_ahead)
        
        relevant = []
        for event in events:
            if not isinstance(event, dict):
                continue
            
            # Parse date - FMP uses "YYYY-MM-DD HH:MM:SS" format
            event_date_str = event.get("date", "")
            try:
                # Replace space with T for ISO format compatibility
                event_date = datetime.fromisoformat(event_date_str.replace(" ", "T").replace("Z", "+00:00"))
                # Add timezone if missing
                if event_date.tzinfo is None:
                    event_date = event_date.replace(tzinfo=timezone.utc)
            except:
                continue
            
            # Check date range (future events only)
            if event_date < now or event_date > cutoff:
                continue
            
            # Check relevance to domain
            event_name = event.get("event", "").lower()
            country = event.get("country", "").upper()
            
            # Only US events for now
            if country and country != "US":
                continue
            
            is_relevant = any(kw.lower() in event_name for kw in keywords)
            if not is_relevant:
                continue
            
            relevant.append({
                "date": event_date.strftime("%Y-%m-%d"),
                "time": event_date.strftime("%H:%M") if event_date.hour else "TBD",
                "event": event.get("event", "Unknown"),
                "impact": event.get("impact", ""),
                "previous": event.get("previous"),
                "estimate": event.get("estimate"),
                "actual": event.get("actual"),
            })
        
        # Sort by date and limit
        relevant.sort(key=lambda x: x["date"])
        return relevant[:max_items]
        
    except Exception as e:
        return []


def show_calendar_output(domain: str, days_ahead: int = 45) -> None:
    """Show upcoming economic events for a domain."""
    events = fetch_economic_calendar(domain, days_ahead=days_ahead)
    
    if not events:
        rprint(f"\n[dim]No upcoming events found for {domain} in next {days_ahead} days.[/dim]")
        return
    
    table = Table(title=f"{domain.title()} — Upcoming Events ({days_ahead}d)", expand=False)
    table.add_column("Date", style="cyan")
    table.add_column("Event", style="bold")
    table.add_column("Est", justify="right")
    table.add_column("Prev", justify="right", style="dim")
    
    for event in events:
        est = f"{event['estimate']}" if event.get('estimate') is not None else "—"
        prev = f"{event['previous']}" if event.get('previous') is not None else "—"
        
        table.add_row(
            event["date"],
            event["event"][:40],
            est,
            prev,
        )
    
    rprint("")
    rprint(table)


# ─────────────────────────────────────────────────────────────────────────────
# TIER 2: Quick Trade Expressions (--trades)
# ─────────────────────────────────────────────────────────────────────────────

# Pre-defined trade expressions per regime
TRADE_EXPRESSIONS: Dict[str, Dict[str, List[Dict[str, str]]]] = {
    "volatility": {
        "COMPLACENT": [
            {"direction": "Long", "ticker": "UVXY", "rationale": "Vol cheap, buy protection"},
            {"direction": "Long", "ticker": "VXX", "rationale": "VIX low percentile entry"},
            {"direction": "Short", "ticker": "SPY puts", "rationale": "Sell premium in low vol"},
        ],
        "ELEVATED": [
            {"direction": "Short", "ticker": "VXX", "rationale": "Mean reversion after spike"},
            {"direction": "Long", "ticker": "SPY calls", "rationale": "Buy dip with vol premium"},
        ],
        "SPIKE": [
            {"direction": "Short", "ticker": "UVXY", "rationale": "Vol crush after spike"},
            {"direction": "Long", "ticker": "TLT", "rationale": "Flight to safety hedge"},
        ],
    },
    "rates": {
        "Steep curve": [
            {"direction": "Long", "ticker": "XLF", "rationale": "Banks benefit from steep curve"},
            {"direction": "Short", "ticker": "TLT", "rationale": "Duration risk in steepener"},
            {"direction": "Long", "ticker": "KRE", "rationale": "Regional banks leverage curve"},
        ],
        "Inverted curve": [
            {"direction": "Long", "ticker": "TLT", "rationale": "Recession hedge, rate cuts coming"},
            {"direction": "Short", "ticker": "XLF", "rationale": "Bank NIM compression"},
            {"direction": "Long", "ticker": "XLU", "rationale": "Defensive yield play"},
        ],
        "Flat curve": [
            {"direction": "Neutral", "ticker": "AGG", "rationale": "Low conviction, stay balanced"},
        ],
    },
    "commodities": {
        "Neutral": [
            {"direction": "Long", "ticker": "GLD", "rationale": "Diversifier, inflation hedge"},
            {"direction": "Neutral", "ticker": "DBC", "rationale": "No strong signal"},
        ],
        "Energy shock": [
            {"direction": "Long", "ticker": "XLE", "rationale": "Energy producers benefit"},
            {"direction": "Short", "ticker": "XLI", "rationale": "Input cost pressure"},
            {"direction": "Long", "ticker": "USO", "rationale": "Direct oil exposure"},
        ],
        "Metals impulse": [
            {"direction": "Long", "ticker": "GDX", "rationale": "Gold miners leverage"},
            {"direction": "Long", "ticker": "SLV", "rationale": "Silver industrial + monetary"},
        ],
    },
    "monetary": {
        "Ample Reserves": [
            {"direction": "Long", "ticker": "SPY", "rationale": "Risk-on with liquidity"},
            {"direction": "Long", "ticker": "QQQ", "rationale": "Growth benefits from liquidity"},
        ],
        "Thinning Buffers": [
            {"direction": "Long", "ticker": "BIL", "rationale": "Short duration safety"},
            {"direction": "Reduce", "ticker": "HYG", "rationale": "Credit spread widening risk"},
        ],
        "Reserve Scarcity": [
            {"direction": "Long", "ticker": "TLT", "rationale": "Flight to quality"},
            {"direction": "Short", "ticker": "HYG", "rationale": "Credit stress"},
        ],
    },
    "fiscal": {
        "benign_funding": [
            {"direction": "Neutral", "ticker": "TLT", "rationale": "No supply pressure"},
        ],
        "Heavy Funding": [
            {"direction": "Short", "ticker": "TLT", "rationale": "Supply pressure on long end"},
            {"direction": "Long", "ticker": "BIL", "rationale": "Front-end safety"},
        ],
        "Auction Stress": [
            {"direction": "Short", "ticker": "TLT", "rationale": "Duration supply overwhelm"},
            {"direction": "Long", "ticker": "GLD", "rationale": "Fiscal credibility hedge"},
        ],
    },
    "funding": {
        "Normal": [
            {"direction": "Neutral", "ticker": "BIL", "rationale": "No funding stress"},
        ],
        "Tightening": [
            {"direction": "Long", "ticker": "BIL", "rationale": "Safety in short duration"},
            {"direction": "Reduce", "ticker": "Leverage", "rationale": "Funding costs rising"},
        ],
        "Stress": [
            {"direction": "Long", "ticker": "TLT", "rationale": "Flight to quality"},
            {"direction": "Long", "ticker": "GLD", "rationale": "Systemic stress hedge"},
            {"direction": "Short", "ticker": "KRE", "rationale": "Bank funding stress"},
        ],
    },
    "inflation": {
        "Benign": [
            {"direction": "Long", "ticker": "QQQ", "rationale": "Growth favored in low inflation"},
            {"direction": "Long", "ticker": "TLT", "rationale": "Bonds benefit from stable prices"},
        ],
        "Elevated": [
            {"direction": "Long", "ticker": "TIP", "rationale": "TIPS benefit from inflation"},
            {"direction": "Long", "ticker": "XLE", "rationale": "Energy as inflation hedge"},
            {"direction": "Short", "ticker": "TLT", "rationale": "Duration risk in inflation"},
        ],
        "Hot": [
            {"direction": "Long", "ticker": "GLD", "rationale": "Gold as inflation hedge"},
            {"direction": "Long", "ticker": "XLE", "rationale": "Hard assets outperform"},
            {"direction": "Short", "ticker": "XLU", "rationale": "Utilities hurt by rising rates"},
            {"direction": "Long", "ticker": "DBC", "rationale": "Broad commodities hedge"},
        ],
        "Sticky": [
            {"direction": "Long", "ticker": "TIP", "rationale": "Persistent inflation protection"},
            {"direction": "Short", "ticker": "XLY", "rationale": "Consumer discretionary hurt"},
            {"direction": "Long", "ticker": "XLP", "rationale": "Staples have pricing power"},
        ],
    },
    "growth": {
        "Expansion": [
            {"direction": "Long", "ticker": "QQQ", "rationale": "Growth stocks in expansion"},
            {"direction": "Long", "ticker": "XLI", "rationale": "Industrials benefit from capex"},
            {"direction": "Short", "ticker": "TLT", "rationale": "Rising rates in expansion"},
        ],
        "Slowing": [
            {"direction": "Long", "ticker": "XLU", "rationale": "Defensives as growth slows"},
            {"direction": "Long", "ticker": "TLT", "rationale": "Rate cut expectations"},
            {"direction": "Short", "ticker": "XLY", "rationale": "Consumer pullback risk"},
        ],
        "Contraction": [
            {"direction": "Long", "ticker": "TLT", "rationale": "Flight to safety, rate cuts"},
            {"direction": "Long", "ticker": "XLP", "rationale": "Defensive staples"},
            {"direction": "Short", "ticker": "XLF", "rationale": "Financials hurt by recession"},
            {"direction": "Long", "ticker": "GLD", "rationale": "Safe haven asset"},
        ],
        "Recession": [
            {"direction": "Long", "ticker": "TLT", "rationale": "Aggressive rate cuts expected"},
            {"direction": "Long", "ticker": "XLU", "rationale": "Defensive yield"},
            {"direction": "Short", "ticker": "HYG", "rationale": "Credit stress"},
            {"direction": "Short", "ticker": "SPY", "rationale": "Broad equity risk"},
        ],
    },
    "liquidity": {
        "Ample": [
            {"direction": "Long", "ticker": "SPY", "rationale": "Risk-on with liquidity"},
            {"direction": "Long", "ticker": "QQQ", "rationale": "Growth benefits from liquidity"},
        ],
        "Thinning": [
            {"direction": "Long", "ticker": "BIL", "rationale": "Short duration safety"},
            {"direction": "Reduce", "ticker": "HYG", "rationale": "Credit spread widening risk"},
        ],
        "Scarcity": [
            {"direction": "Long", "ticker": "TLT", "rationale": "Flight to quality"},
            {"direction": "Short", "ticker": "HYG", "rationale": "Credit stress"},
        ],
    },
}


def get_trade_expressions(domain: str, regime: str) -> List[Dict[str, str]]:
    """Get pre-defined trade expressions for a domain/regime."""
    domain_trades = TRADE_EXPRESSIONS.get(domain.lower(), {})
    
    # Try exact match first
    if regime in domain_trades:
        return domain_trades[regime]
    
    # Try partial match
    regime_lower = regime.lower()
    for key, trades in domain_trades.items():
        if key.lower() in regime_lower or regime_lower in key.lower():
            return trades
    
    # Default fallback
    return [{"direction": "Neutral", "ticker": "—", "rationale": "No specific trade for this regime"}]


def show_trades_output(domain: str, regime: str) -> None:
    """Show quick trade expressions for current regime."""
    trades = get_trade_expressions(domain, regime)
    
    table = Table(title=f"{domain.title()} Trades — {regime}", expand=False)
    table.add_column("Direction", style="bold")
    table.add_column("Ticker", style="cyan")
    table.add_column("Rationale")
    
    for trade in trades:
        direction = trade.get("direction", "—")
        
        # Color code direction
        if direction.lower() == "long":
            dir_str = "[green]Long[/green]"
        elif direction.lower() == "short":
            dir_str = "[red]Short[/red]"
        elif direction.lower() == "reduce":
            dir_str = "[yellow]Reduce[/yellow]"
        else:
            dir_str = f"[dim]{direction}[/dim]"
        
        table.add_row(
            dir_str,
            trade.get("ticker", "—"),
            trade.get("rationale", "—"),
        )
    
    rprint("")
    rprint(table)
    rprint("\n[dim]Note: These are regime-based expressions, not recommendations. Do your own research.[/dim]")
