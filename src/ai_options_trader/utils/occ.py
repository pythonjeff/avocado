from __future__ import annotations

from datetime import date

def parse_occ_option_symbol(symbol: str, underlying: str) -> tuple[date, str, float]:
    """Parse OCC-style option symbol like `GOOG251219C00355000`.

    Returns:
        expiry: datetime.date
        opt_type: 'call' or 'put'
        strike: float

    Notes:
        - Assumes YYMMDD + C/P + 8-digit strike with 3 decimals.
        - `underlying` must match the prefix in `symbol`.
    """
    if not symbol.startswith(underlying):
        raise ValueError(f"Symbol {symbol} does not start with underlying {underlying}.")

    rest = symbol[len(underlying):]
    if len(rest) < 6 + 1 + 8:
        raise ValueError(f"Symbol {symbol} too short to be OCC-style (YYMMDD+C/P+8 strike).")

    date_code = rest[:6]      # YYMMDD
    cp_code = rest[6]         # C or P
    strike_code = rest[7:15]  # 8 digits

    year = 2000 + int(date_code[0:2])
    month = int(date_code[2:4])
    day = int(date_code[4:6])
    expiry = date(year, month, day)

    if cp_code == "C":
        opt_type = "call"
    elif cp_code == "P":
        opt_type = "put"
    else:
        raise ValueError(f"Unknown call/put code '{cp_code}' in symbol {symbol}.")

    strike = int(strike_code) / 1000.0
    return expiry, opt_type, strike
