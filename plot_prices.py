"""
Draw a chart of the oil prices saved by fetch_prices.py.

Run it with:   python plot_prices.py
The chart is saved to data/oil_prices.png
"""

import sqlite3
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # draw straight to an image file, no pop-up window
import matplotlib.pyplot as plt
import pandas as pd

DATA_DIR = Path(__file__).parent / "data"
DB_PATH = DATA_DIR / "oil.db"
CHART_PATH = DATA_DIR / "oil_prices.png"

# A few well-known events, labelled on the chart for context
EVENTS = {
    "1990-08-02": "Iraq invades Kuwait",
    "2008-07-11": "2008 peak",
    "2014-11-27": "OPEC won't cut",
    "2020-04-20": "COVID crash",
    "2022-02-24": "Russia invades Ukraine",
}


def main() -> None:
    with sqlite3.connect(DB_PATH) as db:
        prices = pd.read_sql("SELECT series, date, price FROM prices", db,
                             parse_dates=["date"])

    # Reshape so each benchmark is its own column: date | BRENT | WTI
    wide = prices.pivot(index="date", columns="series", values="price")

    fig, ax = plt.subplots(figsize=(13, 6))
    ax.plot(wide.index, wide["WTI"], label="WTI", color="#1f6feb", linewidth=0.8)
    ax.plot(wide.index, wide["BRENT"], label="Brent", color="#d4730b",
            linewidth=0.8, alpha=0.8)

    for date, label in EVENTS.items():
        when = pd.Timestamp(date)
        ax.axvline(when, color="gray", linestyle=":", linewidth=0.8)
        ax.annotate(label, xy=(when, ax.get_ylim()[1]), rotation=90,
                    va="top", ha="right", fontsize=8, color="dimgray")

    ax.set_title("Crude oil spot prices, daily (USD per barrel)")
    ax.set_ylabel("$ / barrel")
    ax.axhline(0, color="black", linewidth=0.5)
    ax.grid(alpha=0.3)
    ax.legend(loc="upper left")
    fig.tight_layout()
    fig.savefig(CHART_PATH, dpi=110)
    print(f"Chart saved to {CHART_PATH}")


if __name__ == "__main__":
    main()
