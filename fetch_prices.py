"""
Download daily prices for every market we measure, and save them to a local
database (data/oil.db, table "prices").

Sources:
  - FRED (Federal Reserve Bank of St. Louis), which republishes EIA spot
    prices and the Fed's dollar index. U.S. government data - free and OK to
    show publicly.
  - Alpaca for the energy-stock fund XLE (needs the Alpaca keys; skipped
    without them).

Run it with:   python fetch_prices.py
Safe to run again any time - it refreshes the data with the latest prices.
If one source is down, the copy already saved for it is kept.
"""

import io
import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

# FRED series: {our name: FRED's code}
SERIES = {
    "WTI": "DCOILWTICO",          # West Texas Intermediate crude (U.S.), from 1986
    "BRENT": "DCOILBRENTEU",      # Brent crude (international), from 1987
    "GASOLINE": "DGASNYH",        # NY Harbor gasoline, $/gallon, from 1986
    "HEATING_OIL": "DHOILNYH",    # NY Harbor heating oil (diesel's close cousin), from 1986
    "NATGAS": "DHHNGSP",          # Henry Hub natural gas, $/MMBtu, from 1997
    "DOLLAR": "DTWEXBGS",         # Broad U.S. dollar index, from 2006
}
ALPACA_SERIES = {"XLE": "XLE"}   # Energy Select Sector fund (big U.S. oil & gas stocks)

FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={code}"

DATA_DIR = Path(__file__).parent / "data"
DB_PATH = DATA_DIR / "oil.db"


def download_series(name: str, code: str) -> pd.DataFrame:
    """Download one price series from FRED and return a clean table."""
    print(f"Downloading {name} ({code})...")
    response = requests.get(FRED_URL.format(code=code), timeout=60)
    response.raise_for_status()  # stop with an error if the download failed

    table = pd.read_csv(io.StringIO(response.text))
    table.columns = ["date", "price"]  # FRED's column names vary; standardize

    # FRED marks market holidays with "." - turn those into blanks and drop them
    table["price"] = pd.to_numeric(table["price"], errors="coerce")
    table = table.dropna(subset=["price"])

    table["date"] = pd.to_datetime(table["date"]).dt.strftime("%Y-%m-%d")
    table["series"] = name
    return table[["series", "date", "price"]]


def download_alpaca(name: str, symbol: str) -> pd.DataFrame:
    """Daily closes of a stock fund from Alpaca, adjusted for dividends and
    splits (so a % change is the investor's actual return)."""
    print(f"Downloading {name} (Alpaca)...")
    from alpaca.data.enums import Adjustment, DataFeed
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame
    from dotenv import load_dotenv

    load_dotenv()
    if "ALPACA_API_KEY" not in os.environ:
        try:                                  # on Streamlit Cloud the keys are secrets
            import streamlit as st
            for key in ("ALPACA_API_KEY", "ALPACA_SECRET_KEY"):
                os.environ.setdefault(key, st.secrets[key])
        except Exception:
            pass
    client = StockHistoricalDataClient(os.environ["ALPACA_API_KEY"],
                                       os.environ["ALPACA_SECRET_KEY"])
    bars = client.get_stock_bars(StockBarsRequest(
        symbol_or_symbols=symbol, timeframe=TimeFrame.Day,
        start=datetime(2015, 1, 1, tzinfo=timezone.utc), adjustment=Adjustment.ALL,
        feed=DataFeed.SIP)).df.reset_index()
    days = bars["timestamp"].dt.tz_convert("America/New_York").dt.strftime("%Y-%m-%d")
    return pd.DataFrame({"series": name, "date": days, "price": bars["close"]})


def saved_prices() -> pd.DataFrame:
    if not DB_PATH.exists():
        return pd.DataFrame(columns=["series", "date", "price"])
    with sqlite3.connect(DB_PATH) as db:
        try:
            return pd.read_sql("SELECT series, date, price FROM prices", db)
        except Exception:
            return pd.DataFrame(columns=["series", "date", "price"])


def save_to_database(table: pd.DataFrame) -> None:
    """Replace the prices table in our SQLite database with fresh data."""
    DATA_DIR.mkdir(exist_ok=True)
    with sqlite3.connect(DB_PATH) as db:
        table.to_sql("prices", db, if_exists="replace", index=False)
        db.execute("CREATE INDEX IF NOT EXISTS idx_prices ON prices (series, date)")


def main() -> None:
    jobs = [(download_series, name, code) for name, code in SERIES.items()]
    jobs += [(download_alpaca, name, symbol) for name, symbol in ALPACA_SERIES.items()]

    def run(job):
        func, name, code = job
        try:
            return name, func(name, code)
        except Exception as error:
            print(f"  {name} download failed ({error}); keeping the saved copy")
            return name, None

    with ThreadPoolExecutor(max_workers=4) as pool:   # downloads run side by side
        downloaded = dict(pool.map(run, jobs))

    saved = saved_prices()
    tables = [table if table is not None else saved[saved["series"] == name]
              for name, table in downloaded.items()]
    all_prices = pd.concat(tables, ignore_index=True)
    save_to_database(all_prices)

    print(f"\nSaved {len(all_prices):,} prices to {DB_PATH}\n")
    for name, group in all_prices.groupby("series"):
        latest = group.iloc[-1]
        print(f"  {name:12} {group['date'].min()} to {latest['date']}"
              f"  ({len(group):,} days)  latest: {latest['price']:.2f}")


if __name__ == "__main__":
    main()
