"""
Historical bubble reference points for context comparisons.

Each entry holds peak-ish readings near the headline top.  Values are
approximate (sources vary) and chosen to be the figures commonly cited in
the literature so readers can do a sanity check.  All US ratios are unit-
consistent with the live metrics (Buffett indicator = corp-equities mkt value
/ GDP × 100; top-10 share = % of cap-weighted index; margin debt/GDP × 100).

International peaks (1989 Nikkei, 2015 Shanghai A-shares) use the same
formulas applied to local market cap / local GDP — broadly comparable but
flagged via `region` so the similarity scorer doesn't mix corridors.

Coverage:

  1929 — Great Depression (Sept 1929)
    Buffett ~75%, top-10 ~30%, margin/GDP ~9%, CAPE 32.6.  Drawdown -86%
    over 34 months; nominal S&P recovery ~25 years.

  1968 — Nifty Fifty peak (Dec 1968)
    Buffett ~80%, top-10 ~40% (Nifty 50 dominated weight), margin/GDP ~1.2%,
    CAPE ~22, HH-equity ~36% (the prior record).  Drawdown peak-to-1974 ~
    -48%; nominal recovery 13y to 1982.  Most useful concentration parallel
    for today's mag-7 setup.

  1987 — Black Monday (Aug 1987 peak)
    Buffett ~60%, top-10 ~25%, margin/GDP ~1.4%, CAPE ~18.  Drawdown -34%
    in 2 months (Black Monday -22% single day).  Recovered in 18 months —
    fast Fed-rescue precedent.

  1989 — Japan Nikkei (Dec 1989) — INTERNATIONAL
    Buffett-equiv ~140%, top-10 ~30% (banks + NTT), CAPE ~75 (the famous
    one), HH-equity ~20%.  Drawdown -82% over ~14 years; Nikkei finally
    recovered nominal high in Feb 2024 — 35 years.  Tail-risk benchmark.

  2000 — Dot-com (March 2000)
    Buffett ~145%, top-10 ~26%, margin/GDP ~2.6%, CAPE 44 (record),
    HH-equity ~32%.  Drawdown -49% S&P / -78% NDX over 30 months; nominal
    SPX recovery 7y, real recovery 13y.

  2007 — Pre-GFC (Oct 2007)
    Buffett ~105%, top-10 ~20%, margin/GDP ~2.7%, CAPE ~27, HH-equity ~30%.
    Drawdown -57% over 17 months; recovery ~5.5y (Mar 2013).  "Valuation
    tame, credit was the bubble" — anti-AI-bubble comparison.

  2015 — Shanghai A-shares (June 2015) — INTERNATIONAL
    Buffett-equiv ~100%, margin/GDP ~3-4%, CAPE ~40.  Drawdown -45% in
    3 months; Shanghai composite still ~40% below the 2015 high.  Retail
    margin mania archetype.

  2021 — Post-COVID (Nov 2021)
    Buffett ~200%, top-10 ~30%, margin/GDP ~3.6%, CAPE 38.6, HH-equity 36%.
    Drawdown -25% S&P / -33% NDX over 10 months; recovery ~24 months.

Similarity scoring (US peaks only) uses the three metrics we currently
compute live (Buffett, top-10, margin/GDP).  Adding CAPE / HH-equity to the
live computation later promotes them automatically.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import sqrt


@dataclass(frozen=True)
class BubblePeak:
    name: str
    year: int
    region: str                       # "US" | "Japan" | "China"
    buffett_pct: float | None
    cape: float | None                # Shiller CAPE at peak
    top10_share_pct: float | None
    margin_to_gdp_pct: float | None
    hh_equity_pct: float | None       # household-equity as % of financial assets
    drawdown_pct: float | None        # peak-to-trough drawdown that followed (negative)
    recover_months: int | None        # months to nominal new high; None = still recovering
    note: str


# Order: chronological. Today's row is appended at render time.
HISTORICAL_BUBBLES: tuple[BubblePeak, ...] = (
    BubblePeak(
        name="1929 — Great Depression", year=1929, region="US",
        buffett_pct=75.0, cape=32.6, top10_share_pct=30.0,
        margin_to_gdp_pct=9.0, hh_equity_pct=28.0,
        drawdown_pct=-86.0, recover_months=300,
        note="10x margin retail mania",
    ),
    BubblePeak(
        name="1968 — Nifty Fifty", year=1968, region="US",
        buffett_pct=80.0, cape=22.0, top10_share_pct=40.0,
        margin_to_gdp_pct=1.2, hh_equity_pct=36.0,
        drawdown_pct=-48.0, recover_months=156,
        note="concentration era — closest mag-7 parallel",
    ),
    BubblePeak(
        name="1987 — Black Monday", year=1987, region="US",
        buffett_pct=60.0, cape=18.0, top10_share_pct=25.0,
        margin_to_gdp_pct=1.4, hh_equity_pct=18.0,
        drawdown_pct=-34.0, recover_months=18,
        note="portfolio insurance crash — fast Fed rescue",
    ),
    BubblePeak(
        name="1989 — Japan Nikkei", year=1989, region="Japan",
        buffett_pct=140.0, cape=75.0, top10_share_pct=30.0,
        margin_to_gdp_pct=None, hh_equity_pct=20.0,
        drawdown_pct=-82.0, recover_months=420,
        note="30y unwind — the tail-risk benchmark",
    ),
    BubblePeak(
        name="2000 — Dot-com", year=2000, region="US",
        buffett_pct=145.0, cape=44.2, top10_share_pct=26.0,
        margin_to_gdp_pct=2.6, hh_equity_pct=32.0,
        drawdown_pct=-49.0, recover_months=84,
        note="TMT-led, no broad leverage",
    ),
    BubblePeak(
        name="2007 — Pre-GFC", year=2007, region="US",
        buffett_pct=105.0, cape=27.3, top10_share_pct=20.0,
        margin_to_gdp_pct=2.7, hh_equity_pct=30.0,
        drawdown_pct=-57.0, recover_months=66,
        note="valuation tame — credit was the bubble",
    ),
    BubblePeak(
        name="2015 — Shanghai A-shares", year=2015, region="China",
        buffett_pct=100.0, cape=40.0, top10_share_pct=None,
        margin_to_gdp_pct=3.5, hh_equity_pct=10.0,
        drawdown_pct=-45.0, recover_months=None,
        note="retail margin mania — never recovered",
    ),
    BubblePeak(
        name="2021 — Post-COVID", year=2021, region="US",
        buffett_pct=200.0, cape=38.6, top10_share_pct=30.0,
        margin_to_gdp_pct=3.6, hh_equity_pct=36.0,
        drawdown_pct=-25.0, recover_months=24,
        note="broad mania, record margin",
    ),
)


# ─────────────────────────────────────────────────────────────────────────────
# Similarity scoring — which historical US peak does today most resemble?
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SimilarityResult:
    peak_name: str
    similarity: float       # 0..1, higher = more similar
    distance: float         # raw normalized Euclidean distance
    components: dict        # per-metric contributions (for transparency)


# Metrics used in similarity — only those we compute LIVE today. Adding
# CAPE/HH-equity to today's snapshot in the future promotes them here
# automatically (would also need to add to peak fields, already done).
_SIMILARITY_METRICS = (
    "buffett_pct",
    "top10_share_pct",
    "margin_to_gdp_pct",
)


def compute_similarity(
    today: dict,
    peaks: tuple[BubblePeak, ...] = HISTORICAL_BUBBLES,
    *,
    same_region_only: str | None = "US",
) -> list[SimilarityResult]:
    """
    Rank historical peaks by similarity to today's reading.

    Args:
        today: dict with keys matching peak field names. Missing keys are
               treated as unknown and excluded from that comparison.
        peaks: pool of historical peaks to rank against.
        same_region_only: filter peaks to this region (default "US"). Set to
               None to rank across all regions — but cross-region scoring is
               apples-to-oranges (Buffett indicator is country-specific).

    Returns: list of SimilarityResult, descending by similarity.

    Method: scale each metric to [0,1] using the full range across the peak
    set + today, compute Euclidean distance, convert to similarity via
    1 / (1 + distance). Only metrics where BOTH today and the peak have a
    value contribute (no penalization for missing data — but a peak with
    only one shared metric gets a wider effective range, so its distance is
    typically larger and similarity smaller).
    """
    candidates = peaks
    if same_region_only:
        candidates = tuple(p for p in peaks if p.region == same_region_only)

    # Build per-metric normalization range from candidates + today
    ranges: dict[str, tuple[float, float]] = {}
    for m in _SIMILARITY_METRICS:
        vals = [getattr(p, m) for p in candidates if getattr(p, m) is not None]
        today_v = today.get(m)
        if today_v is not None:
            vals.append(today_v)
        if len(vals) < 2:
            continue
        ranges[m] = (min(vals), max(vals))

    if not ranges:
        return []

    def _norm(v: float, lo: float, hi: float) -> float:
        if hi == lo:
            return 0.5
        return (v - lo) / (hi - lo)

    results: list[SimilarityResult] = []
    for peak in candidates:
        components: dict[str, float] = {}
        sq_sum = 0.0
        n = 0
        for m in _SIMILARITY_METRICS:
            if m not in ranges:
                continue
            today_v = today.get(m)
            peak_v = getattr(peak, m)
            if today_v is None or peak_v is None:
                continue
            lo, hi = ranges[m]
            d = _norm(today_v, lo, hi) - _norm(peak_v, lo, hi)
            sq = d * d
            components[m] = sq
            sq_sum += sq
            n += 1
        if n == 0:
            continue
        # Average squared distance across available dimensions, then sqrt for
        # comparability across peaks with different dimension counts.
        distance = sqrt(sq_sum / n)
        similarity = 1.0 / (1.0 + distance)
        results.append(SimilarityResult(
            peak_name=peak.name,
            similarity=similarity,
            distance=distance,
            components=components,
        ))

    results.sort(key=lambda r: r.similarity, reverse=True)
    return results


def format_recover_months(months: int | None) -> str:
    """Render the recovery-time field compactly: '18m', '7y', '25y+', '—'."""
    if months is None:
        return "—"
    if months < 12:
        return f"{months}m"
    years = months / 12.0
    if years >= 100:
        return f"{int(years)}y"  # for 1989 Nikkei etc.
    if years >= 10:
        return f"{int(round(years))}y"
    return f"{years:.1f}y"
