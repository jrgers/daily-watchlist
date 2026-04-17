"""
Fetch daily market data for the options watchlist universe.

Runs via GitHub Actions every weekday at 12:30 UTC (8:30am ET).
Outputs watchlist_input.json to the repo root for the Claude agent to read.

Requirements: yfinance, pandas
"""

import json
import logging
import time
import datetime
import pandas as pd
import yfinance as yf

# Suppress yfinance internal error noise (404s on ETFs with no fundamentals data are expected)
logging.getLogger("yfinance").setLevel(logging.CRITICAL)

UNIVERSE_FILE = "watchlist_universe.json"
OUTPUT_FILE = "watchlist_input.json"

# ETFs and funds have no earnings dates — skip the calendar call entirely
NO_EARNINGS_SYMBOLS = {"SPY", "QQQ", "IWM", "GLD", "TLT", "XLF", "XLE", "XLK", "XBI", "GDX"}


def load_universe() -> dict:
    with open(UNIVERSE_FILE, "r") as f:
        return json.load(f)


def batch_download_daily(tickers: list[str]) -> pd.DataFrame:
    """Download 1-year daily OHLCV for MAs, ATR, HV, 52-week range."""
    print(f"Downloading 1-year daily data for {len(tickers)} tickers...")
    return yf.download(
        tickers,
        period="1y",
        auto_adjust=True,
        progress=False,
        group_by="ticker",
    )


def batch_download_premarket(tickers: list[str]) -> pd.DataFrame:
    """Download today's 1-min bars including pre/post market to capture pre-market prices."""
    print(f"Downloading pre-market 1-min bars for {len(tickers)} tickers...")
    return yf.download(
        tickers,
        period="1d",
        interval="1m",
        auto_adjust=True,
        prepost=True,
        progress=False,
        group_by="ticker",
    )


def get_premarket_price(symbol: str, pm_raw: pd.DataFrame, prev_close: float) -> tuple[float | None, float | None]:
    """
    Extract the latest pre-market price from the 1-min intraday download.
    Pre-market = candles before 13:30 UTC (9:30am ET).
    Returns (price, change_pct) or (None, None).
    """
    try:
        multi = hasattr(pm_raw.columns, "levels") and len(pm_raw.columns.levels[0]) > 1
        close_series = pm_raw[symbol]["Close"] if multi else pm_raw["Close"]
        close_series = close_series.dropna()
        if close_series.empty:
            return None, None

        # Filter to pre-market only: before 13:30 UTC
        pre = close_series[close_series.index.tz_convert("UTC").hour * 60
                           + close_series.index.tz_convert("UTC").minute < 13 * 60 + 30]
        if pre.empty:
            return None, None

        pm_price = float(pre.iloc[-1])
        if prev_close and prev_close > 0:
            change_pct = round((pm_price - prev_close) / prev_close * 100, 2)
        else:
            change_pct = None
        return round(pm_price, 2), change_pct
    except Exception:
        return None, None


def compute_ticker_stats(symbol: str, raw: pd.DataFrame) -> dict | None:
    """Extract stats for a single ticker from the 1-year batch download."""
    try:
        multi = hasattr(raw.columns, "levels") and len(raw.columns.levels[0]) > 1
        close = (raw[symbol]["Close"] if multi else raw["Close"]).dropna()
        high_s = (raw[symbol]["High"] if multi else raw["High"]).dropna()
        low_s = (raw[symbol]["Low"] if multi else raw["Low"]).dropna()
        vol_s = (raw[symbol]["Volume"] if multi else raw["Volume"]).dropna()

        if len(close) < 50:
            print(f"  {symbol}: insufficient history, skipping")
            return None

        prev_close = float(close.iloc[-1])
        ma20 = float(close.rolling(20).mean().iloc[-1])
        ma50 = float(close.rolling(50).mean().iloc[-1])
        high_52w = float(high_s.max())
        low_52w = float(low_s.min())

        range_position = (
            (prev_close - low_52w) / (high_52w - low_52w) * 100
            if high_52w != low_52w else 50.0
        )

        # ATR-14
        hl = high_s - low_s
        hc = (high_s - close.shift(1)).abs()
        lc = (low_s - close.shift(1)).abs()
        atr14 = float(pd.concat([hl, hc, lc], axis=1).max(axis=1).rolling(14).mean().iloc[-1])

        # Volume ratio
        avg_vol = float(vol_s.rolling(20).mean().iloc[-1])
        last_vol = float(vol_s.iloc[-1])
        volume_ratio = round(last_vol / avg_vol, 2) if avg_vol > 0 else 1.0

        # 30-day historical volatility (annualized)
        hv30_raw = close.pct_change().dropna().rolling(30).std().iloc[-1] * (252 ** 0.5) * 100
        hv30 = round(float(hv30_raw), 1) if not pd.isna(hv30_raw) else None

        return {
            "symbol": symbol,
            "prev_close": round(prev_close, 2),
            "ma20": round(ma20, 2),
            "ma50": round(ma50, 2),
            "price_vs_ma20_pct": round((prev_close - ma20) / ma20 * 100, 2),
            "price_vs_ma50_pct": round((prev_close - ma50) / ma50 * 100, 2),
            "high_52w": round(high_52w, 2),
            "low_52w": round(low_52w, 2),
            "range_position_pct": round(range_position, 1),
            "atr14": round(atr14, 2),
            "volume_ratio_vs_20d_avg": volume_ratio,
            "hv30_annualized_pct": hv30,
        }

    except Exception as e:
        print(f"  {symbol}: stats error — {e}")
        return None


def fetch_earnings(symbol: str) -> tuple[str | None, bool]:
    """Return (next_earnings_date_str, earnings_within_2_days)."""
    if symbol in NO_EARNINGS_SYMBOLS:
        return None, False
    try:
        t = yf.Ticker(symbol)
        cal = t.get_calendar()
        if cal and "Earnings Date" in cal:
            earn_dates = list(cal["Earnings Date"])
            if earn_dates:
                next_earn = pd.Timestamp(earn_dates[0]).date()
                days = (next_earn - datetime.date.today()).days
                return str(next_earn), (0 <= days <= 2)
    except Exception:
        pass
    return None, False




def main():
    universe_data = load_universe()
    tickers = universe_data["universe"]

    today = datetime.date.today().strftime("%Y-%m-%d")
    print(f"Fetching watchlist data for {today} — {len(tickers)} tickers")

    # Step 1: 1-year daily data (MAs, ATR, HV, range)
    raw_daily = batch_download_daily(tickers)

    # Step 2: Today's 1-min pre-market data
    raw_pm = batch_download_premarket(tickers)

    # Step 3: Compute per-ticker stats from daily data
    results = []
    for symbol in tickers:
        stats = compute_ticker_stats(symbol, raw_daily)
        if stats is None:
            continue
        results.append(stats)

    # Step 4: Add pre-market prices from intraday batch
    print("Extracting pre-market prices...")
    for entry in results:
        pm_price, pm_chg = get_premarket_price(entry["symbol"], raw_pm, entry["prev_close"])
        entry["pre_market_price"] = pm_price
        entry["pre_market_change_pct"] = pm_chg

    # Step 5: Earnings dates (individual calls, throttled)
    print("Fetching earnings dates...")
    for entry in results:
        next_earn, within_2 = fetch_earnings(entry["symbol"])
        entry["next_earnings"] = next_earn
        entry["earnings_within_2_days"] = within_2
        time.sleep(0.3)

    output = {
        "date": today,
        "generated_at_utc": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ticker_count": len(results),
        "tickers": results,
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)

    earnings_flagged = [e["symbol"] for e in results if e.get("earnings_within_2_days")]
    big_movers = [
        f"{e['symbol']} {e['pre_market_change_pct']:+.1f}%"
        for e in results
        if e.get("pre_market_change_pct") and abs(e["pre_market_change_pct"]) >= 3
    ]

    print(f"\nSaved {len(results)} tickers to {OUTPUT_FILE}")
    if earnings_flagged:
        print(f"Earnings within 2 days (will be skipped): {', '.join(earnings_flagged)}")
    if big_movers:
        print(f"Pre-market movers (>=3%): {', '.join(big_movers)}")


if __name__ == "__main__":
    main()
