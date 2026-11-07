"""
Federal Reserve interest-rate decisions as events.

Source: the Fed's target rate on FRED (DFEDTAR until Dec 2008, then the
upper end of the target range, DFEDTARU). Every change in the target is
one event. Rate changes matter for oil through the economy (demand) and the
dollar (oil is priced in dollars).

We classify each change by whether it TURNED the cycle:
  - first cut:  the first cut after a hike (a policy turn - often a scare)
  - cut:        a cut continuing a cutting cycle
  - first hike: the first hike after a cut
  - hike:       a hike continuing a hiking cycle

Limitations: FRED records the date a change took EFFECT, which since 2008
is usually the day after the announcement. To stay safe we treat the event
as one business day earlier, so our starting price is always from before
the announcement. Meetings where the Fed held rates aren't in this data.

Run it with:   python fed_events.py
"""

import io
import sqlite3

import pandas as pd
import requests

from event_study import DB_PATH

URLS = {
    "DFEDTAR": "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DFEDTAR",
    "DFEDTARU": "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DFEDTARU",
}
START = "1990-01-01"

CATEGORIES = ["first_cut", "cut", "hike", "first_hike"]
LABELS = {"first_cut": "First cut of a cycle", "cut": "Cut (continuing)",
          "hike": "Hike (continuing)", "first_hike": "First hike of a cycle"}
# Two-sided scale: blues = cuts, reds = hikes; darker = a turn in the cycle
COLORS = {"first_cut": "#104281", "cut": "#5598e7",
          "hike": "#e66767", "first_hike": "#a8282a"}


def download_fed() -> None:
    print("Downloading Fed target rate...")
    parts = []
    for name, url in URLS.items():
        response = requests.get(url, timeout=60)
        response.raise_for_status()
        part = pd.read_csv(io.StringIO(response.text))
        part.columns = ["date", "rate"]
        parts.append(part)
    table = pd.concat(parts).dropna()
    table["rate"] = pd.to_numeric(table["rate"], errors="coerce")
    table = table.dropna().drop_duplicates("date", keep="last").sort_values("date")
    DB_PATH.parent.mkdir(exist_ok=True)
    with sqlite3.connect(DB_PATH) as db:
        table.to_sql("fed_target", db, if_exists="replace", index=False)
    print(f"  {len(table):,} days ({table['date'].iloc[0]} to {table['date'].iloc[-1]})")


def load_fed() -> pd.Series:
    with sqlite3.connect(DB_PATH) as db:
        rows = pd.read_sql("SELECT * FROM fed_target", db, parse_dates=["date"])
    return rows.set_index("date")["rate"]


def build_events(rate: pd.Series) -> pd.DataFrame:
    change = rate.diff()
    moves = change[change.abs() > 1e-9]
    rows, previous_direction = [], 0
    for effective, size in moves.items():
        direction = 1 if size > 0 else -1
        turned = direction != previous_direction
        if direction < 0:
            category = "first_cut" if turned else "cut"
        else:
            category = "first_hike" if turned else "hike"
        previous_direction = direction
        bp = round(size * 100)
        rows.append({
            "date": effective - pd.offsets.BDay(1),
            "effective_date": effective,
            "decision": category,
            "size_bp": bp,
            "new_rate": rate.loc[effective],
            "description": f"Fed {'raises' if bp > 0 else 'cuts'} target by "
                           f"{abs(bp)} bp to {rate.loc[effective]:.2f}%",
        })
    events = pd.DataFrame(rows)
    return events[events["date"] >= START].reset_index(drop=True)


def main() -> None:
    download_fed()
    events = build_events(load_fed())
    print(f"\n{len(events)} rate changes since {START}:")
    for cat in CATEGORIES:
        print(f"  {LABELS[cat]:24} {(events['decision'] == cat).sum():>3}")
    print("\nLatest:", events.iloc[-1]["effective_date"].date(), events.iloc[-1]["description"])


if __name__ == "__main__":
    main()
