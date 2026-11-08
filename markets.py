"""
Several markets, one event study: how did each market react to the same events?

The same event dates (OPEC+ decisions, EIA reports, Fed moves, news spikes...)
are measured in every market below, from the close BEFORE the event. Markets
differ a lot in how much they normally move (natural gas swings far more
than the dollar), so every comparison here is also shown against that
market's own typical move.

Prices come from fetch_prices.py (table "prices" in data/oil.db).
"""

import math

import numpy as np
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


# ---------------------------------------------------------------------------
# "Is this real?" - could random days have produced this average?
# ---------------------------------------------------------------------------
STRONG, POSSIBLE = 0.02, 0.10      # p-value cut-offs for the two pattern labels
MIN_EVENTS = 5
VERDICTS = {
    "strong": ("Strong pattern", "#1d6b4f"),
    "possible": ("Possible pattern", "#b07a00"),
    "noise": ("Could be noise", "#898781"),
    "few": ("Too few events", "#898781"),
}


class Significance:
    """For each market and horizon, every past N-day move from an ordinary
    day. To judge an average after N events, we draw N random days thousands
    of times and see how often their average strays as far from normal as
    the events' average did. That share is the p-value: small = unlikely to
    be luck. (For large N the bell-curve shortcut gives the same answer.)"""

    SIMS = 4000

    def __init__(self, markets: dict):
        self.moves = {}
        for key, prices in markets.items():
            values = prices.to_numpy(dtype=float)
            for h in es.HORIZONS:
                base, later = values[:-h], values[h:]
                ok = (base > 0) & (later > 0)
                self.moves[key, h] = (later[ok] / base[ok] - 1) * 100
        self._null = {}
        self._rng = np.random.default_rng(42)       # fixed, so results don't flicker

    def p_value(self, market: str, horizon: int, values) -> float:
        values = np.asarray(values, dtype=float)
        values = values[~np.isnan(values)]
        n = len(values)
        moves = self.moves.get((market, horizon))
        if moves is None or n == 0:
            return float("nan")
        normal = moves.mean()
        gap = abs(values.mean() - normal)
        if n > 100:                                   # bell-curve shortcut
            z = gap / (moves.std() / math.sqrt(n))
            return math.erfc(z / math.sqrt(2))
        if (market, horizon, n) not in self._null:
            picks = self._rng.integers(0, len(moves), size=(self.SIMS, n))
            self._null[market, horizon, n] = np.abs(moves[picks].mean(axis=1) - normal)
        return float((self._null[market, horizon, n] >= gap).mean())

    @staticmethod
    def verdict(p: float, n: int) -> str:
        if n < MIN_EVENTS or pd.isna(p):
            return "few"
        return "strong" if p < STRONG else "possible" if p < POSSIBLE else "noise"

    def check(self, market: str, horizon: int, values) -> str:
        values = pd.Series(values, dtype=float).dropna()
        return self.verdict(self.p_value(market, horizon, values), len(values))


def typical_moves(markets: dict[str, pd.Series]) -> dict[int, dict[str, float]]:
    """{horizon: {market: median size of an ordinary move over that horizon}}."""
    return {h: {key: es.typical_move(prices, h) for key, prices in markets.items()}
            for h in es.HORIZONS}


def by_category(by_market: dict, cat_col: str, categories: list, labels: dict,
                horizon: int, sig: Significance | None = None):
    """Average move after each kind of event (rows) in each market (columns).
    With `sig`, also returns a same-shaped table of verdicts ("strong", ...)."""
    col = f"day_{horizon}_pct"
    means, verdicts = {}, {}
    for key, (results, _) in by_market.items():
        if results.empty:
            continue
        groups = results.groupby(cat_col)[col]
        means[key] = groups.mean().reindex(categories)
        if sig is not None:
            verdicts[key] = pd.Series({c: sig.check(key, horizon, g) for c, g in groups},
                                      dtype=object).reindex(categories).fillna("few")
    order = [k for k in MARKETS if k in means]
    out = pd.DataFrame(means).reindex(columns=order)
    out.index = [labels[c] for c in out.index]
    if sig is None:
        return out
    v = pd.DataFrame(verdicts).reindex(columns=order)
    v.index = out.index
    return out, v


def for_events(by_market: dict, keep=None, sig: Significance | None = None) -> pd.DataFrame:
    """One row per market: how it moved after a set of events.
    keep: optional function(results) -> True/False rows to include.
    With `sig`, adds a verdict column per horizon (verdict_1, verdict_5, ...)."""
    rows = []
    for key, (results, _) in by_market.items():
        if results.empty:
            continue
        group = results[keep(results)] if keep else results
        if group.empty:
            continue
        rows.append({"market": MARKETS[key][0], "key": key, "events": len(group),
                     **{f"day_{h}_pct": group[f"day_{h}_pct"].mean() for h in es.HORIZONS},
                     "pct_up_5": (group["day_5_pct"] > 0).mean() * 100,
                     **({f"verdict_{h}": sig.check(key, h, group[f"day_{h}_pct"])
                         for h in es.HORIZONS} if sig is not None else {})})
    return pd.DataFrame(rows)
