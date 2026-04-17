"""
Fetch daily market data for the options watchlist universe.

Runs via GitHub Actions every weekday at 13:30 UTC (8:30am ET).
Outputs watchlist_input.json to the repo root for the Claude agent to read.

Requirements: yfinance, pandas
"""

import json
import logging
import os
import sys
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

# Tickers to also fetch options chain IV for (most liquid names only — others too slow)
PRIORITY_IV_TICKERS = []


def load_universe() -> dict:
    with open(UNIVERSE_FILE, "r") as f:
        data = json.load(f)
    return data


def batch_download(tickers: list[str]) -> pd.DataFrame:
    """Download 1-year OHLCV for all tickers at once."""
    print(f"Downloading price data for {len(tickers)} tickers...")
    raw = yf.download(
        tickers,
        period="1y",
        auto_adjust=True,
        progress=False,
        group_by="ticker",
    )
    return raw


def compute_ticker_stats(symbol: str, raw: pd.DataFrame) -> dict | None:
    """Extract stats for a single ticker from the batch download result."""
    try:
        if len(raw.columns.levels[0]) > 1:
            # Multi-ticker download: first level is ticker
            close = raw[symbol]["Close"].dropna()
            high_s = raw[symbol]["High"].dropna()
            low_s = raw[symbol]["Low"].dropna()
            vol_s = raw[symbol]["Volume"].dropna()
        else:
            # Single-ticker fallback
            close = raw["Close"].dropna()
            high_s = raw["High"].dropna()
            low_s = raw["Low"].dropna()
            vol_s = raw["Volume"].dropna()

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
            if high_52w != low_52w
            else 50.0
        )

        # ATR-14
        hl = high_s - low_s
        hc = (high_s - close.shift(1)).abs()
        lc = (low_s - close.shift(1)).abs()
        tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
        atr14 = float(tr.rolling(14).mean().iloc[-1])

        # Volume ratio (last day vs 20-day avg)
        avg_vol = float(vol_s.rolling(20).mean().iloc[-1])
        last_vol = float(vol_s.iloc[-1])
        volume_ratio = round(last_vol / avg_vol, 2) if avg_vol > 0 else 1.0

        # 30-day historical volatility (annualized)
        returns = close.pct_change().dropna()
        hv30 = float(returns.rolling(30).std().iloc[-1] * (252 ** 0.5) * 100)

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
            "hv30_annualized_pct": round(hv30, 1) if not pd.isna(hv30) else None,
        }

    except Exception as e:
        print(f"  {symbol}: stats error — {e}")
        return None


def fetch_premarket_and_earnings(symbol: str) -> dict:
    """Fetch pre-market price and next earnings date for a single ticker."""
    result = {
        "pre_market_price": None,
        "pre_market_change_pct": None,
        "next_earnings": None,
        "earnings_within_2_days": False,
    }
    try:
        t = yf.Ticker(symbol)

        # Pre-market price
        info = t.fast_info
        pm = getattr(info, "pre_market_price", None)
        prev = getattr(info, "previous_close", None)
        if pm and prev and prev > 0:
            result["pre_market_price"] = round(float(pm), 2)
            result["pre_market_change_pct"] = round((pm - prev) / prev * 100, 2)

        # Earnings date (skip for ETFs — they have no earnings)
        if symbol not in NO_EARNINGS_SYMBOLS:
            try:
                cal = t.get_calendar()
                if cal and "Earnings Date" in cal:
                    earn_dates = cal["Earnings Date"]
                    if hasattr(earn_dates, "__iter__"):
                        earn_dates = list(earn_dates)
                        if earn_dates:
                            next_earn = pd.Timestamp(earn_dates[0]).date()
                            result["next_earnings"] = str(next_earn)
                            days = (next_earn - datetime.date.today()).days
                            result["earnings_within_2_days"] = 0 <= days <= 2
            except Exception:
                pass

    except Exception as e:
        print(f"  {symbol}: premarket/earnings error — {e}")

    return result


def fetch_atm_iv(symbol: str, prev_close: float) -> float | None:
    """Fetch ATM implied volatility from the nearest weekly options expiry."""
    try:
        t = yf.Ticker(symbol)
        expirations = t.options
        if not expirations:
            return None
        chain = t.option_chain(expirations[0])
        calls = chain.calls
        if calls.empty:
            return None
        idx = (calls["strike"] - prev_close).abs().idxmin()
        iv = calls.loc[idx, "impliedVolatility"]
        return round(float(iv) * 100, 1) if not pd.isna(iv) else None
    except Exception:
        return None


def main():
    universe_data = load_universe()
    tickers = universe_data["universe"]
    priority_iv = universe_data.get("priority_for_iv_fetch", tickers[:15])

    today = datetime.date.today().strftime("%Y-%m-%d")
    print(f"Fetching watchlist data for {today} — {len(tickers)} tickers")

    # Step 1: Batch price download
    raw = batch_download(tickers)

    # Step 2: Compute per-ticker stats
    results = []
    for symbol in tickers:
        stats = compute_ticker_stats(symbol, raw)
        if stats is None:
            continue
        results.append(stats)

    # Step 3: Pre-market prices + earnings (individual calls, throttled)
    print("Fetching pre-market prices and earnings dates...")
    for entry in results:
        pm_data = fetch_premarket_and_earnings(entry["symbol"])
        entry.update(pm_data)
        time.sleep(0.3)  # gentle rate limiting

    # Step 4: ATM IV for priority tickers only
    print(f"Fetching ATM IV for {len(priority_iv)} priority tickers...")
    stats_by_symbol = {e["symbol"]: e for e in results}
    for symbol in priority_iv:
        if symbol not in stats_by_symbol:
            continue
        prev_close = stats_by_symbol[symbol]["prev_close"]
        iv = fetch_atm_iv(symbol, prev_close)
        stats_by_symbol[symbol]["atm_iv_pct"] = iv
        time.sleep(0.5)

    # Fill atm_iv_pct as None for non-priority tickers
    for entry in results:
        if "atm_iv_pct" not in entry:
            entry["atm_iv_pct"] = None

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
