# Daily Options Watchlist — Setup Guide

## How It Works

```
GitHub Actions (daily-watchlist.yml)
  M-F 13:30 UTC (8:30am ET)
  └── fetch_watchlist_data.py → watchlist_input.json (committed to main)

Claude Code remote scheduled agent
  M-F ~13:40 UTC (10 min later)
  ├── Reads watchlist_input.json
  ├── Web-searches for premarket catalysts
  ├── Screens universe + ranks candidates
  └── Writes watchlist.json → pushes to claude/ branch

GitHub Actions (post-watchlist.yml)
  Triggered by claude/ branch push with watchlist.json
  ├── Merges claude/ branch into main
  ├── Sends HTML email via SendGrid
  └── Posts to Discord
```

---

## Step 1 — Add GitHub Secret: DISCORD_WEBHOOK_URL

In the GitHub repo: **Settings → Secrets and variables → Actions → New repository secret**

| Name | Value |
|---|---|
| `DISCORD_WEBHOOK_URL` | Your Discord webhook URL |

`SENDGRID_API_KEY` is already set from the portfolio advisor.

---

## Step 2 — Set Up Claude Code Remote Scheduled Agent

This is the analysis step. Set it up via Claude Code:

1. Open Claude Code in this repo
2. Run the `/schedule` command
3. Use these settings:
   - **Schedule**: `40 13 * * 1-5` (M-F 13:40 UTC — 10 min after data fetch)
   - **Prompt**: paste the full content of `watchlist_prompt.md`
   - **Working directory**: repo root

The agent will read `watchlist_input.json`, search for catalysts, and write `watchlist.json`.

---

## Step 3 — Test Run

**Test the data fetcher manually:**
```bash
pip install -r requirements.txt
python fetch_watchlist_data.py
```
Check that `watchlist_input.json` is created with ticker data.

**Test the post script manually** (requires a real `watchlist.json`):
```bash
SENDGRID_API_KEY=xxx DISCORD_WEBHOOK_URL=xxx python post_watchlist.py
```

**Trigger a full GitHub Actions run:**
Go to **Actions → Daily Watchlist — Fetch Market Data → Run workflow**

---

## Step 4 — Activate

Once test runs look good:
- `daily-watchlist.yml` is already scheduled (M-F 13:30 UTC) — it fires automatically
- The Claude Code scheduled task fires at 13:40 UTC — activate it in Claude Code
- `post-watchlist.yml` fires automatically when watchlist.json is pushed to claude/ branch

---

## What You Get Each Day (~9:45am ET)

**Email:** HTML-formatted trade cards with color-coded direction, full IF/THEN structure, entry/target/stop.

**Discord:** Embedded trade cards (green for bullish, red for bearish) with all IF conditions and trade details.

---

## Editing the Universe

To add or remove tickers: edit `watchlist_universe.json`.

- **`universe`** — full list screened by the agent
- **`priority_for_iv_fetch`** — subset that gets ATM IV fetched (keep this to ~15 for speed)

---

## Reference

| File | Purpose |
|---|---|
| `fetch_watchlist_data.py` | yfinance data fetch |
| `post_watchlist.py` | Email + Discord delivery |
| `watchlist_prompt.md` | Claude agent system prompt |
| `watchlist_universe.json` | Base ticker universe |
| `requirements.txt` | Python deps (yfinance, pandas) |
| `watchlist_input.json` | Generated daily — market data for agent |
| `watchlist.json` | Generated daily — agent output |
| `.github/workflows/daily-watchlist.yml` | Fetch schedule |
| `.github/workflows/post-watchlist.yml` | Post-agent delivery |
