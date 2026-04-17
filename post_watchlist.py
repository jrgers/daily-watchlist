"""
Post the daily options watchlist via email (SendGrid) and Discord webhook.

Reads watchlist.json from the repo root (written by the Claude agent).

Environment variables required:
    SENDGRID_API_KEY     — SendGrid API key
    DISCORD_WEBHOOK_URL  — Discord incoming webhook URL
    EMAIL_FROM           — Sender address (default: johnnygerges@gmail.com)
    EMAIL_TO             — Recipient address (default: johnnygerges@gmail.com)
    EMAIL_FROM_NAME      — Sender display name (default: Johny Gerges)
"""

import json
import os
import sys
import urllib.request
import urllib.error

SENDGRID_API_URL = "https://api.sendgrid.com/v3/mail/send"
INPUT_FILE = "watchlist.json"

DIRECTION_COLOR = {"BULLISH": "#28a745", "BEARISH": "#dc3545"}
CONFIDENCE_BADGE = {"High": "#1a1a2e", "Medium": "#6c757d"}
CATEGORY_BADGE = {"Day Trade": "#fd7e14", "Swing": "#0d6efd"}
DISCORD_COLOR = {"BULLISH": 0x28A745, "BEARISH": 0xDC3545}


def get_env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if value is None:
        print(f"ERROR: environment variable '{name}' is not set.", file=sys.stderr)
        sys.exit(1)
    return value


def esc(text) -> str:
    return (str(text)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))


# ── HTML email ────────────────────────────────────────────────────────────────

def badge(text: str, color: str) -> str:
    return (
        f"<span style='background:{color};color:#fff;padding:2px 8px;"
        f"border-radius:3px;font-size:11px;font-weight:600'>{esc(text)}</span>"
    )


def build_trade_card_html(trade: dict, index: int) -> str:
    direction = trade.get("direction", "")
    dir_color = DIRECTION_COLOR.get(direction, "#6c757d")
    category = trade.get("trade_category", "")
    cat_color = CATEGORY_BADGE.get(category, "#6c757d")
    conf = trade.get("confidence", "")
    conf_color = CONFIDENCE_BADGE.get(conf, "#6c757d")
    t = trade.get("trade", {})

    if_rows = "".join(
        f"<li style='padding:3px 0;color:#333;font-size:13px'>{esc(c)}</li>"
        for c in trade.get("if_conditions", [])
    )

    return f"""
    <div style='border:1px solid #e9ecef;border-radius:6px;margin-bottom:20px;overflow:hidden'>
      <div style='background:{dir_color};padding:10px 16px;display:flex;align-items:center;gap:8px'>
        <span style='color:#fff;font-size:15px;font-weight:700'>
          [{index}] {esc(trade.get('symbol',''))} &mdash; {esc(direction)}
        </span>
        {badge(category, cat_color)}
        {badge(trade.get('type',''), '#6c757d')}
        {badge(f"Confidence: {conf}", conf_color)}
      </div>
      <div style='padding:14px 16px'>
        <p style='margin:0 0 10px;font-size:13px;color:#555;font-style:italic'>{esc(trade.get('context',''))}</p>
        <div style='margin-bottom:12px'>
          <div style='font-size:12px;font-weight:700;color:#1a1a2e;margin-bottom:4px;text-transform:uppercase;letter-spacing:.5px'>IF conditions</div>
          <ul style='margin:0;padding-left:18px'>{if_rows}</ul>
        </div>
        <div style='background:#f8f9fa;border-radius:4px;padding:10px 12px;margin-bottom:10px'>
          <div style='font-size:12px;font-weight:700;color:#1a1a2e;margin-bottom:6px;text-transform:uppercase;letter-spacing:.5px'>THEN trade</div>
          <table style='font-size:13px;color:#333;width:100%'>
            <tr><td style='padding:2px 8px 2px 0;color:#888;width:90px'>Structure</td><td>{esc(t.get('structure',''))}</td></tr>
            <tr><td style='padding:2px 8px 2px 0;color:#888'>Strike / Exp</td><td>{esc(t.get('strike',''))} &mdash; {esc(t.get('expiry',''))} ({esc(t.get('dte',''))} DTE)</td></tr>
            <tr><td style='padding:2px 8px 2px 0;color:#888'>Entry range</td><td>{esc(t.get('entry_range',''))}</td></tr>
            <tr><td style='padding:2px 8px 2px 0;color:#888'>Target</td><td style='color:#28a745;font-weight:600'>{esc(t.get('target',''))}</td></tr>
            <tr><td style='padding:2px 8px 2px 0;color:#888'>Stop</td><td style='color:#dc3545;font-weight:600'>{esc(t.get('stop',''))}</td></tr>
          </table>
        </div>
        <div style='font-size:12px;color:#888'>
          <strong style='color:#333'>Invalidation:</strong> {esc(trade.get('invalidation',''))}
        </div>
      </div>
    </div>"""


def build_html(watchlist: dict) -> str:
    date = watchlist.get("date", "")
    gen_at = watchlist.get("generated_at_et", "")
    market_ctx = watchlist.get("market_context", "")
    trades = watchlist.get("trades", [])
    skipped = watchlist.get("skipped", [])
    no_trades = watchlist.get("no_trades", False)

    trade_cards = "".join(build_trade_card_html(t, i + 1) for i, t in enumerate(trades))

    skipped_html = ""
    if skipped:
        items = "".join(f"<li style='padding:2px 0;font-size:12px;color:#888'>{esc(s)}</li>" for s in skipped)
        skipped_html = f"<div style='margin-top:16px'><div style='font-size:11px;font-weight:700;color:#aaa;text-transform:uppercase;letter-spacing:.5px;margin-bottom:4px'>Skipped / Filtered</div><ul style='margin:0;padding-left:18px'>{items}</ul></div>"

    no_trade_banner = ""
    if no_trades:
        no_trade_banner = "<div style='background:#fff3cd;border:1px solid #ffc107;border-radius:4px;padding:12px 16px;color:#856404;font-size:13px;margin-bottom:16px'><strong>No trades today.</strong> Quality bar not met — stand aside.</div>"

    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'></head>"
        "<body style='margin:0;padding:0;background:#f4f6f9;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif'>"
        "<div style='max-width:720px;margin:24px auto;background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.08)'>"
        f"<div style='background:#1a1a2e;padding:18px 24px;color:#fff'>"
        f"<h1 style='margin:0;font-size:18px;font-weight:700'>Daily Options Watchlist &mdash; {esc(date)}</h1>"
        f"<div style='margin-top:6px;font-size:12px;color:#adb5bd'>Generated {esc(gen_at)} &nbsp;|&nbsp; {len(trades)} trade(s) today</div>"
        "</div>"
        f"<div style='padding:20px 24px'>"
        f"<div style='background:#eef2ff;border-left:4px solid #4f46e5;padding:10px 14px;border-radius:0 4px 4px 0;margin-bottom:20px;font-size:13px;color:#333'>"
        f"<strong>Market:</strong> {esc(market_ctx)}</div>"
        f"{no_trade_banner}{trade_cards}{skipped_html}"
        "</div>"
        f"<div style='background:#f8f9fa;padding:10px 24px;font-size:11px;color:#aaa;border-top:1px solid #e9ecef'>"
        f"Advisory only &mdash; does not execute trades &nbsp;|&nbsp; Portfolio Analysis Watchlist"
        "</div></div></body></html>"
    )


def send_email(watchlist: dict) -> None:
    api_key = get_env("SENDGRID_API_KEY")
    from_email = get_env("EMAIL_FROM", "johnnygerges@gmail.com")
    from_name = get_env("EMAIL_FROM_NAME", "Johny Gerges")
    to_email = get_env("EMAIL_TO", "johnnygerges@gmail.com")

    date = watchlist.get("date", "")
    trade_count = len(watchlist.get("trades", []))
    subject = f"Options Watchlist {date} — {trade_count} trade(s)"
    html = build_html(watchlist)

    payload = {
        "personalizations": [{"to": [{"email": to_email}]}],
        "from": {"email": from_email, "name": from_name},
        "subject": subject,
        "content": [{"type": "text/html", "value": html}],
    }

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        SENDGRID_API_URL,
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            print(f"Email sent — status {resp.status}: {subject}")
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8")
        print(f"ERROR: SendGrid {e.code}: {body_text}", file=sys.stderr)
        sys.exit(1)


# ── Discord ───────────────────────────────────────────────────────────────────

def build_discord_embed(trade: dict, index: int) -> dict:
    direction = trade.get("direction", "")
    color = DISCORD_COLOR.get(direction, 0x6C757D)
    symbol = trade.get("symbol", "")
    category = trade.get("trade_category", "")
    t = trade.get("trade", {})

    if_text = "\n".join(f"• {c}" for c in trade.get("if_conditions", []))
    trade_text = (
        f"**{t.get('structure','')}** {t.get('strike','')} — {t.get('expiry','')} ({t.get('dte','')} DTE)\n"
        f"Entry: {t.get('entry_range','')}\n"
        f"Target: {t.get('target','')}\n"
        f"Stop: {t.get('stop','')}"
    )

    return {
        "title": f"[{index}] {symbol} — {direction} | {category}",
        "description": trade.get("context", ""),
        "color": color,
        "fields": [
            {"name": "IF conditions", "value": if_text or "—", "inline": False},
            {"name": "THEN trade", "value": trade_text, "inline": False},
            {"name": "Invalidation", "value": trade.get("invalidation", "—"), "inline": False},
            {"name": "Confidence", "value": trade.get("confidence", "—"), "inline": True},
            {"name": "Type", "value": trade.get("type", "—"), "inline": True},
        ],
    }


def send_discord(watchlist: dict) -> None:
    webhook_url = get_env("DISCORD_WEBHOOK_URL")
    date = watchlist.get("date", "")
    gen_at = watchlist.get("generated_at_et", "")
    market_ctx = watchlist.get("market_context", "")
    trades = watchlist.get("trades", [])
    no_trades = watchlist.get("no_trades", False)
    skipped = watchlist.get("skipped", [])

    if no_trades or not trades:
        payload = {
            "content": f"**Options Watchlist — {date}**\n> {market_ctx}\n\nNo trades today — quality bar not met.",
        }
    else:
        embeds = [build_discord_embed(t, i + 1) for i, t in enumerate(trades)]
        skipped_text = ""
        if skipped:
            skipped_text = "\n**Skipped:** " + " | ".join(skipped)

        payload = {
            "content": (
                f"**Options Watchlist — {date}** | Generated {gen_at}\n"
                f"> {market_ctx}"
                f"{skipped_text}"
            ),
            "embeds": embeds,
        }

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            print(f"Discord posted — status {resp.status}")
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8")
        print(f"ERROR: Discord webhook {e.code}: {body_text}", file=sys.stderr)
        sys.exit(1)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    if not os.path.exists(INPUT_FILE):
        print(f"ERROR: {INPUT_FILE} not found in current directory.", file=sys.stderr)
        sys.exit(1)

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        watchlist = json.load(f)

    trade_count = len(watchlist.get("trades", []))
    print(f"Posting watchlist for {watchlist.get('date','?')} — {trade_count} trade(s)")

    send_email(watchlist)
    send_discord(watchlist)


if __name__ == "__main__":
    main()
