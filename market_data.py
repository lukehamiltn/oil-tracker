"""
Extra market data used by the strategies (all free U.S. government data):

- CFTC Commitments of Traders: how "managed money" (hedge funds, CTAs) is
  positioned in WTI crude futures. Reported every Friday for the previous
  Tuesday. Very one-sided positioning often comes before reversals.
- Broad U.S. dollar index (Federal Reserve, via FRED). Oil is priced in
  dollars, so it tends to move opposite to the dollar.

Run it with:   python market_data.py
"""

import io
import sqlite3

import pandas as pd
import requests

from event_study import DB_PATH

COT_URL = "https://publicreporting.cftc.gov/resource/72hh-3qpy.json"
WTI_CODE = "067651"  # CFTC's code for NYMEX WTI crude oil futures
DOLLAR_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DTWEXBGS"


def _save(table: pd.DataFrame, name: str) -> None:
    DB_PATH.parent.mkdir(exist_ok=True)
    with sqlite3.connect(DB_PATH) as db:
        table.to_sql(name, db, if_exists="replace", index=False)


def download_cot() -> None:
    print("Downloading CFTC positioning (Commitments of Traders)...")
    params = {
        "$select": "report_date_as_yyyy_mm_dd, m_money_positions_long_all, "
                   "m_money_positions_short_all, open_interest_all",
        "$where": f"cftc_contract_market_code='{WTI_CODE}'",
        "$order": "report_date_as_yyyy_mm_dd",
        "$limit": 50000,
    }
    response = requests.get(COT_URL, params=params, timeout=60)
    response.raise_for_status()
    table = pd.DataFrame(response.json())
    table.columns = ["report_date", "mm_long", "mm_short", "open_interest"]
    table["report_date"] = table["report_date"].str[:10]
    for col in ["mm_long", "mm_short", "open_interest"]:
        table[col] = pd.to_numeric(table[col])
    _save(table, "cot")
    print(f"  {len(table):,} weekly reports ({table['report_date'].iloc[0]} "
          f"to {table['report_date'].iloc[-1]})")


def download_dollar() -> None:
    print("Downloading U.S. dollar index...")
    response = requests.get(DOLLAR_URL, timeout=60)
    response.raise_for_status()
    table = pd.read_csv(io.StringIO(response.text))
    table.columns = ["date", "value"]
    table["value"] = pd.to_numeric(table["value"], errors="coerce")
    table = table.dropna()
    _save(table, "dollar")
    print(f"  {len(table):,} days ({table['date'].iloc[0]} to {table['date'].iloc[-1]})")


def load_cot() -> pd.DataFrame:
    with sqlite3.connect(DB_PATH) as db:
        return pd.read_sql("SELECT * FROM cot", db, parse_dates=["report_date"])


def load_dollar() -> pd.Series:
    with sqlite3.connect(DB_PATH) as db:
        rows = pd.read_sql("SELECT * FROM dollar", db, parse_dates=["date"])
    return rows.set_index("date")["value"]


def main() -> None:
    download_cot()
    download_dollar()


if __name__ == "__main__":
    main()
