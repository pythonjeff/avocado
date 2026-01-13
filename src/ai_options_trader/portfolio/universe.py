from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PortfolioUniverse:
    """
    Default "macro pod" universe:
    - Core equity beta proxies
    - Rates / duration
    - Credit
    - USD
    - Gold
    - Sectors

    v1 executes equities/ETFs only (no options, no crypto execution).
    """

    basket_equity: tuple[str, ...]
    tradable: tuple[str, ...]


DEFAULT_UNIVERSE = PortfolioUniverse(
    basket_equity=("SPY", "QQQ", "IWM", "XLF", "XLK", "XLE"),
    tradable=(
        "SPY",
        "QQQ",
        "IWM",
        "TLT",
        "HYG",
        "LQD",
        "UUP",
        "GLD",
        "XLF",
        "XLK",
        "XLE",
    ),
)

# "Starter" universe: lower-dollar, liquid, optionable, and diversified across key macro exposures.
# Notes:
# - Prefer lower share-price ETFs for small accounts (Alpaca supports fractional shares, but options do not).
# - Use ETF proxies for metals/bitcoin to keep execution in the equity/ETF lane.
STARTER_UNIVERSE = PortfolioUniverse(
    basket_equity=(
        # Equity beta proxies (lower-priced share classes where possible)
        "SPY",   # S&P 500 (most universally tradable + deepest options)
        "QQQM",  # Nasdaq-100 (lower $/share than QQQ)
        "IWM",   # Small caps
        # Key macro hedges / diversifiers
        "UUP",   # USD
        "GLDM",  # Gold (lower $/share than GLD)
        "SLV",   # Silver
        "DBC",   # Broad commodities (liquid, optionable)
        "IBIT",  # Bitcoin ETF proxy (alternatives: BITO; keep configurable)
        "VIXY",  # Volatility (VIX short-term futures proxy; long-vol expression)
        # Rates / defensives
        "SHY",   # 1-3y Treasuries (cash-like)
        "IEF",   # 7-10y Treasuries (belly duration)
        "TLT",   # Long duration
        "TIP",   # TIPS (inflation-linked duration)
        # Credit
        "HYG",   # HY credit beta
        "LQD",   # IG credit (quality spread / duration-credit blend)
        # Simple hedges / distinct equity sleeves (liquid, optionable)
        "SH",    # -1x S&P 500 (simple equity hedge)
        "TBT",   # Inverse long duration (rates up)
        "SMH",   # Semiconductors (growth/duration proxy)
        "KRE",   # Regional banks (rates/credit transmission)
    ),
    tradable=(
        # Keep tradable superset stable and modest for data pulls
        "SPY",
        "QQQM",
        "IWM",
        "UUP",
        "GLDM",
        "SLV",
        "DBC",
        "IBIT",
        "VIXY",
        "SHY",
        "IEF",
        "TLT",
        "TIP",
        "HYG",
        "LQD",
        "SH",
        "TBT",
        "SMH",
        "KRE",
        # Optional sector tilts (still liquid; may be pricier but useful)
        "XLF",
        "XLE",
    ),
)


# "Extended" universe: broaden cross-section while staying in the macro/options ideology.
# Goals:
# - Highly liquid + optionable tickers (ETFs + a small set of mega-cap stocks)
# - Add inverse/hedge instruments (not just adjacent clones)
# - Avoid redundant duplicates (e.g., don't add a second S&P 500 wrapper if SPY is already present)
EXTENDED_UNIVERSE = PortfolioUniverse(
    basket_equity=tuple(
        dict.fromkeys(
            (
                # Core (keep starter)
                *STARTER_UNIVERSE.basket_equity,
                # Broad styles / equity slices
                "DIA",   # Dow / industrial cyclicality
                "IWN",   # Russell 2000 value (adjacent but meaningfully different from IWM)
                "IWO",   # Russell 2000 growth
                # Sectors (liquid, optionable)
                "XLV",   # Health care (defensive growth)
                "XLI",   # Industrials (cycle)
                "XLP",   # Staples (defensive)
                "XLY",   # Discretionary (cycle)
                "XLU",   # Utilities (rates-sensitive defensive)
                "XLB",   # Materials (cycle/commod linkage)
                # Thematic risk-on / risk-off
                "SMH",   # Semiconductors (rates/AI beta)
                "ARKK",  # High beta / duration proxy
                "KRE",   # Regional banks (rates/credit sensitivity)
                "XBI",   # Biotech (risk appetite)
                # Real assets / commodity adjacencies
                "CPER",  # Copper (industrial cycle)
                "USO",   # Oil (energy shock)
                "GDX",   # Gold miners (levered gold / real rates)
                # Rates / convexity / inverse-style hedges (optionable)
                "TBT",   # Inverse long duration (rates up)
                "SH",    # -1x S&P (equity hedge)
                "PSQ",   # -1x Nasdaq-100 (tech hedge)
                # Leveraged inverse ETFs (use with care; higher decay / path-dependence)
                "SDS",   # -2x S&P 500
                "SPXU",  # -3x S&P 500
                "QID",   # -2x Nasdaq-100
                "SQQQ",  # -3x Nasdaq-100
                "RWM",   # -1x Russell 2000
                "TWM",   # -2x Russell 2000
                "TZA",   # -3x Russell 2000
                "DOG",   # -1x Dow
                "DXD",   # -2x Dow
                "TBF",   # -1x 20+Y Treasury
                "TMV",   # -3x 20+Y Treasury
                "SJB",   # -1x High Yield (short HYG proxy)
                "SVXY",  # short-vol proxy (inverse-ish to VIX products; use with caution)
                # Inflation-protected / rate-linked
                "TIP",   # TIPS
                # International (USD/flow sensitivity)
                "EEM",   # Emerging markets
                "EFA",   # Developed ex-US
                # Mega-cap "stocks in the space" (very liquid options)
                "AAPL",
                "MSFT",
                "NVDA",
                "JPM",
                "XOM",
            )
        )
    ),
    tradable=tuple(
        dict.fromkeys(
            (
                *STARTER_UNIVERSE.tradable,
                # Add all extended basket tickers to tradable superset
                *(
                    "DIA",
                    "IWN",
                    "IWO",
                    "XLV",
                    "XLI",
                    "XLP",
                    "XLY",
                    "XLU",
                    "XLB",
                    "SMH",
                    "ARKK",
                    "KRE",
                    "XBI",
                    "CPER",
                    "USO",
                    "GDX",
                    "TBT",
                    "SH",
                    "PSQ",
                    "SDS",
                    "SPXU",
                    "QID",
                    "SQQQ",
                    "RWM",
                    "TWM",
                    "TZA",
                    "DOG",
                    "DXD",
                    "TBF",
                    "TMV",
                    "SJB",
                    "SVXY",
                    "TIP",
                    "EEM",
                    "EFA",
                    "AAPL",
                    "MSFT",
                    "NVDA",
                    "JPM",
                    "XOM",
                ),
            )
        )
    ),
)


# Housing / MBS basket: focused sleeve for housing cycle + mortgage rates + mortgage-backed securities proxies.
HOUSING_UNIVERSE = PortfolioUniverse(
    basket_equity=(
        # Mortgage-backed securities (agency MBS proxy ETFs)
        "MBB",   # iShares MBS ETF
        "VMBS",  # Vanguard MBS ETF
        # Housing / builders
        "ITB",   # US home construction
        "XHB",   # homebuilders (broader)
        # REITs / real estate beta
        "VNQ",   # Vanguard REIT
        "IYR",   # iShares US Real Estate
        # Inverse real estate (non-option expressions)
        "REK",   # -1x real estate
        "SRS",   # -2x real estate (more aggressive / more decay)
        # Rate anchors / hedges
        "IEF",   # 7-10y Treasuries
        "TLT",   # long duration
        "SHY",   # front-end / cash proxy
        # Equity beta baseline
        "SPY",
    ),
    tradable=(
        "MBB",
        "VMBS",
        "ITB",
        "XHB",
        "VNQ",
        "IYR",
        "REK",
        "SRS",
        "IEF",
        "TLT",
        "SHY",
        "SPY",
    ),
)


def get_universe(name: str) -> PortfolioUniverse:
    """
    Resolve a named universe:
    - starter
    - extended
    - default
    """
    n = (name or "starter").strip().lower()
    if n.startswith("e"):
        return EXTENDED_UNIVERSE
    if n.startswith("h"):
        return HOUSING_UNIVERSE
    if n.startswith("d"):
        return DEFAULT_UNIVERSE
    return STARTER_UNIVERSE
