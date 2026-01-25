from __future__ import annotations

import json
import select
import sys
import threading
import time
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import typer
import pandas as pd
from rich.console import Console
from rich.panel import Panel

from ai_options_trader.config import load_settings
from ai_options_trader.data.alpaca import make_clients
from ai_options_trader.execution.alpaca import CryptoOrderPreview, submit_crypto_order
from ai_options_trader.regimes.feature_matrix import build_regime_feature_matrix


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _jsonl_append(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False, default=str) + "\n")


def _to_f(x) -> float | None:
    try:
        return float(x) if x is not None else None
    except Exception:
        return None


def _pair_to_trade_symbol(pair: str) -> str:
    # Alpaca trading symbols are commonly "BTCUSD" while data symbols are "BTC/USD".
    return pair.strip().upper().replace("/", "")


def _coin_from_pair(pair: str) -> str:
    s = pair.strip().upper()
    if "/" in s:
        return s.split("/", 1)[0].strip()
    return s


def _resolve_pair(token: str, pairs: list[str]) -> str | None:
    """
    Resolve user input like "ETH" or "ETH/USD" to a configured pair string (e.g., "ETH/USD").
    """
    t = token.strip().upper()
    if not t:
        return None
    # Exact match on pair
    for p in pairs:
        if t == p.strip().upper():
            return p
    # Match by coin prefix (ETH -> ETH/USD)
    for p in pairs:
        if t == _coin_from_pair(p):
            return p
    # Allow "ETHUSD" (trade symbol)
    for p in pairs:
        if t.replace("/", "") == _pair_to_trade_symbol(p):
            return p
    return None


def _read_line_nonblocking() -> str | None:
    """
    Best-effort non-blocking stdin line read (unix-like terminals).
    Returns a full line (without newline) or None if no input is available.
    """
    try:
        r, _w, _x = select.select([sys.stdin], [], [], 0.0)
        if r:
            line = sys.stdin.readline()
            if not line:
                return None
            return line.strip()
        return None
    except Exception:
        return None


def _format_pct(x: float | None) -> str:
    if x is None:
        return "—"
    return f"{x:+.2f}%"


def _format_usd(x: float | None) -> str:
    if x is None:
        return "—"
    return f"${x:,.2f}"


def _start_crypto_price_stream(
    *,
    api_key: str,
    api_secret: str,
    pairs: list[str],
    shared_prices: dict[str, float],
    shared_asof: dict[str, str],
    lock: threading.Lock,
    console: Console,
    meta: dict[str, float],
) -> tuple[object | None, threading.Thread | None]:
    """
    Best-effort websocket stream for crypto trades.
    Updates `shared_prices` and `shared_asof` in-place.

    Returns (stream_obj, thread) or (None, None) if unavailable.
    """
    CryptoDataStream = None
    try:
        from alpaca.data.live import CryptoDataStream as _CryptoDataStream  # type: ignore

        CryptoDataStream = _CryptoDataStream
    except Exception:
        try:
            from alpaca.data.live.crypto import CryptoDataStream as _CryptoDataStream  # type: ignore

            CryptoDataStream = _CryptoDataStream
        except Exception:
            CryptoDataStream = None

    if CryptoDataStream is None:
        return None, None

    try:
        stream = CryptoDataStream(api_key, api_secret)
    except Exception as e:
        console.print(Panel(f"[yellow]Crypto stream init failed[/yellow]\n\n{e}", title="Live stream", expand=False))
        return None, None

    async def _on_trade(trade) -> None:
        try:
            sym = getattr(trade, "symbol", None) or getattr(trade, "S", None)
            px = getattr(trade, "price", None) or getattr(trade, "p", None)
            ts = getattr(trade, "timestamp", None) or getattr(trade, "t", None)
            if sym is None or px is None:
                return
            s = str(sym).upper()
            fpx = _to_f(px)
            if fpx is None:
                return
            with lock:
                shared_prices[s] = float(fpx)
                if ts is not None:
                    shared_asof[s] = str(ts)
                meta["msg_count"] = float(meta.get("msg_count", 0.0) + 1.0)
                meta["last_recv_unix"] = float(time.time())
        except Exception:
            return

    def _runner() -> None:
        try:
            # Subscribe and run; SDK owns its event loop.
            try:
                stream.subscribe_trades(_on_trade, *[p.upper() for p in pairs])
            except TypeError:
                # Some SDK versions accept list-style symbols.
                stream.subscribe_trades(_on_trade, [p.upper() for p in pairs])
            stream.run()
        except Exception as e:
            console.print(Panel(f"[yellow]Crypto stream stopped[/yellow]\n\n{e}", title="Live stream", expand=False))

    t = threading.Thread(target=_runner, name="lox-crypto-stream", daemon=True)
    t.start()
    return stream, t


def _fetch_crypto_last_prices(
    *,
    api_key: str,
    api_secret: str,
    pairs: list[str],
) -> tuple[dict[str, float], dict[str, str]]:
    """
    Fetch latest-ish crypto prices (best effort).
    Primary: latest trade API (if available in installed alpaca-py).
    Fallback: last minute bar close.
    """
    # Lazy import: keep module importable without alpaca installed.
    from alpaca.data.historical import CryptoHistoricalDataClient
    from alpaca.data.timeframe import TimeFrame

    client = CryptoHistoricalDataClient(api_key, api_secret)
    out: dict[str, float] = {}
    out_asof: dict[str, str] = {}

    # Attempt latest trade request first (SDK-dependent)
    try:
        from alpaca.data.requests import CryptoLatestTradeRequest

        syms = [p.upper() for p in pairs]
        # SDK compatibility: some versions accept request object; others accept keyword args.
        try:
            req = CryptoLatestTradeRequest(symbol_or_symbols=syms)
            latest = client.get_crypto_latest_trade(req)
        except TypeError:
            latest = client.get_crypto_latest_trade(symbol_or_symbols=syms)
        # alpaca-py typically returns mapping: symbol -> trade
        if isinstance(latest, dict):
            for sym, trade in latest.items():
                px = getattr(trade, "price", None)
                ts = getattr(trade, "timestamp", None) or getattr(trade, "t", None)
                fpx = _to_f(px)
                if fpx is not None:
                    out[str(sym).upper()] = fpx
                    if ts is not None:
                        out_asof[str(sym).upper()] = str(ts)
    except Exception:
        pass

    missing = [p for p in pairs if p.upper() not in out]
    if not missing:
        return out, out_asof

    try:
        from alpaca.data.requests import CryptoBarsRequest

        # Pull 1m bars for the last ~10 minutes and take the last close.
        start = pd.Timestamp(datetime.now(timezone.utc) - timedelta(minutes=10))
        req = CryptoBarsRequest(symbol_or_symbols=[p.upper() for p in missing], timeframe=TimeFrame.Minute, start=start)
        bars = client.get_crypto_bars(req).df
        if bars is not None and len(bars) > 0:
            b = bars.reset_index()
            # columns: symbol, timestamp, close, ...
            for sym in missing:
                df_sym = b[b["symbol"].astype(str).str.upper() == sym.upper()]
                if df_sym.empty:
                    continue
                last_close = df_sym.sort_values("timestamp").iloc[-1].get("close")
                last_ts = df_sym.sort_values("timestamp").iloc[-1].get("timestamp")
                fpx = _to_f(last_close)
                if fpx is not None:
                    out[sym.upper()] = fpx
                    if last_ts is not None:
                        out_asof[sym.upper()] = str(last_ts)
    except Exception:
        pass

    return out, out_asof


def _fetch_upcoming_events(*, settings, hours: int) -> list[dict]:
    """
    Best-effort: fetch US/USD calendar events and keep those within next `hours`.
    """
    try:
        from ai_options_trader.overlay.context import fetch_calendar_events

        now = datetime.now(timezone.utc)
        days = max(1, int((hours / 24.0) + 1))
        events = fetch_calendar_events(settings=settings, days_ahead=days, max_items=50)
        out = []
        for e in events:
            ts_s = str(e.get("date") or e.get("ts") or "")
            try:
                ts = datetime.fromisoformat(ts_s.replace("Z", "+00:00"))
            except Exception:
                continue
            if now <= ts <= now + timedelta(hours=hours):
                out.append(e)
        return out
    except Exception:
        return []


def register(live_app: typer.Typer) -> None:
    @live_app.command("console")
    def live_console(
        pairs: str = typer.Option("BTC/USD,ETH/USD,DOGE/USD", "--pairs", help="Comma-separated crypto pairs, e.g. BTC/USD,ETH/USD"),
        poll_seconds: int = typer.Option(30, "--poll-seconds", help="Polling interval in seconds"),
        move_alert_pct: float = typer.Option(0.1, "--move-alert-pct", help="Alert when |price move| >= this percent since last poll"),
        open_cash_pct: float = typer.Option(0.60, "--open-cash-pct", help="Fraction of available USD cash to deploy on buy commands (0..1)"),
        position_alert_pct: float = typer.Option(5.0, "--position-alert-pct", help="Alert when |uPL% change| >= this since last poll"),
        position_alert_usd: float = typer.Option(75.0, "--position-alert-usd", help="Alert when |uPL$ change| >= this since last poll"),
        events_hours: int = typer.Option(6, "--events-hours", help="Lookahead window for upcoming events"),
        regimes_start: str = typer.Option("2012-01-01", "--regimes-start", help="Start date for regime feature matrix build"),
        refresh_regimes: bool = typer.Option(False, "--refresh-regimes", help="Force refresh FRED downloads (regimes)"),
        with_regimes: bool = typer.Option(True, "--with-regimes/--no-regimes", help="Build/refresh regimes (hourly cadence inside console)"),
        stream: bool = typer.Option(True, "--stream/--no-stream", help="Use Alpaca websocket crypto stream for live prices (fallback to REST)"),
        debug_stream: bool = typer.Option(False, "--debug-stream", help="Print websocket diagnostics (msg count, last recv age)"),
        log_dir: str = typer.Option("data/live", "--log-dir", help="Directory for JSONL logs"),
        execute: bool = typer.Option(True, "--execute/--no-execute", help="If disabled, prints order previews but does not submit"),
    ):
        """
        Interactive live console:
        - Streams crypto prices (30s polling by default) + alerts
        - Lets you type commands like: buy ETH | sell ETH | close ETH | alert 3 | status | positions | quit
        - Executes ONLY when you type a buy/sell/close command (never automatic)
        - Logs every tick + action to JSONL
        """
        settings = load_settings()
        console = Console()

        pairs_list = [p.strip().upper() for p in pairs.split(",") if p.strip()]
        if not pairs_list:
            raise typer.BadParameter("No pairs provided.")

        if not (0.0 < float(open_cash_pct) <= 1.0):
            raise typer.BadParameter("--open-cash-pct must be in (0, 1].")
        if int(poll_seconds) <= 0:
            raise typer.BadParameter("--poll-seconds must be > 0.")

        trading, _opt_data = make_clients(settings)

        # Logging
        log_base = Path(log_dir)
        ticks_path = log_base / "ticks.jsonl"
        actions_path = log_base / "actions.jsonl"

        state: dict[str, object] = {
            "last_prices": {},  # pair -> float
            "last_positions": {},  # symbol -> {upl, uplpc}
            "last_regime_ts": None,
        }

        # Banner
        console.print(
            Panel(
                f"mode={'LIVE' if not bool(settings.alpaca_paper) else 'PAPER'} execute={bool(execute)}\n"
                f"pairs={','.join(pairs_list)} poll={int(poll_seconds)}s move_alert={float(move_alert_pct):.2f}% open_cash_pct={float(open_cash_pct):.2f}\n"
                f"price_source={'stream' if bool(stream) else 'rest'}\n"
                f"Type: buy ETH | sell ETH | close ETH | alert 3 | status | positions | help | quit",
                title="Lox Live Console (crypto)",
                expand=False,
            )
        )

        # Optional websocket stream cache (pair -> price / asof)
        ws_lock = threading.Lock()
        ws_prices: dict[str, float] = {}
        ws_asof: dict[str, str] = {}
        ws_meta: dict[str, float] = {"msg_count": 0.0, "last_recv_unix": 0.0}
        ws_stream = None
        stream_warned_silent = False
        if stream:
            data_key = settings.alpaca_data_key or settings.alpaca_api_key
            data_secret = settings.alpaca_data_secret or settings.alpaca_api_secret
            ws_stream, _t = _start_crypto_price_stream(
                api_key=data_key,
                api_secret=data_secret,
                pairs=pairs_list,
                shared_prices=ws_prices,
                shared_asof=ws_asof,
                lock=ws_lock,
                console=console,
                meta=ws_meta,
            )
            if ws_stream is None:
                console.print(Panel("[yellow]Websocket stream unavailable; using REST latest prices.[/yellow]", title="Live stream", expand=False))

        # Helper: print + log action
        def log_action(kind: str, payload: dict) -> None:
            _jsonl_append(
                actions_path,
                {
                    "ts": _utc_now_iso(),
                    "kind": kind,
                    **payload,
                },
            )

        def get_account_cash() -> float:
            acct = trading.get_account()
            cash = _to_f(getattr(acct, "cash", None)) or 0.0
            return float(cash)

        def get_positions() -> list[dict]:
            out = []
            for p in trading.get_all_positions():
                sym = str(getattr(p, "symbol", "") or "").upper()
                qty = _to_f(getattr(p, "qty", None))
                avg_entry = _to_f(getattr(p, "avg_entry_price", None))
                current = _to_f(getattr(p, "current_price", None))
                upl = _to_f(getattr(p, "unrealized_pl", None))
                uplpc = _to_f(getattr(p, "unrealized_plpc", None))
                out.append(
                    {
                        "symbol": sym,
                        "qty": qty,
                        "avg_entry_price": avg_entry,
                        "current_price": current,
                        "unrealized_pl": upl,
                        "unrealized_plpc": uplpc,
                    }
                )
            return out

        def print_positions() -> None:
            pos = get_positions()
            if not pos:
                console.print(Panel("No open positions.", title="Positions", expand=False))
                return
            lines = []
            for p in sorted(pos, key=lambda x: str(x.get("symbol") or "")):
                lines.append(
                    f"{p.get('symbol')} qty={p.get('qty')} current={_format_usd(p.get('current_price'))} "
                    f"uPL={_format_usd(p.get('unrealized_pl'))} uPL%={_format_pct((p.get('unrealized_plpc') or 0.0) * 100.0 if isinstance(p.get('unrealized_plpc'), (int, float)) else None)}"
                )
            console.print(Panel("\n".join(lines), title="Positions", expand=False))

        def do_buy(pair: str) -> None:
            cash = get_account_cash()
            notional = float(cash) * float(open_cash_pct)
            notional = max(0.0, notional)
            notional = round(float(notional), 2)
            if notional <= 1.0:
                console.print(Panel(f"Cash=${cash:.2f} -> notional=${notional:.2f} is too small.", title="Buy", expand=False))
                log_action("buy_skipped", {"pair": pair, "cash": cash, "notional": notional, "reason": "too_small"})
                return

            trade_symbol = _pair_to_trade_symbol(pair)
            preview = CryptoOrderPreview(symbol=trade_symbol, side="buy", order_type="market", notional=notional, qty=None, tif="day")
            console.print(Panel(f"BUY {pair} notional={_format_usd(notional)} (60% of cash={_format_usd(cash)})", title="ORDER", expand=False))
            log_action("order_preview", {"preview": asdict(preview), "pair": pair})

            if not execute:
                console.print(Panel("Execution disabled (--no-execute).", title="ORDER", expand=False))
                return

            try:
                res = submit_crypto_order(trading=trading, symbol=trade_symbol, side="buy", notional=notional, qty=None, tif="day")
                oid = getattr(res, "id", None)
                status = getattr(res, "status", None)
                console.print(Panel(f"submitted id={oid} status={status}", title="ORDER", expand=False))
                log_action("order_submitted", {"preview": asdict(preview), "pair": pair, "id": str(oid), "status": str(status)})
            except Exception as e:
                console.print(Panel(f"[red]Order failed[/red]\n\n{e}", title="ORDER", expand=False))
                log_action("order_failed", {"preview": asdict(preview), "pair": pair, "error": str(e)})

        def do_close(pair: str) -> None:
            # Close = sell full qty of the position (market), at whatever price it fills.
            trade_symbol = _pair_to_trade_symbol(pair)
            positions = get_positions()
            pos = None
            for p in positions:
                if str(p.get("symbol") or "").upper() == trade_symbol:
                    pos = p
                    break
            if not pos or not isinstance(pos.get("qty"), (int, float)) or float(pos.get("qty") or 0.0) <= 0.0:
                console.print(Panel(f"No open position found for {pair} ({trade_symbol}).", title="Close", expand=False))
                log_action("close_skipped", {"pair": pair, "symbol": trade_symbol, "reason": "no_position"})
                return

            qty = float(pos["qty"])
            preview = CryptoOrderPreview(symbol=trade_symbol, side="sell", order_type="market", notional=None, qty=qty, tif="day")
            console.print(Panel(f"CLOSE {pair} qty={qty}", title="ORDER", expand=False))
            log_action("order_preview", {"preview": asdict(preview), "pair": pair})

            if not execute:
                console.print(Panel("Execution disabled (--no-execute).", title="ORDER", expand=False))
                return

            try:
                res = submit_crypto_order(trading=trading, symbol=trade_symbol, side="sell", notional=None, qty=qty, tif="day")
                oid = getattr(res, "id", None)
                status = getattr(res, "status", None)
                console.print(Panel(f"submitted id={oid} status={status}", title="ORDER", expand=False))
                log_action("order_submitted", {"preview": asdict(preview), "pair": pair, "id": str(oid), "status": str(status)})
            except Exception as e:
                console.print(Panel(f"[red]Order failed[/red]\n\n{e}", title="ORDER", expand=False))
                log_action("order_failed", {"preview": asdict(preview), "pair": pair, "error": str(e)})

        def print_status(*, last_prices: dict[str, float]) -> None:
            try:
                cash = get_account_cash()
            except Exception:
                cash = None
            body = (
                f"cash={_format_usd(cash)} open_cash_pct={float(open_cash_pct):.2f}\n"
                f"move_alert_pct={float(move_alert_pct):.2f}% position_alert_pct={float(position_alert_pct):.2f}% position_alert_usd={_format_usd(float(position_alert_usd))}\n"
                f"pairs={','.join(pairs_list)} poll={int(poll_seconds)}s\n"
            )
            if last_prices:
                body += "last_prices:\n" + "\n".join([f"- {k}: {v:.6f}" for k, v in last_prices.items()])
            console.print(Panel(body, title="Status", expand=False))

        # Main loop
        last_tick = 0.0
        last_regime_build = 0.0

        while True:
            now = time.time()

            # Process any pending user input first (so trading is responsive)
            line = _read_line_nonblocking()
            if line:
                cmd = line.strip()
                if not cmd:
                    pass
                else:
                    parts = cmd.split()
                    verb = parts[0].strip().lower()
                    arg = parts[1].strip() if len(parts) > 1 else ""

                    if verb in {"q", "quit", "exit"}:
                        log_action("quit", {"cmd": cmd})
                        try:
                            if ws_stream is not None and hasattr(ws_stream, "stop"):
                                ws_stream.stop()
                        except Exception:
                            pass
                        console.print(Panel("bye", title="Live console", expand=False))
                        return
                    if verb == "help":
                        console.print(
                            Panel(
                                "Commands:\n"
                                "- buy ETH | buy BTC | buy DOGE\n"
                                "- sell ETH | close ETH\n"
                                "- short ETH (not supported yet)\n"
                                "- alert 0.1  (set move alert threshold)\n"
                                "- status | positions | quit",
                                title="Help",
                                expand=False,
                            )
                        )
                        log_action("help", {"cmd": cmd})
                    elif verb == "alert":
                        try:
                            v = float(arg)
                            move_alert_pct = float(v)
                            console.print(Panel(f"move_alert_pct set to {move_alert_pct:.2f}%", title="Alerts", expand=False))
                            log_action("set_alert", {"cmd": cmd, "move_alert_pct": move_alert_pct})
                        except Exception:
                            console.print(Panel("Usage: alert 0.1   (percent)", title="Alerts", expand=False))
                            log_action("set_alert_failed", {"cmd": cmd})
                    elif verb in {"status"}:
                        lp = state.get("last_prices") if isinstance(state.get("last_prices"), dict) else {}
                        print_status(last_prices=lp)  # type: ignore[arg-type]
                        log_action("status", {"cmd": cmd})
                    elif verb in {"positions", "pos"}:
                        print_positions()
                        log_action("positions", {"cmd": cmd})
                    elif verb in {"short"}:
                        console.print(Panel("Short crypto is not supported yet (perps later).", title="Trade", expand=False))
                        log_action("short_not_supported", {"cmd": cmd})
                    elif verb in {"buy"}:
                        pair = _resolve_pair(arg, pairs_list)
                        if not pair:
                            console.print(Panel(f"Unknown coin/pair: {arg}", title="Trade", expand=False))
                            log_action("buy_failed", {"cmd": cmd, "reason": "unknown_pair"})
                        else:
                            do_buy(pair)
                    elif verb in {"sell", "close"}:
                        pair = _resolve_pair(arg, pairs_list)
                        if not pair:
                            console.print(Panel(f"Unknown coin/pair: {arg}", title="Trade", expand=False))
                            log_action("close_failed", {"cmd": cmd, "reason": "unknown_pair"})
                        else:
                            do_close(pair)
                    else:
                        console.print(Panel(f"Unknown command: {cmd}\nTry: help", title="Live console", expand=False))
                        log_action("unknown_cmd", {"cmd": cmd})

            # Tick
            if now - last_tick >= float(poll_seconds):
                last_tick = now

                # Prices
                data_key = settings.alpaca_data_key or settings.alpaca_api_key
                data_secret = settings.alpaca_data_secret or settings.alpaca_api_secret
                prices: dict[str, float] = {}
                prices_asof: dict[str, str] = {}
                if ws_stream is not None:
                    with ws_lock:
                        prices = {k.upper(): float(v) for k, v in ws_prices.items()}
                        prices_asof = {k.upper(): str(v) for k, v in ws_asof.items()}
                if not prices:
                    prices, prices_asof = _fetch_crypto_last_prices(api_key=data_key, api_secret=data_secret, pairs=pairs_list)
                    if ws_stream is not None and not stream_warned_silent:
                        # If the stream is enabled but hasn't produced any messages, alert once.
                        if float(ws_meta.get("msg_count", 0.0)) <= 0.0:
                            console.print(
                                Panel(
                                    "[yellow]Crypto websocket stream is running but has not produced any trade updates yet.[/yellow]\n"
                                    "Falling back to REST for prices. This usually means data permissions/keys/feed mismatch.\n"
                                    "Run with: --debug-stream to see message counts.",
                                    title="Live stream",
                                    expand=False,
                                )
                            )
                            stream_warned_silent = True

                last_prices = state.get("last_prices") if isinstance(state.get("last_prices"), dict) else {}
                deltas: dict[str, float] = {}
                for p in pairs_list:
                    px = prices.get(p.upper())
                    prev = _to_f(last_prices.get(p.upper()) if isinstance(last_prices, dict) else None)
                    if px is not None and prev is not None and prev != 0:
                        deltas[p.upper()] = (float(px) / float(prev) - 1.0) * 100.0
                state["last_prices"] = {**(last_prices or {}), **{k: float(v) for k, v in prices.items() if v is not None}}  # type: ignore[arg-type]

                # Positions (for P&L move detection)
                positions = []
                pos_delta_alerts = []
                try:
                    positions = get_positions()
                    last_pos = state.get("last_positions") if isinstance(state.get("last_positions"), dict) else {}
                    cur_pos_map = {}
                    for p in positions:
                        sym = str(p.get("symbol") or "").upper()
                        upl = _to_f(p.get("unrealized_pl"))
                        uplpc = _to_f(p.get("unrealized_plpc"))
                        cur_pos_map[sym] = {"upl": upl, "uplpc": uplpc}
                        prevp = last_pos.get(sym) if isinstance(last_pos, dict) else None
                        if isinstance(prevp, dict):
                            prev_upl = _to_f(prevp.get("upl"))
                            prev_uplpc = _to_f(prevp.get("uplpc"))
                            dupl = (upl - prev_upl) if (upl is not None and prev_upl is not None) else None
                            duplpc = ((uplpc - prev_uplpc) * 100.0) if (uplpc is not None and prev_uplpc is not None) else None
                            if dupl is not None and abs(float(dupl)) >= float(position_alert_usd):
                                pos_delta_alerts.append((sym, duplpc, dupl))
                            elif duplpc is not None and abs(float(duplpc)) >= float(position_alert_pct):
                                pos_delta_alerts.append((sym, duplpc, dupl))
                    state["last_positions"] = cur_pos_map
                except Exception:
                    positions = []

                # Events (next N hours)
                events = _fetch_upcoming_events(settings=settings, hours=int(events_hours))

                # Regimes (hourly cadence)
                regime_row = None
                if with_regimes and (now - last_regime_build >= 3600):
                    last_regime_build = now
                    try:
                        X = build_regime_feature_matrix(settings=settings, start_date=str(regimes_start), refresh_fred=bool(refresh_regimes))
                        if not X.empty:
                            last_dt = X.index.max()
                            row = X.loc[last_dt].to_dict()
                            regime_row = {"asof": str(last_dt), "features": row}
                            state["last_regime_ts"] = str(last_dt)
                    except Exception:
                        regime_row = None

                # Print tick line
                tick_ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
                parts = []
                for p in pairs_list:
                    px = prices.get(p.upper())
                    dp = deltas.get(p.upper())
                    if px is None:
                        parts.append(f"{p} —")
                    else:
                        # Show whether the feed is stale (best-effort).
                        asof_s = prices_asof.get(p.upper(), "")
                        stale_tag = ""
                        try:
                            if asof_s:
                                dt = datetime.fromisoformat(asof_s.replace("Z", "+00:00"))
                                age_s = (datetime.now(timezone.utc) - dt).total_seconds()
                                if age_s > 120:
                                    stale_tag = f" STALE({int(age_s)}s)"
                        except Exception:
                            stale_tag = ""
                        parts.append(f"{p} {float(px):.6f} ({_format_pct(dp)}){stale_tag}")
                src_tag = "stream" if (ws_stream is not None and float(ws_meta.get("msg_count", 0.0)) > 0.0) else "rest"
                console.print(f"[{tick_ts}] " + " | ".join(parts) + f"  [src={src_tag}]")

                if debug_stream and ws_stream is not None:
                    age_s = None
                    try:
                        last_recv = float(ws_meta.get("last_recv_unix", 0.0))
                        if last_recv > 0:
                            age_s = float(time.time()) - last_recv
                    except Exception:
                        age_s = None
                    console.print(
                        Panel(
                            f"msg_count={int(ws_meta.get('msg_count', 0.0))}\n"
                            f"last_recv_age_s={int(age_s) if isinstance(age_s, (int, float)) else '—'}\n"
                            f"prices_cached={len(ws_prices)}",
                            title="Stream diagnostics",
                            expand=False,
                        )
                    )

                # Alerts: crypto move
                move_alerts = []
                for p, dp in deltas.items():
                    if abs(float(dp)) >= float(move_alert_pct):
                        move_alerts.append({"pair": p, "move_pct": float(dp), "threshold_pct": float(move_alert_pct)})
                        console.print(
                            Panel(
                                f"{p} moved {_format_pct(float(dp))} in last {int(poll_seconds)}s (threshold={float(move_alert_pct):.2f}%).\n"
                                f"Commands: buy {_coin_from_pair(p)} | sell {_coin_from_pair(p)} | close {_coin_from_pair(p)}",
                                title="ALERT: crypto move",
                                expand=False,
                            )
                        )

                # Alerts: position P&L move
                for sym, duplpc, dupl in pos_delta_alerts:
                    console.print(
                        Panel(
                            f"{sym} moved since last tick: ΔuPL={_format_usd(dupl)} ΔuPL%={_format_pct(duplpc)}\n"
                            f"Request: consider close {sym}",
                            title="ALERT: position move",
                            expand=False,
                        )
                    )

                # Alerts: events in next window
                if events:
                    # Keep it short; print top few.
                    lines = []
                    for e in events[:6]:
                        lines.append(f"- {e.get('date') or e.get('ts')}: {e.get('event') or e.get('name') or e.get('title')}")
                    console.print(Panel("\n".join(lines), title=f"Upcoming events (next {int(events_hours)}h)", expand=False))

                # Log tick
                tick_obj = {
                    "ts": _utc_now_iso(),
                    "pairs": pairs_list,
                    "prices": {k: prices.get(k.upper()) for k in pairs_list},
                    "prices_asof": {k: prices_asof.get(k.upper()) for k in pairs_list},
                    "price_source": "stream" if (ws_stream is not None and float(ws_meta.get("msg_count", 0.0)) > 0.0) else "rest",
                    "stream_msg_count": int(ws_meta.get("msg_count", 0.0)) if ws_stream is not None else 0,
                    "deltas_pct": deltas,
                    "move_alert_pct": float(move_alert_pct),
                    "position_alert_pct": float(position_alert_pct),
                    "position_alert_usd": float(position_alert_usd),
                    "move_alerts": move_alerts,
                    "position_alerts": [{"symbol": s, "duplpc": duplpc, "dupl": dupl} for (s, duplpc, dupl) in pos_delta_alerts],
                    "events_hours": int(events_hours),
                    "events": events[:20],
                    "regime": regime_row,
                }
                _jsonl_append(ticks_path, tick_obj)

            # Small sleep so we don't busy-loop.
            time.sleep(0.05)

