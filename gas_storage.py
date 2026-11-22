"""
EIA weekly natural gas storage reports, turned into events.

Every Thursday at 10:30am ET the U.S. Energy Information Administration
publishes how much natural gas is in underground storage in the Lower 48
states (billion cubic feet, "Bcf"). Traders watch the weekly CHANGE:
  - a smaller injection / bigger withdrawal than normal -> tight supply -> bullish
  - a bigger injection / smaller withdrawal than normal -> plenty of gas -> bearish

As with the oil report, what moves prices is the SURPRISE. Professional
forecasts aren't free, so the stand-in is how much storage normally changes
in that same week of the year (average of the previous 5 years). Gas is
injected into storage from about April to October and withdrawn in winter.

Run it with:   python gas_storage.py
"""

import io
import sqlite3

import pandas as pd
import requests
from pandas.tseries.holiday import USFederalHolidayCalendar

from event_study import DB_PATH

# Public EIA download - no API key needed. Lower 48 working gas, weekly, Bcf.
EIA_URL = "https://www.eia.gov/dnav/ng/hist_xls/NW2_EPG0_SWO_R48_BCFw.xls"

START = "2015-01-01"   # reports analysed from here (5 years of history before it set "normal")

CATEGORIES = ["big_draw", "draw", "normal", "build", "big_build"]
LABELS = {
    "big_draw": "Much tighter than normal",
    "draw": "Tighter than normal",
    "normal": "About normal",
    "build": "Looser than normal",
    "big_build": "Much looser than normal",
}
# Blue = tighter (bullish for prices), grey = normal, red = looser (bearish)
COLORS = {
    "big_draw": "#104281", "draw": "#5598e7", "normal": "#898781",
    "build": "#e66767", "big_build": "#a8282a",
}
# Surprise thresholds in Bcf (each bucket holds roughly a fifth of reports)
SMALL, LARGE = 7.0, 27.0


def download_storage() -> None:
    """Download weekly Lower 48 gas storage from EIA into the database."""
    print("Downloading EIA weekly natural gas storage...")
    response = requests.get(EIA_URL, timeout=60)
    response.raise_for_status()
    table = pd.read_excel(io.BytesIO(response.content), sheet_name="Data 1", skiprows=2, engine="calamine")
    table = table.iloc[:, :2]
    table.columns = ["week_ending", "storage_bcf"]
    table["week_ending"] = pd.to_datetime(table["week_ending"]).dt.strftime("%Y-%m-%d")
    table = table.dropna()
    DB_PATH.parent.mkdir(exist_ok=True)
    with sqlite3.connect(DB_PATH) as db:
        table.to_sql("gas_storage", db, if_exists="replace", index=False)
    print(f"Saved {len(table):,} weeks ({table['week_ending'].iloc[0]} to {table['week_ending'].iloc[-1]})")


def load_storage() -> pd.Series:
    with sqlite3.connect(DB_PATH) as db:
        rows = pd.read_sql("SELECT week_ending, storage_bcf FROM gas_storage", db, parse_dates=["week_ending"])
    return rows.set_index("week_ending")["storage_bcf"].astype(float).sort_index()


def release_dates(week_endings: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """The report for a week ending Friday comes out the next Thursday, or a
    day later if a federal holiday falls earlier in that week. (An
    approximation - EIA occasionally moves other weeks too.)"""
    holidays = USFederalHolidayCalendar().holidays(start="2000", end="2040")
    out = []
    for friday in week_endings:
        thursday = friday + pd.Timedelta(days=6)
        monday = thursday - pd.Timedelta(days=3)
        delayed = ((holidays >= monday) & (holidays <= thursday)).any()
        out.append(thursday + pd.Timedelta(days=1 if delayed else 0))
    return pd.DatetimeIndex(out)


def next_reports(after: pd.Timestamp, n: int = 4) -> list[pd.Timestamp]:
    """The next `n` report days (Thursdays, moved for holidays) from `after`."""
    friday = after - pd.Timedelta(days=(after.weekday() - 4) % 7 + 7)
    days = release_dates(pd.DatetimeIndex([friday + pd.Timedelta(weeks=i) for i in range(n + 2)]))
    return [d for d in days if d.normalize() >= after.normalize()][:n]


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
    def word(x: float) -> str:
        return f"{'injection' if x > 0 else 'withdrawal'} of {abs(x):.0f} Bcf"
    return f"Storage: {word(change)} (normal for this week: {word(normal)})"


def build_events(storage: pd.Series) -> pd.DataFrame:
    """One row per weekly report, with its surprise and category."""
    change = storage.diff()
    week_of_year = change.index.isocalendar().week.values
    # Normal = average change for the same week in the previous 5 years
    normal = change.groupby(week_of_year).transform(lambda s: s.shift(1).rolling(5, min_periods=3).mean())
    events = pd.DataFrame({
        "week_ending": storage.index,
        "date": release_dates(storage.index),
        "change_bcf": change.round(1).values,
        "normal_bcf": normal.round(1).values,
    }).dropna()
    events["surprise_bcf"] = (events["change_bcf"] - events["normal_bcf"]).round(1)
    events["category"] = events["surprise_bcf"].apply(classify)
    events["description"] = [describe(c, n) for c, n in zip(events["change_bcf"], events["normal_bcf"])]
    return events[events["week_ending"] >= START].reset_index(drop=True)


def main() -> None:
    download_storage()
    events = build_events(load_storage())
    print(f"\n{len(events):,} reports since {START}:")
    for cat in CATEGORIES:
        print(f"  {LABELS[cat]:28} {(events['category'] == cat).sum():>4}")
    print("surprise quantiles:", events["surprise_bcf"].quantile([0.2, 0.4, 0.6, 0.8]).round(1).tolist())
    latest = events.iloc[-1]
    print(f"\nLatest report ({latest['date']:%a %b %d, %Y}): {latest['description']} -> {LABELS[latest['category']]}")


if __name__ == "__main__":
    main()
