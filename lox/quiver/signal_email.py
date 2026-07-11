"""
HTML email builder and Gmail SMTP sender for the LOX quiver signal digest.

Requires in .env:
  GMAIL_USER         = jeffreyblarson00@gmail.com
  GMAIL_APP_PASSWORD = xxxx xxxx xxxx xxxx

Generate an App Password at:
  https://myaccount.google.com/apppasswords
  (Google Account → Security → 2-Step Verification → App passwords)
"""
from __future__ import annotations

import os
import smtplib
from datetime import date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from lox.quiver.signal import QuiverSignal


def _fmt_usd(v: float) -> str:
    if v >= 1_000_000:
        return f"${v/1e6:.1f}M"
    if v >= 1_000:
        return f"${v/1e3:.0f}K"
    return f"${v:.0f}"


def _alpha_color(alpha: Optional[float], side: str) -> str:
    if alpha is None:
        return "#888888"
    if side == "Buy":
        return "#27ae60" if alpha <= 2 else "#e67e22"
    else:
        return "#27ae60" if alpha >= -2 else "#e67e22"


def _score_dots(score: float) -> str:
    filled = round(score * 5)
    return "●" * filled + "○" * (5 - filled)


def build_email_html(signals: list[QuiverSignal], asof: date) -> str:
    rows = []
    for s in signals:
        alpha_str = f"{s.alpha_vs_spy:+.1f}%" if s.alpha_vs_spy is not None else "—"
        alpha_col = _alpha_color(s.alpha_vs_spy, s.side)
        side_col = "#27ae60" if s.side == "Buy" else "#e74c3c"
        officials_str = ", ".join(s.officials[:3]) + ("…" if len(s.officials) > 3 else "")
        source_label = " + ".join(s.sources).upper()

        rows.append(f"""
<tr>
  <td style="padding:12px 14px;border-bottom:1px solid #2d2d2d;vertical-align:top;">
    <div style="font-size:20px;font-weight:700;color:#ffffff;letter-spacing:.5px">{s.ticker}</div>
    <div style="font-size:11px;color:#777;margin-top:2px">{s.company[:32]}</div>
  </td>
  <td style="padding:12px 14px;border-bottom:1px solid #2d2d2d;text-align:center;vertical-align:top;">
    <span style="color:{side_col};font-weight:700;font-size:13px">{s.side.upper()}</span>
  </td>
  <td style="padding:12px 14px;border-bottom:1px solid #2d2d2d;vertical-align:top;font-size:12px;color:#cccccc;">
    {officials_str}<br>
    <span style="color:#555;font-size:10px">{source_label} · {s.cluster_count} official{'s' if s.cluster_count > 1 else ''}</span>
  </td>
  <td style="padding:12px 14px;border-bottom:1px solid #2d2d2d;text-align:center;vertical-align:top;">
    <div style="color:#aaa;font-size:13px">{s.avg_lag_days:.0f}d</div>
    <div style="color:#555;font-size:10px">lag</div>
  </td>
  <td style="padding:12px 14px;border-bottom:1px solid #2d2d2d;text-align:center;vertical-align:top;">
    <div style="color:{alpha_col};font-weight:700;font-size:14px">{alpha_str}</div>
    <div style="color:#555;font-size:10px">α vs SPY</div>
  </td>
  <td style="padding:12px 14px;border-bottom:1px solid #2d2d2d;vertical-align:top;max-width:280px">
    <div style="color:#3498db;font-size:12px;font-weight:600">{s.suggested_action}</div>
    <div style="color:#666;font-size:11px;margin-top:3px">{s.rationale}</div>
  </td>
  <td style="padding:12px 14px;border-bottom:1px solid #2d2d2d;text-align:center;vertical-align:top;">
    <div style="color:#f39c12;font-size:12px;letter-spacing:1px">{_score_dots(s.score)}</div>
    <div style="color:#555;font-size:10px">{s.score:.2f}</div>
  </td>
</tr>""")

    rows_html = "\n".join(rows)
    n = len(signals)

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#0f0f0f;font-family:'Helvetica Neue',Arial,sans-serif;">
<div style="max-width:960px;margin:0 auto;padding:28px 20px;">

  <div style="border-left:4px solid #3498db;padding-left:16px;margin-bottom:20px;">
    <div style="font-size:24px;font-weight:700;color:#ffffff">LOX Signal Digest</div>
    <div style="font-size:13px;color:#666;margin-top:4px">Congress + Trump trades &nbsp;·&nbsp; {asof.isoformat()} &nbsp;·&nbsp; {n} signal{'s' if n != 1 else ''}</div>
  </div>

  <p style="font-size:13px;color:#888;margin:0 0 20px;line-height:1.6">
    Each signal below is a ticker where a government official has disclosed a trade,
    but the stock has <em>not yet moved</em> in the direction of their bet.
    <strong style="color:#f39c12">α vs SPY</strong> is the stock's excess return
    since the trade date — negative on a Buy means the opportunity is still open.
  </p>

  <table style="width:100%;border-collapse:collapse;background:#1a1a1a;border-radius:8px;overflow:hidden;">
    <thead>
      <tr style="background:#222;">
        <th style="padding:10px 14px;text-align:left;color:#555;font-size:10px;text-transform:uppercase;letter-spacing:.8px">Ticker</th>
        <th style="padding:10px 14px;text-align:center;color:#555;font-size:10px;text-transform:uppercase;letter-spacing:.8px">Side</th>
        <th style="padding:10px 14px;text-align:left;color:#555;font-size:10px;text-transform:uppercase;letter-spacing:.8px">Officials</th>
        <th style="padding:10px 14px;text-align:center;color:#555;font-size:10px;text-transform:uppercase;letter-spacing:.8px">Lag</th>
        <th style="padding:10px 14px;text-align:center;color:#555;font-size:10px;text-transform:uppercase;letter-spacing:.8px">α vs SPY</th>
        <th style="padding:10px 14px;text-align:left;color:#555;font-size:10px;text-transform:uppercase;letter-spacing:.8px">Options Play</th>
        <th style="padding:10px 14px;text-align:center;color:#555;font-size:10px;text-transform:uppercase;letter-spacing:.8px">Signal</th>
      </tr>
    </thead>
    <tbody>
{rows_html}
    </tbody>
  </table>

  <p style="font-size:10px;color:#444;margin-top:20px;text-align:center">
    Generated by LOX Capital &nbsp;·&nbsp; Source: Quiver Quantitative &nbsp;·&nbsp; Not investment advice
  </p>
</div>
</body>
</html>"""


def send_signal_email(
    signals: list[QuiverSignal],
    to_email: str,
    asof: date,
) -> None:
    """Send the signal digest via Gmail SMTP. Raises RuntimeError on config failure."""
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    gmail_user = os.environ.get("GMAIL_USER")
    gmail_password = os.environ.get("GMAIL_APP_PASSWORD")

    if not gmail_user or not gmail_password:
        raise RuntimeError(
            "GMAIL_USER and GMAIL_APP_PASSWORD must be set in .env\n"
            "  GMAIL_USER=jeffreyblarson00@gmail.com\n"
            "  GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx\n"
            "Generate at: https://myaccount.google.com/apppasswords"
        )

    n = len(signals)
    subject = f"LOX Signal | {asof.isoformat()} | {n} signal{'s' if n != 1 else ''}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = gmail_user
    msg["To"] = to_email

    msg.attach(MIMEText(build_email_html(signals, asof), "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(gmail_user, gmail_password)
        smtp.sendmail(gmail_user, to_email, msg.as_string())
