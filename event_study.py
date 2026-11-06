"""
Event study: how did oil prices move after each type of OPEC+ decision?

For every event we take the closing price on the last trading day BEFORE
the announcement (the "base"), then measure the % change 1, 5 and 20
trading days later. Using the day before keeps it honest: it is the last
price nobody could have known the decision at.

Run it with:   python event_study.py
Outputs:
  data/event_results.csv   one row per event, with its returns
  data/opec_reaction.png   average price path by decision type
"""

import sqlite3
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

ROOT = Path(__file__).parent
DB_PATH = ROOT / "data" / "oil.db"
EVENTS_PATH = ROOT / "events" / "opec_decisions.csv"
RESULTS_PATH = ROOT / "data" / "event_results.csv"
CHART_PATH = ROOT / "data" / "opec_reaction.png"

# Brent is the main benchmark here: it is the global price, and unlike WTI
# it never went negative (WTI hit -$37 in April 2020, which breaks % maths).
SERIES = "BRENT"
HORIZONS = [1, 5, 20]       # trading days after the base day (20 ~ one month)
WINDOW = range(-5, 21)      # days shown on the chart

DECISIONS = ["cut", "increase", "extend", "no_deal"]
LABELS = {"cut": "Cut", "increase": "Increase",
          "extend": "Extend existing cuts", "no_deal": "No deal / no cut"}
COLORS = {"cut": "#2a78d6", "increase": "#eb6834",
          "extend": "#1baf7a", "no_deal": "#eda100"}


def load_prices(series: str = SERIES) -> pd.Series:
    with sqlite3.connect(DB_PATH) as db:
        rows = pd.read_sql("SELECT date, price FROM prices WHERE series = ?",
                           db, params=[series], parse_dates=["date"])
    return rows.set_index("date")["price"].sort_index()


def load_events() -> pd.DataFrame:
    return pd.read_csv(EVENTS_PATH, parse_dates=["date"])


def compute_results(prices: pd.Series, events: pd.DataFrame):
    """Run the event study.

    Returns (results, paths):
      results - one row per event with its % change at each horizon
      paths   - {event date: % change for every day in WINDOW}
    """
    paths, rows = {}, []
    for _, event in events.iterrows():
        path = price_path(prices, event["date"])
        if path is None:
            print(f"  skipped {event['date'].date()} (not enough price data)")
            continue
        paths[event["date"]] = path
        rows.append({**event.to_dict(),  # keep all the event's own columns
                     **{f"day_{h}_pct": round(path[h], 2) for h in HORIZONS}})
    return pd.DataFrame(rows), paths


def price_path(prices: pd.Series, event_date: pd.Timestamp) -> pd.Series | None:
    """% change from the base day for each day in WINDOW (None if not enough data)."""
    before = prices.index[prices.index < event_date]
    if len(before) == 0:
        return None
    base_pos = prices.index.get_loc(before[-1])
    if base_pos + WINDOW.stop - 1 >= len(prices) or base_pos + WINDOW.start < 0:
        return None
    base_price = prices.iloc[base_pos]
    path = {d: (prices.iloc[base_pos + d] / base_price - 1) * 100 for d in WINDOW}
    return pd.Series(path)


def typical_move(prices: pd.Series, days: int) -> float:
    """Median size (ignoring direction) of an ordinary N-day move, for comparison."""
    changes = prices.pct_change(days, fill_method=None).dropna() * 100
    return changes.abs().median()


def main() -> None:
    prices = load_prices()
    results, paths = compute_results(prices, load_events())
    results.to_csv(RESULTS_PATH, index=False, date_format="%Y-%m-%d")

    # ---- Summary table -------------------------------------------------
    print(f"\n{SERIES} price change after OPEC+ decisions "
          f"(from close the day before)\n")
    header = f"{'decision':22} {'events':>6}"
    for h in HORIZONS:
        header += f" {'avg +' + str(h) + 'd':>9} {'% up':>5}"
    print(header)
    print("-" * len(header))
    for decision in DECISIONS:
        group = results[results["decision"] == decision]
        line = f"{LABELS[decision]:22} {len(group):>6}"
        for h in HORIZONS:
            col = group[f"day_{h}_pct"]
            line += f" {col.mean():>+8.1f}% {(col > 0).mean() * 100:>4.0f}%"
        print(line)

    print("\nFor comparison, a typical move on an ordinary day (median size):")
    for h in HORIZONS:
        print(f"  {h:>2} trading days: +/-{typical_move(prices, h):.1f}%")

    # ---- Chart: average path by decision type -----------------------------
    fig, ax = plt.subplots(figsize=(11, 6))
    fig.patch.set_facecolor("#fcfcfb")
    ax.set_facecolor("#fcfcfb")
    for decision in DECISIONS:
        dates = results.loc[results["decision"] == decision, "date"]
        group_paths = [paths[d] for d in dates]
        if not group_paths:
            continue
        avg = pd.concat(group_paths, axis=1).mean(axis=1)
        label = f"{LABELS[decision]} ({len(group_paths)})"
        ax.plot(avg.index, avg.values, color=COLORS[decision], linewidth=2,
                label=label)
        ax.annotate(f"{LABELS[decision]} {avg.iloc[-1]:+.1f}%",
                    xy=(avg.index[-1], avg.iloc[-1]), xytext=(6, 0),
                    textcoords="offset points", va="center", fontsize=9,
                    color="#52514e")

    ax.axhline(0, color="#c3c2b7", linewidth=1)
    ax.axvline(0, color="#898781", linestyle=":", linewidth=1)
    ax.annotate("base day\n(close before\nannouncement)", xy=(0, ax.get_ylim()[1]),
                xytext=(4, -4), textcoords="offset points", va="top",
                fontsize=8, color="#898781")
    ax.set_xlim(WINDOW.start, WINDOW.stop + 5)
    ax.set_xlabel("Trading days from base day", color="#52514e")
    ax.set_ylabel("Average % change in Brent", color="#52514e")
    ax.set_title("How Brent crude moved after OPEC+ decisions (average path)",
                 color="#0b0b0b", loc="left")
    ax.grid(color="#e1e0d9", linewidth=0.6)
    for side in ["top", "right"]:
        ax.spines[side].set_visible(False)
    for side in ["left", "bottom"]:
        ax.spines[side].set_color("#c3c2b7")
    ax.tick_params(colors="#898781")
    ax.legend(title="Decision (number of events)", frameon=False, loc="upper left",
              bbox_to_anchor=(0, -0.12), ncol=4, fontsize=9, title_fontsize=9)
    fig.tight_layout()
    fig.savefig(CHART_PATH, dpi=110)

    print(f"\nPer-event results: {RESULTS_PATH}")
    print(f"Chart:             {CHART_PATH}")


if __name__ == "__main__":
    main()
