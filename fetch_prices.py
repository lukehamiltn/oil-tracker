"""
Download daily crude oil prices and save them to a local database.

Source: FRED (Federal Reserve Bank of St. Louis), which republishes
EIA spot prices. U.S. government data - free and OK to show publicly.

Run it with:   python fetch_prices.py
Safe to run again any time - it refreshes the data with the latest prices.
"""

import io
import sqlite3
from pathlib import Path

import pandas as pd
import requests

# The oil price series we want: {our name: FRED's code for it}
SERIES = {
    "WTI": "DCOILWTICO",     # West Texas Intermediate (U.S. benchmark), from 1986
    "BRENT": "DCOILBRENTEU", # Brent (international benchmark), from 1987
}

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


def save_to_database(table: pd.DataFrame) -> None:
    """Replace the prices table in our SQLite database with fresh data."""
    DATA_DIR.mkdir(exist_ok=True)
    with sqlite3.connect(DB_PATH) as db:
        table.to_sql("prices", db, if_exists="replace", index=False)
        db.execute("CREATE INDEX IF NOT EXISTS idx_prices ON prices (series, date)")


def main() -> None:
    tables = [download_series(name, code) for name, code in SERIES.items()]
    all_prices = pd.concat(tables, ignore_index=True)
    save_to_database(all_prices)

    print(f"\nSaved {len(all_prices):,} prices to {DB_PATH}\n")
    for name, group in all_prices.groupby("series"):
        latest = group.iloc[-1]
        print(f"  {name:6} {group['date'].min()} to {latest['date']}"
              f"  ({len(group):,} days)  latest: ${latest['price']:.2f}")


if __name__ == "__main__":
    main()
