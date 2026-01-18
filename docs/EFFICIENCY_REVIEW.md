# Efficiency Review

## Completed

### 1. Consolidated `_safe_settings()` → `utils/settings.py`
**Impact:** HIGH  
**Files updated:** `ticker_cmd.py`, `weekly_report_cmd.py`  
**Savings:** Removed 40+ lines of duplicate code, single source of truth for fallback settings logic.

---

## Recommended Next Steps (prioritized)

### 2. Consolidate timestamp parsing → `utils/dates.py`
**Impact:** MEDIUM  
**Duplication found in:**
- `nav/store.py`: `_parse_ts()`
- `nav/investors.py`: `_normalize_ts()` + `_excel_serial_to_iso()`
- `llm/ticker_news.py`: `parse_iso8601()`
- `data/econ_release.py`: `_parse_dt_any()`

**Recommendation:** Create one canonical `parse_timestamp(s: str, tz=timezone.utc) -> datetime` that handles:
- ISO8601 (with/without Z)
- Excel serial dates
- Common date-only formats

**Estimated savings:** 80+ lines, fewer datetime bugs.

---

### 3. Pass `settings` parameter instead of reloading
**Impact:** MEDIUM (performance)  
**Pattern:** Many commands call `load_settings()` multiple times per invocation.

**Recommendation:** Load once in `register()` or command entry, pass as param to helpers.

**Estimated savings:** 2–5 `.env` file reads per CLI invocation.

---

### 4. Reuse Alpaca clients within a command
**Impact:** MEDIUM (performance + cleaner code)  
**Pattern:** Commands that need multiple API calls recreate clients.

**Examples:**
- `account_cmd.py`: creates client per sub-command
- `weekly_report_cmd.py`: creates client for positions, then again for option chains

**Recommendation:** Create once, pass around.

**Estimated savings:** 1–3 HTTP connection setups per command.

---

### 5. Helper for macro regime classification
**Impact:** LOW (code clarity)  
**Pattern:** The same 10-line `classify_macro_regime_from_state()` call repeated in 4+ commands.

**Recommendation:** Create `get_current_macro_regime(settings, start, refresh)` helper.

**Estimated savings:** 40+ lines of repeated boilerplate.

---

## How to Operate

1. Review this doc before adding new CLI commands.
2. Use `safe_load_settings()` from `utils/settings.py` instead of reimplementing fallback logic.
3. When adding timestamp parsing, check if `utils/dates.py` (if created) already handles it.
4. Prefer passing `settings` as a parameter to helpers rather than reloading.
