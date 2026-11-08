"""
Several markets, one event study: how did each market react to the same events?

The same event dates (OPEC+ decisions, EIA reports, Fed moves, news spikes...)
are measured in every market below, from the close BEFORE the event. Markets
differ a lot in how much they normally move (natural gas swings far more
than the dollar), so every comparison here is also shown against that
market's own typical move.

Prices come from fetch_prices.py (table "prices" in data/oil.db).
"""

import pandas as pd

import event_study as es

# key: (label, short label for buttons, colour)
MARKETS = {
    "BRENT": ("Brent crude", "Brent", "#2a78d6"),
    "WTI": ("WTI crude (U.S.)", "WTI", "#104281"),
    "GASOLINE": ("Gasoline", "Gasoline", "#eb6834"),
    "HEATING_OIL": ("Heating oil / diesel", "Heating oil", "#a8282a"),
    "NATGAS": ("Natural gas", "Natural gas", "#1baf7a"),
    "XLE": ("Energy stocks (XLE fund)", "Energy stocks", "#6250d6"),
    "DOLLAR": ("U.S. dollar index", "Dollar", "#898781"),
}
NOTES = {
    "XLE": "Energy stocks: data from 2016.",
    "DOLLAR": "Dollar: data from 2006.",
    "NATGAS": "Natural gas: data from 1997.",
}


def load_markets() -> dict[str, pd.Series]:
    """{market: daily prices}, skipping any market not downloaded yet."""
    out = {}
    for key in MARKETS:
        series = es.load_prices(key)
        if len(series):
            out[key] = series
    return out


def reactions(markets: dict[str, pd.Series], events: pd.DataFrame) -> dict:
    """{market: (results, paths)} - the event study run in every market."""
    return {key: es.compute_results(prices, events) for key, prices in markets.items()}


def typical_moves(markets: dict[str, pd.Series]) -> dict[int, dict[str, float]]:
    """{horizon: {market: median size of an ordinary move over that horizon}}."""
    return {h: {key: es.typical_move(prices, h) for key, prices in markets.items()}
            for h in es.HORIZONS}


def by_category(by_market: dict, cat_col: str, categories: list, labels: dict,
                horizon: int) -> pd.DataFrame:
    """Average move after each kind of event (rows) in each market (columns)."""
    col = f"day_{horizon}_pct"
    table = {}
    for key, (results, _) in by_market.items():
        if results.empty:
            continue
        table[key] = results.groupby(cat_col)[col].mean().reindex(categories)
    out = pd.DataFrame(table).reindex(columns=[k for k in MARKETS if k in table])
    out.index = [labels[c] for c in out.index]
    return out


def for_events(by_market: dict, keep=None) -> pd.DataFrame:
    """One row per market: how it moved after a set of events.
    keep: optional function(results) -> True/False rows to include."""
    rows = []
    for key, (results, _) in by_market.items():
        if results.empty:
            continue
        group = results[keep(results)] if keep else results
        if group.empty:
            continue
        rows.append({"market": MARKETS[key][0], "key": key, "events": len(group),
                     **{f"day_{h}_pct": group[f"day_{h}_pct"].mean() for h in es.HORIZONS},
                     "pct_up_5": (group["day_5_pct"] > 0).mean() * 100})
    return pd.DataFrame(rows)
