"""
Liquidity Pillar - Fed balance sheet and funding market analysis.

Metrics:
- Fed Funds / IORB / SOFR
- ON RRP balance
- Bank reserves
- Fed balance sheet (WALCL)
- TGA balance
- Net Liquidity Proxy (WALCL - TGA - RRP, Howell/Bianco definition)

Author: Lox Capital Research
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Any

from lox.regimes.core import RegimePillar, Metric, register_pillar


@register_pillar("liquidity")
@dataclass
class LiquidityPillar(RegimePillar):
    """
    Liquidity regime pillar.
    
    Tracks Fed balance sheet mechanics and funding conditions:
    - Policy rates (IORB, SOFR, Fed Funds)
    - Liquidity buffers (ON RRP, reserves)
    - Treasury flows (TGA)
    - Net liquidity proxy
    """
    name: str = "Liquidity"
    description: str = "Fed balance sheet and funding conditions"
    metrics: List[Metric] = field(default_factory=list)
    
    def compute(self, settings: Any) -> None:
        """Fetch liquidity data and compute metrics."""
        from lox.data.fred import FredClient
        
        if not settings.FRED_API_KEY:
            return
        
        fred = FredClient(api_key=settings.FRED_API_KEY)
        
        # IORB (Interest on Reserve Balances)
        try:
            iorb_df = fred.fetch_series("IORB", start_date="2020-01-01")
            if iorb_df is not None and not iorb_df.empty:
                iorb_df = iorb_df.sort_values("date")
                iorb = iorb_df["value"].iloc[-1]
                
                self.metrics.append(Metric(
                    name="IORB",
                    value=iorb,
                    unit="%",
                    source="FRED:IORB",
                ))
        except Exception:
            pass
        
        # SOFR (Secured Overnight Financing Rate)
        try:
            sofr_df = fred.fetch_series("SOFR", start_date="2020-01-01")
            if sofr_df is not None and not sofr_df.empty:
                sofr_df = sofr_df.sort_values("date")
                sofr = sofr_df["value"].iloc[-1]
                
                # Weekly change
                if len(sofr_df) > 5:
                    delta_1w = sofr - sofr_df["value"].iloc[-6]
                else:
                    delta_1w = None
                
                self.metrics.append(Metric(
                    name="SOFR",
                    value=sofr,
                    unit="%",
                    delta_1w=delta_1w,
                    source="FRED:SOFR",
                ))
        except Exception:
            pass
        
        # ON RRP (Overnight Reverse Repo)
        try:
            rrp_df = fred.fetch_series("RRPONTSYD", start_date="2020-01-01")
            if rrp_df is not None and not rrp_df.empty:
                rrp_df = rrp_df.sort_values("date")
                rrp = rrp_df["value"].iloc[-1] / 1000  # Convert to $T
                
                # Weekly and monthly changes
                if len(rrp_df) > 5:
                    delta_1w = (rrp - rrp_df["value"].iloc[-6] / 1000)
                else:
                    delta_1w = None
                
                if len(rrp_df) > 22:
                    delta_1m = (rrp - rrp_df["value"].iloc[-23] / 1000)
                else:
                    delta_1m = None
                
                self.metrics.append(Metric(
                    name="ON RRP",
                    value=rrp,
                    unit="$T",
                    delta_1w=delta_1w,
                    delta_1m=delta_1m,
                    threshold_low=0.1,
                    threshold_high=0.5,
                    source="FRED:RRPONTSYD",
                ))
        except Exception:
            pass
        
        # Bank Reserves (WRESBAL) — FRED reports this in $ millions, so the
        # divisor to reach $T is 1e6, not 1e3 (that only reaches $B). The old
        # /1000 left this metric (and its 3.0/3.5 thresholds, which *were*
        # written in $T) off by 1000x — e.g. reading "$2944T" instead of
        # "$2.94T", permanently past every threshold regardless of actual
        # reserve scarcity.
        try:
            res_df = fred.fetch_series("WRESBAL", start_date="2020-01-01")
            if res_df is not None and not res_df.empty:
                res_df = res_df.sort_values("date")
                reserves = res_df["value"].iloc[-1] / 1_000_000  # $M -> $T

                if len(res_df) > 4:
                    delta_1m = (reserves - res_df["value"].iloc[-5] / 1_000_000)
                else:
                    delta_1m = None

                self.metrics.append(Metric(
                    name="Bank Reserves",
                    value=reserves,
                    unit="$T",
                    delta_1m=delta_1m,
                    threshold_low=3.0,
                    threshold_high=3.5,
                    source="FRED:WRESBAL",
                ))
        except Exception:
            pass

        # Fed Balance Sheet (WALCL) — also $ millions natively. This, not
        # Bank Reserves, is the leg Net Liquidity below is built from (see
        # _compute_net_liquidity for why).
        try:
            walcl_df = fred.fetch_series("WALCL", start_date="2020-01-01")
            if walcl_df is not None and not walcl_df.empty:
                walcl_df = walcl_df.sort_values("date")
                walcl = walcl_df["value"].iloc[-1] / 1_000_000  # $M -> $T

                if len(walcl_df) > 4:
                    delta_1m = (walcl - walcl_df["value"].iloc[-5] / 1_000_000)
                else:
                    delta_1m = None

                self.metrics.append(Metric(
                    name="Fed Balance Sheet",
                    value=walcl,
                    unit="$T",
                    delta_1m=delta_1m,
                    source="FRED:WALCL",
                ))
        except Exception:
            pass

        # TGA (Treasury General Account) — same $M-native unit issue as
        # Bank Reserves above; needs /1e6 to reach $T, not /1e3.
        try:
            tga_df = fred.fetch_series("WTREGEN", start_date="2020-01-01")
            if tga_df is not None and not tga_df.empty:
                tga_df = tga_df.sort_values("date")
                tga = tga_df["value"].iloc[-1] / 1_000_000  # $M -> $T

                if len(tga_df) > 4:
                    delta_1m = (tga - tga_df["value"].iloc[-5] / 1_000_000)
                else:
                    delta_1m = None

                self.metrics.append(Metric(
                    name="TGA",
                    value=tga,
                    unit="$T",
                    delta_1m=delta_1m,
                    source="FRED:WTREGEN",
                ))
        except Exception:
            pass

        # Compute Net Liquidity Proxy
        self._compute_net_liquidity()
        
        # Compute SOFR-IORB spread
        self._compute_funding_spread()
        
        self._compute_score()
    
    def _compute_net_liquidity(self) -> None:
        """
        Compute Net Liquidity = Fed Balance Sheet (WALCL) - TGA - ON RRP —
        the Howell/Bianco definition, matching lox.funding.net_liquidity and
        lox.funding.correlations.

        Previously this used Bank Reserves (WRESBAL) + RRP - TGA: wrong on
        two counts. Reserves already nets out most of TGA/RRP's balance-sheet
        impact, so reserves-based net liquidity double-subtracts those legs
        and has ~zero correlation to the standard WALCL-based series. And the
        RRP sign was flipped — rising RRP parks MMF cash at the Fed and
        should *reduce* net liquidity, not add to it.
        """
        walcl = self.get_metric("Fed Balance Sheet")
        rrp = self.get_metric("ON RRP")
        tga = self.get_metric("TGA")

        if all(m and m.value is not None for m in [walcl, rrp, tga]):
            net_liq = walcl.value - tga.value - rrp.value

            # Compute delta
            delta_1m = None
            if all(m.delta_1m is not None for m in [walcl, rrp, tga]):
                delta_1m = walcl.delta_1m - tga.delta_1m - rrp.delta_1m

            self.metrics.append(Metric(
                name="Net Liquidity",
                value=net_liq,
                unit="$T",
                delta_1m=delta_1m,
                threshold_low=5.5,
                threshold_high=6.5,
                source="Computed",
            ))
    
    def _compute_funding_spread(self) -> None:
        """Compute SOFR-IORB spread (funding pressure gauge)."""
        sofr = self.get_metric("SOFR")
        iorb = self.get_metric("IORB")
        
        if sofr and sofr.value is not None and iorb and iorb.value is not None:
            spread_bps = (sofr.value - iorb.value) * 100
            
            self.metrics.append(Metric(
                name="SOFR-IORB Spread",
                value=spread_bps,
                unit="bps",
                threshold_low=-5,
                threshold_high=5,
                source="Computed",
            ))
    
    def _compute_score(self) -> None:
        """Compute composite liquidity score (0-100, higher = more liquid)."""
        scores = []
        
        net_liq = self.get_metric("Net Liquidity")
        if net_liq and net_liq.value is not None:
            if net_liq.value > 6.0:
                scores.append(80)
            elif net_liq.value > 5.5:
                scores.append(60)
            elif net_liq.value > 5.0:
                scores.append(40)
            else:
                scores.append(20)
            
            # Momentum adjustment
            if net_liq.delta_1m is not None:
                if net_liq.delta_1m > 0.1:
                    scores[-1] = min(100, scores[-1] + 10)
                elif net_liq.delta_1m < -0.1:
                    scores[-1] = max(0, scores[-1] - 10)
        
        rrp = self.get_metric("ON RRP")
        if rrp and rrp.value is not None:
            # Buffer status
            if rrp.value > 0.5:
                scores.append(80)  # Buffer available
            elif rrp.value > 0.2:
                scores.append(50)  # Buffer depleting
            else:
                scores.append(20)  # Buffer depleted
        
        spread = self.get_metric("SOFR-IORB Spread")
        if spread and spread.value is not None:
            # Funding pressure
            if abs(spread.value) < 3:
                scores.append(80)  # Orderly
            elif abs(spread.value) < 10:
                scores.append(50)  # Slightly tight
            else:
                scores.append(20)  # Stressed
        
        if scores:
            self.composite_score = sum(scores) / len(scores)
        
        self.regime = self.classify()
    
    def classify(self) -> str:
        """Classify liquidity regime."""
        if self.composite_score is None:
            return "UNKNOWN"
        
        # Also check buffer status
        rrp = self.get_metric("ON RRP")
        spread = self.get_metric("SOFR-IORB Spread")
        
        score = self.composite_score
        
        # Check for stress signals
        if spread and spread.value is not None and abs(spread.value) > 10:
            return "STRESSED"
        
        if score >= 70:
            return "AMPLE"
        elif score >= 50:
            if rrp and rrp.value is not None and rrp.value < 0.2:
                return "FRAGILE"  # Buffer depleted but funding orderly
            return "ADEQUATE"
        elif score >= 30:
            return "FRAGILE"
        else:
            return "SCARCE"
    
    def buffer_status(self) -> str:
        """Determine who absorbs the next drain."""
        rrp = self.get_metric("ON RRP")
        reserves = self.get_metric("Bank Reserves")
        
        if rrp and rrp.value is not None:
            if rrp.value > 0.3:
                return "RRP buffer available"
            elif rrp.value > 0.1:
                return "RRP buffer depleting"
            else:
                return "RRP depleted - reserves absorb drains"
        
        return "Unknown"
    
    def deep_dive(self) -> dict:
        """Hedge-fund style deep dive."""
        return {
            "regime": self.regime,
            "score": self.composite_score,
            "buffer_status": self.buffer_status(),
            "metrics": {m.name: m.value for m in self.metrics},
            "flows": self._flow_analysis(),
            "interpretation": self._interpret(),
            "triggers": self._triggers(),
        }
    
    def _flow_analysis(self) -> dict:
        """Analyze liquidity flows."""
        reserves = self.get_metric("Bank Reserves")
        rrp = self.get_metric("ON RRP")
        tga = self.get_metric("TGA")
        
        flows = {
            "reserves_trend": "stable",
            "rrp_trend": "stable",
            "tga_impact": "neutral",
        }
        
        if reserves and reserves.delta_1m is not None:
            if reserves.delta_1m > 0.05:
                flows["reserves_trend"] = "rising"
            elif reserves.delta_1m < -0.05:
                flows["reserves_trend"] = "falling"
        
        if rrp and rrp.delta_1m is not None:
            if rrp.delta_1m > 0.05:
                flows["rrp_trend"] = "rising"
            elif rrp.delta_1m < -0.05:
                flows["rrp_trend"] = "falling"
        
        if tga and tga.delta_1m is not None:
            if tga.delta_1m > 0.05:
                flows["tga_impact"] = "drain"  # TGA up = liquidity drain
            elif tga.delta_1m < -0.05:
                flows["tga_impact"] = "add"  # TGA down = liquidity add
        
        return flows
    
    def _triggers(self) -> List[str]:
        """Identify liquidity stress triggers."""
        triggers = []
        
        spread = self.get_metric("SOFR-IORB Spread")
        if spread and spread.value is not None and spread.value > 5:
            triggers.append(f"SOFR-IORB spread widening ({spread.value:.0f}bp)")
        
        rrp = self.get_metric("ON RRP")
        if rrp and rrp.value is not None and rrp.value < 0.1:
            triggers.append("ON RRP buffer depleted")
        
        net_liq = self.get_metric("Net Liquidity")
        if net_liq and net_liq.delta_1m is not None and net_liq.delta_1m < -0.2:
            triggers.append(f"Net liquidity draining (${net_liq.delta_1m:.1f}T/mo)")
        
        return triggers
    
    def _interpret(self) -> str:
        """Generate interpretation."""
        parts = []
        
        regime = self.regime
        if regime == "AMPLE":
            parts.append("Liquidity conditions remain ample.")
        elif regime == "ADEQUATE":
            parts.append("Liquidity adequate but watch for drains.")
        elif regime == "FRAGILE":
            parts.append("Liquidity fragile — buffer depleted but funding orderly.")
        elif regime == "STRESSED":
            parts.append("Funding stress detected — watch for spillovers.")
        elif regime == "SCARCE":
            parts.append("Liquidity scarce — elevated volatility risk.")
        
        triggers = self._triggers()
        if triggers:
            parts.append(f"Active triggers: {', '.join(triggers)}.")
        
        return " ".join(parts) if parts else "Insufficient data."
