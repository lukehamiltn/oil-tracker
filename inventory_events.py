"""
EIA weekly crude oil inventory reports, turned into events.

Every Wednesday at 10:30am ET the U.S. Energy Information Administration
publishes how much crude oil is in storage in the U.S. (excluding the
Strategic Petroleum Reserve). Traders watch the weekly CHANGE:
  - a "draw" (stocks fell)  -> demand is strong / supply is tight -> bullish
  - a "build" (stocks rose) -> supply is piling up                -> bearish

What moves prices is the SURPRISE, not the raw number. Professional
forecasts aren't free, so we use a simple stand-in: how much stocks
normally change in that same week of the year (average of the previous
5 years). Stocks usually build in spring and draw in summer, so a 3M
barrel draw in July means something different from one in March.

Run it with:   python inventory_events.py
"""

import io
import sqlite3

import pandas as pd
import requests
from pandas.tseries.holiday import USFederalHolidayCalendar

from event_study import DB_PATH

# Public EIA download - no API key needed. Values are thousand barrels.
EIA_URL = "https://www.eia.gov/dnav/pet/hist_xls/WCESTUS1w.xls"

START = "2006-01-01"   # analyse roughly the last 20 years of reports

CATEGORIES = ["big_draw", "draw", "normal", "build", "big_build"]
LABELS = {
    "big_draw": "Much bigger draw than normal",
    "draw": "Bigger draw than normal",
    "normal": "About normal",
    "build": "Bigger build than normal",
    "big_build": "Much bigger build than normal",
}
# Ordered categories -> two-sided colour scale: blue = draws (bullish),
# grey = normal, red = builds (bearish). Darker = bigger surprise.
COLORS = {
    "big_draw": "#104281", "draw": "#5598e7", "normal": "#898781",
    "build": "#e66767", "big_build": "#a8282a",
}
# Surprise thresholds in million barrels (each bucket ~ 1/5 of reports)
SMALL, LARGE = 1.25, 4.0


def download_inventories() -> None:
    """Download weekly U.S. crude stocks from EIA into the database."""
    print("Downloading EIA weekly crude inventories...")
    response = requests.get(EIA_URL, timeout=60)
    response.raise_for_status()
    table = pd.read_excel(io.BytesIO(response.content), sheet_name="Data 1",
                          skiprows=2, engine="calamine")
    table.columns = ["week_ending", "stocks_kb"]
    table["week_ending"] = pd.to_datetime(table["week_ending"]).dt.strftime("%Y-%m-%d")
    table = table.dropna()

    DB_PATH.parent.mkdir(exist_ok=True)
    with sqlite3.connect(DB_PATH) as db:
        table.to_sql("inventories", db, if_exists="replace", index=False)
    print(f"Saved {len(table):,} weeks ({table['week_ending'].iloc[0]} to "
          f"{table['week_ending'].iloc[-1]})")


def load_inventories() -> pd.Series:
    with sqlite3.connect(DB_PATH) as db:
        rows = pd.read_sql("SELECT week_ending, stocks_kb FROM inventories", db,
                           parse_dates=["week_ending"])
    return rows.set_index("week_ending")["stocks_kb"].sort_index()


def release_dates(week_endings: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """The report for a week ending Friday comes out the next Wednesday,
    or Thursday if a federal holiday falls earlier in that week.
    (An approximation - EIA occasionally shifts other weeks too.)"""
    holidays = USFederalHolidayCalendar().holidays(start="1980", end="2040")
    out = []
    for friday in week_endings:
        wednesday = friday + pd.Timedelta(days=5)
        monday = wednesday - pd.Timedelta(days=2)
        delayed = ((holidays >= monday) & (holidays <= wednesday)).any()
        out.append(wednesday + pd.Timedelta(days=1 if delayed else 0))
    return pd.DatetimeIndex(out)


def classify(surprise: float) -> str:
    if surprise <= -LARGE:
        return "big_draw"
    if surprise <= -SMALL:
        return "draw"
    if surprise < SMALL:
        return "normal"
    if surprise < LARGE:
        return "build"
    return "big_build"


def describe(change: float, normal: float) -> str:
    actual = f"{'rose' if change > 0 else 'fell'} {abs(change):.1f}M bbl"
    usual = f"{'rise' if normal > 0 else 'fall'} {abs(normal):.1f}M bbl"
    return f"Stocks {actual} (normal for this week: {usual})"


def build_events(stocks: pd.Series) -> pd.DataFrame:
    """One row per weekly report, with its surprise and category."""
    change = stocks.diff() / 1000  # thousand -> million barrels
    week_of_year = change.index.isocalendar().week.values
    # Normal = average change for the same week in the previous 5 years.
    # shift(1) inside each week-of-year group = only PAST years are used.
    normal = change.groupby(week_of_year).transform(
        lambda s: s.shift(1).rolling(5, min_periods=3).mean())

    events = pd.DataFrame({
        "week_ending": stocks.index,
        "date": release_dates(stocks.index),
        "change_mb": change.round(2).values,
        "normal_mb": normal.round(2).values,
    }).dropna()
    events["surprise_mb"] = (events["change_mb"] - events["normal_mb"]).round(2)
    events["category"] = events["surprise_mb"].apply(classify)
    events["description"] = [describe(c, n) for c, n in
                             zip(events["change_mb"], events["normal_mb"])]
    return events[events["week_ending"] >= START].reset_index(drop=True)


def main() -> None:
    download_inventories()
    events = build_events(load_inventories())
    print(f"\n{len(events):,} reports since {START}:")
    for cat in CATEGORIES:
        print(f"  {LABELS[cat]:30} {(events['category'] == cat).sum():>4}")
    latest = events.iloc[-1]
    print(f"\nLatest report ({latest['date']:%a %b %d, %Y}): {latest['description']}"
          f" -> {LABELS[latest['category']]}")


if __name__ == "__main__":
    main()
