"""
Can a small model predict where oil goes next week?

The model reads the same daily facts the strategy lab uses (each one shifted
to the day it was really public - see strategies.build_features) and guesses
the chance that Brent is HIGHER five trading days later.

The test is "walk-forward", the way it would have worked in real life: every
month the model is retrained on everything known up to then (minus the last
week, whose answer wasn't known yet), and then predicts the following month,
which it has never seen. Its track record is compared with dumb guesses:
  - always guess "up" (oil rose in slightly more weeks than it fell)
  - guess the same direction as the past week
  - a coin flip (50%)
If the model can't beat those, it has no real skill.

Two models are tried:
  - "simple": logistic regression, a weighted sum of the facts
  - "trees":  gradient-boosted decision trees, which can find if-this-then-that
              patterns (and are also better at fooling themselves)

    python forecast.py      # print the track record
"""

import math

import numpy as np
import pandas as pd

HORIZON = 5            # trading days ahead (one week)
TEST_START = "2012-01-01"
MIN_TRAIN_DAYS = 750   # about 3 years of history before the first prediction
REFIT_DAYS = 21        # retrain every month (about 21 trading days)

FEATURES = {
    "trend_gap_pct": "Brent vs its 200-day average",
    "momentum_1m": "Brent change over the last month",
    "momentum_3m": "Brent change over the last 3 months",
    "change_1w": "Brent change over the last week",
    "volatility_1m": "How much Brent has been swinging",
    "inv_vs_normal_pct": "U.S. crude stocks vs normal",
    "mm_positioning_rank": "Hedge-fund positioning",
    "dollar_vs_50d_pct": "Dollar vs its 50-day average",
    "supply_news_recent": "Supply-scare news spike in the last week",
}


def table(features: pd.DataFrame) -> pd.DataFrame:
    """The model's inputs for every day, plus the answer (did Brent rise
    over the next week?) where it's already known."""
    p = features["price"]
    t = pd.DataFrame(index=features.index)
    t["trend_gap_pct"] = features["trend_gap_pct"]
    t["momentum_1m"] = (p / p.shift(21) - 1) * 100
    t["momentum_3m"] = (p / p.shift(63) - 1) * 100
    t["change_1w"] = (p / p.shift(5) - 1) * 100
    t["volatility_1m"] = p.pct_change().rolling(21).std() * math.sqrt(252) * 100
    t["inv_vs_normal_pct"] = features["inv_vs_normal_pct"]
    t["mm_positioning_rank"] = features["mm_positioning_rank"]
    t["dollar_vs_50d_pct"] = features["dollar_vs_50d_pct"]
    news = features["supply_news"].notna().astype(float)
    t["supply_news_recent"] = news.rolling(5, min_periods=1).max()
    t["ahead_pct"] = (p.shift(-HORIZON) / p - 1) * 100   # the answer (blank for the last week)
    t["up"] = (t["ahead_pct"] > 0).astype(float).where(t["ahead_pct"].notna())
    return t


def _models():
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    return {
        "simple": lambda: make_pipeline(StandardScaler(), LogisticRegression(C=0.1, max_iter=500)),
        "trees": lambda: HistGradientBoostingClassifier(max_depth=3, max_iter=150, learning_rate=0.05,
                                                        min_samples_leaf=80, random_state=0),
    }


def walk_forward(t: pd.DataFrame) -> pd.DataFrame:
    """Each model's out-of-sample probability of 'up' for every test day."""
    data = t.dropna(subset=list(FEATURES))
    days = data.index
    test_days = days[(days >= TEST_START)]
    test_days = test_days[test_days.isin(data.index[data["up"].notna()])]
    out = pd.DataFrame(index=test_days, columns=list(_models()), dtype=float)
    makers = _models()
    for start in range(0, len(test_days), REFIT_DAYS):
        block = test_days[start:start + REFIT_DAYS]
        first = block[0]
        # train on days whose answer was known before `first`: their week ended
        # before it, so drop the last HORIZON days before the block
        pos = days.get_loc(first)
        train = data.iloc[:max(0, pos - HORIZON)]
        train = train[train["up"].notna()]
        if len(train) < MIN_TRAIN_DAYS:
            continue
        x, y = train[list(FEATURES)].values, train["up"].values
        for name, make in makers.items():
            model = make().fit(x, y)
            out.loc[block, name] = model.predict_proba(data.loc[block, list(FEATURES)].values)[:, 1]
    out = out.dropna()
    out["up"] = t.loc[out.index, "up"]
    out["ahead_pct"] = t.loc[out.index, "ahead_pct"]
    out["last_week_up"] = (t.loc[out.index, "change_1w"] > 0).astype(float)
    return out


def _p_value(hits: int, n: int, chance: float) -> float:
    """How likely `hits` or more correct out of `n` would be by luck, if the
    true hit rate were `chance` (one-sided binomial test, normal approximation)."""
    if n == 0:
        return 1.0
    sd = math.sqrt(n * chance * (1 - chance))
    z = (hits - 0.5 - n * chance) / sd
    return 0.5 * math.erfc(z / math.sqrt(2))


def scorecard(preds: pd.DataFrame) -> pd.DataFrame:
    """Hit rates on separate weeks (every 5th test day, so weeks don't overlap)."""
    weekly = preds.iloc[::HORIZON]
    up = weekly["up"]
    rows = []
    # The fair yardstick: how often "always up" would have been right in this period
    always_up = up.mean()
    guesses = {
        "Model: simple": (weekly["simple"] > 0.5).astype(float),
        "Model: trees": (weekly["trees"] > 0.5).astype(float),
        "Always guess up": pd.Series(1.0, index=weekly.index),
        "Same as last week": weekly["last_week_up"],
    }
    for name, guess in guesses.items():
        right = (guess == up)
        hits, n = int(right.sum()), len(right)
        rows.append({"Method": name, "Right": hits / n, "Weeks": n,
                     "p vs always-up": _p_value(hits, n, max(always_up, 1 - always_up))
                     if name.startswith("Model") else np.nan})
    rows.append({"Method": "Coin flip", "Right": 0.5, "Weeks": len(weekly), "p vs always-up": np.nan})
    return pd.DataFrame(rows)


def confident(preds: pd.DataFrame, model: str = "simple", edge: float = 0.08) -> dict:
    """How the model did on the weeks it was most sure about (probability
    above 50% + edge or below 50% - edge)."""
    weekly = preds.iloc[::HORIZON]
    sure = weekly[(weekly[model] - 0.5).abs() >= edge]
    if sure.empty:
        return {"n": 0, "right": float("nan"), "share": 0.0}
    right = ((sure[model] > 0.5).astype(float) == sure["up"]).mean()
    return {"n": len(sure), "right": right, "share": len(sure) / len(weekly)}


def rolling_accuracy(preds: pd.DataFrame, window_weeks: int = 52) -> pd.DataFrame:
    """Share of the past year's weeks each method got right, week by week."""
    weekly = preds.iloc[::HORIZON]
    up = weekly["up"]
    right = pd.DataFrame({
        "Model: simple": ((weekly["simple"] > 0.5).astype(float) == up).astype(float),
        "Model: trees": ((weekly["trees"] > 0.5).astype(float) == up).astype(float),
        "Always guess up": (up == 1).astype(float),
    })
    return right.rolling(window_weeks, min_periods=26).mean().dropna() * 100


def this_week(t: pd.DataFrame) -> dict:
    """Today's forecast from models trained on everything with a known answer,
    and what the simple model leans on most (its weights on each fact,
    measured in standard deviations, so they can be compared)."""
    data = t.dropna(subset=list(FEATURES))
    train = data[data["up"].notna()]
    latest = data.iloc[[-1]]
    makers = _models()
    out = {"day": latest.index[0]}
    for name, make in makers.items():
        model = make().fit(train[list(FEATURES)].values, train["up"].values)
        out[name] = float(model.predict_proba(latest[list(FEATURES)].values)[0, 1])
        if name == "simple":
            weights = model[-1].coef_[0]
            scaled = (latest[list(FEATURES)].values[0] - model[0].mean_) / model[0].scale_
            out["drivers"] = sorted(
                [(FEATURES[f], float(w), float(w * v)) for f, w, v in zip(FEATURES, weights, scaled)],
                key=lambda r: -abs(r[2]))
    return out


# ---------------------------------------------------------------------------
# Saved results (made by the daily GitHub job, read by the website)
# ---------------------------------------------------------------------------
from pathlib import Path  # noqa: E402

DATA = Path(__file__).parent / "news_data"
BACKTEST_PATH = DATA / "forecast_backtest.csv"   # walk-forward predictions, every test day
LOG_PATH = DATA / "forecast_log.csv"             # forecasts made live, one per day


def save() -> None:
    """Download fresh data, re-run the walk-forward test, and log today's
    forecast. Run by .github/workflows/forecast.yml every weekday evening."""
    import fetch_prices
    import inventory_events as inv
    import live_prices
    import market_data as md
    import strategies as strat
    for job in (fetch_prices.main, inv.download_inventories, md.main):
        try:
            job()
        except Exception as error:
            print(f"Download failed, using saved data: {error}")

    # The test uses official prices only
    import event_study as es
    official = es.load_prices()
    preds = walk_forward(table(strat.build_features(official)))
    preds.index.name = "date"
    DATA.mkdir(exist_ok=True)
    preds.round(4).to_csv(BACKTEST_PATH)
    print(scorecard(preds).to_string(index=False))

    # Today's forecast uses prices carried to today with futures (official
    # prices arrive a week late, so the newest official day is already old)
    extended, _ = live_prices.extend(official)
    now = this_week(table(strat.build_features(extended)))
    log = load_log()
    day = now["day"].strftime("%Y-%m-%d")
    log = log[log["date"] != day]
    row = {"date": day, "price": round(float(extended.loc[now["day"]]), 2),
           "simple": round(now["simple"], 4), "trees": round(now["trees"], 4)}
    log = pd.concat([log, pd.DataFrame([row])], ignore_index=True).sort_values("date")
    log.to_csv(LOG_PATH, index=False)
    print(f"Logged forecast for {day}: simple {now['simple']:.0%}, trees {now['trees']:.0%}")


def load_backtest() -> pd.DataFrame:
    if not BACKTEST_PATH.exists():
        return pd.DataFrame()
    return pd.read_csv(BACKTEST_PATH, parse_dates=["date"], index_col="date")


def load_log() -> pd.DataFrame:
    if not LOG_PATH.exists():
        return pd.DataFrame(columns=["date", "price", "simple", "trees"])
    return pd.read_csv(LOG_PATH, dtype={"date": str})


def score_log(log: pd.DataFrame, prices: pd.Series) -> pd.DataFrame:
    """Live forecasts whose week has finished, with what actually happened."""
    if log.empty:
        return log
    rows = []
    for _, r in log.iterrows():
        day = pd.Timestamp(r["date"])
        after = prices[prices.index > day]
        if len(after) < HORIZON:
            continue                       # this forecast's week isn't over yet
        later = float(after.iloc[HORIZON - 1])
        up = later > r["price"]
        rows.append({"date": day, "simple": r["simple"], "trees": r["trees"], "up": float(up),
                     "move_pct": (later / r["price"] - 1) * 100})
    return pd.DataFrame(rows)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "save":
        save()
    else:
        import strategies as strat
        t = table(strat.build_features())
        preds = walk_forward(t)
        print(scorecard(preds).to_string(index=False))
        for m in ("simple", "trees"):
            print(m, "when confident:", confident(preds, m))
        print(this_week(t))
