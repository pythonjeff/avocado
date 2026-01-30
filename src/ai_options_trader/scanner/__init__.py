"""
Bubble Finder / Extreme Move Scanner

Scans a universe of stocks for unusual run-ups or run-downs
and analyzes whether to bet on mean reversion.

Key Features:
- Universe scanning (S&P 500, ETFs, custom lists)
- Bubble/crash detection using z-scores and technicals
- Reason analysis (earnings, news, sector rotation)
- Reversion probability scoring
- Trade ideas generation
"""

from .bubble_finder import (
    scan_for_bubbles,
    BubbleCandidate,
    BubbleScanResult,
)

__all__ = [
    "scan_for_bubbles",
    "BubbleCandidate",
    "BubbleScanResult",
]
