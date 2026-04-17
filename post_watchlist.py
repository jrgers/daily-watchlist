"""
Post the daily options watchlist to Discord.

Reads watchlist.json from the repo root (written by the Claude agent).

Environment variables required:
    DISCORD_WEBHOOK_URL  — Discord incoming webhook URL
"""

import json
import os
import sys
import urllib.request
import urllib.error

INPUT_FILE = "watchlist.json"

DISCORD_COLOR = {"BULLISH": 0x28A745, "BEARISH": 0xDC3545}


def get_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        print(f"ERROR: environment variable '{name}' is not set.", file=sys.stderr)
        sys.exit(1)
    return value


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
        headers={
            "Content-Type": "application/json",
            "User-Agent": "DiscordBot (daily-watchlist, 1.0)",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            print(f"Discord posted — status {resp.status}")
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8")
        print(f"ERROR: Discord webhook {e.code}: {body_text}", file=sys.stderr)
        sys.exit(1)


def main():
    if not os.path.exists(INPUT_FILE):
        print(f"ERROR: {INPUT_FILE} not found in current directory.", file=sys.stderr)
        sys.exit(1)

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        watchlist = json.load(f)

    trade_count = len(watchlist.get("trades", []))
    print(f"Posting watchlist for {watchlist.get('date','?')} — {trade_count} trade(s)")

    send_discord(watchlist)


if __name__ == "__main__":
    main()
