"""
Tariff / trade-cost proxy configuration.

Design goals:
- Include series that should react to tariff policy (import prices, export prices)
- Include domestic substitution / input-cost channels (PPI, steel)
- Include retaliatory channels (ag PPI)
- Include a broad "effective tariff rate" proxy computed from NIPA series

Notes:
- Most BLS price indices here are monthly. Your pipeline already resamples+ffills daily.
- The "effective tariff rate" is not a single FRED series; it is computed per FRED Blog:
  customs duties / imports of goods * 100.
"""

from __future__ import annotations

# ---------------------------------------------------------------------
# 1) Core cost proxies (starter set)
# ---------------------------------------------------------------------
DEFAULT_COST_PROXY_SERIES: dict[str, str] = {
    # Import/Export price indices (End Use): All Commodities
    "IMPORT_PRICE_ALL_COMMODITIES": "IR",  # Import Price Index (End Use): All Commodities
    "EXPORT_PRICE_ALL_COMMODITIES": "IQ",  # Export Price Index (End Use): All Commodities

    # Broad producer prices (domestic cost channel)
    "PPI_ALL_COMMODITIES": "PPIACO",       # Producer Price Index by Commodity: All Commodities

    # Common tariff target example: steel
    "PPI_IRON_AND_STEEL": "WPU101",        # PPI by Commodity: Metals and Metal Products: Iron and Steel

    # Retaliatory tariff exposure examples (ag / food)
    "PPI_SOYBEANS": "WPU01830131",         # Farm Products: Soybeans
    "PPI_WHEAT": "WPU0121",                # Farm Products: Wheat
    "PPI_CORN": "WPU01220205",             # Farm Products: Corn (use WPU01220205 or WPU012202; either works)
    "PPI_PORK_PRODUCTS": "WPU022104",      # Processed Foods and Feeds: Pork products (broad)
}

# Optional: initial equal weights for a composite cost proxy
# (You can later make this basket-specific; e.g., apparel focuses more on IR + consumer-goods import indices.)
DEFAULT_COST_PROXY_WEIGHTS: dict[str, float] = {
    "IMPORT_PRICE_ALL_COMMODITIES": 0.25,
    "EXPORT_PRICE_ALL_COMMODITIES": 0.05,
    "PPI_ALL_COMMODITIES": 0.20,
    "PPI_IRON_AND_STEEL": 0.10,
    "PPI_SOYBEANS": 0.10,
    "PPI_WHEAT": 0.10,
    "PPI_CORN": 0.10,
    "PPI_PORK_PRODUCTS": 0.10,
}

# ---------------------------------------------------------------------
# 2) “Effective tariff rate” components (computed series)
# ---------------------------------------------------------------------
EFFECTIVE_TARIFF_RATE_COMPONENTS: dict[str, str] = {
    # Numerator: customs duties (federal receipts)
    "CUSTOMS_DUTIES": "B235RC1Q027SBEA",

    # Denominator: imports of goods (current payments to rest of world)
    "IMPORTS_OF_GOODS": "A255RC1Q027SBEA",
}

# Convenience: name for the computed proxy if you add it to your dataset
EFFECTIVE_TARIFF_RATE_NAME = "EFFECTIVE_TARIFF_RATE_PCT"

# Formula:
# effective_tariff_rate_pct = (CUSTOMS_DUTIES / IMPORTS_OF_GOODS) * 100
