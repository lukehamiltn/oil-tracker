"""
Trading rules, and the daily table of facts they are allowed to use.

THE GOLDEN RULE: on any given day, a strategy may only use information that
was actually public by that day's close. Each data source below is shifted
to the day it became available:
  - EIA inventory report: released Wednesday 10:30am ET -> usable that day's close
  - CFTC positioning: as of Tuesday, released Friday 3:30pm ET (after oil
    futures close) -> usable from the following Monday's close
  - Dollar index: published weekly by the Fed -> treated as usable 7 days later
  - News spikes (GDELT): a day's coverage is complete at midnight UTC (7pm ET,
    after the close) -> usable from the NEXT trading day's close

Every strategy returns a "position" for each day: 1 = own oil, 0 = in cash.
The position chosen at a day's close earns the NEXT day's price change.

The rules and their settings were fixed BEFORE looking at the 2017+ results,
so 2017+ is a fair test. Don't tune them by peeking at the 2017+ numbers.
"""

import pandas as pd

import event_study as es
import inventory_events as inv
import market_data as md
import news

# News topics that threaten oil SUPPLY, where the textbook reaction is a price
# rise. Chosen on that reasoning, not by picking the best past results.
SUPPLY_TOPICS = ["shipping", "infrastructure", "middle_east", "sanctions"]


def _as_of(values: pd.Series, known_from: pd.DatetimeIndex,
           days: pd.DatetimeIndex) -> pd.Series:
    """For each trading day, the latest value that was public by then."""
    table = pd.DataFrame({"known_from": known_from, "value": values.values})
    table = table.dropna().sort_values("known_from")
    merged = pd.merge_asof(pd.DataFrame({"day": days}), table,
                           left_on="day", right_on="known_from")
    return pd.Series(merged["value"].values, index=days)


def dollar_trend(dollar: pd.Series, days: pd.DatetimeIndex) -> pd.Series:
    """% the dollar index is above (+) or below (-) its 50-day average, as it
    was publicly known on each of `days` (the Fed publishes weekly, so each
    value is treated as known 7 days after its date). Used by the backtest
    AND the live bot, so both follow exactly the same rule."""
    trend = (dollar / dollar.rolling(50).mean() - 1) * 100
    return _as_of(trend, dollar.index + pd.Timedelta(days=7), days)


def trend_gap(prices: pd.Series) -> pd.Series:
    """% the price is above (+) or below (-) its 200-day average.
    Shared by the backtest and the live bot."""
    return (prices / prices.rolling(200).mean() - 1) * 100


def build_features(prices: pd.Series | None = None) -> pd.DataFrame:
    """One row per trading day with everything a strategy may look at."""
    prices = es.load_prices() if prices is None else prices
    days = prices.index
    f = pd.DataFrame(index=days)
    f["price"] = prices
    f["sma200"] = prices.rolling(200).mean()
    f["trend_gap_pct"] = trend_gap(prices)

    # --- EIA inventories ---------------------------------------------------
    stocks = inv.load_inventories()
    events = inv.build_events(stocks)
    # Category of a report, placed on the first trading day on/after release
    report_day = days[days.searchsorted(events["date"].clip(upper=days[-1]))]
    category = pd.Series(events["category"].values, index=report_day)
    category = category[~category.index.duplicated(keep="last")]
    f["inv_report"] = category.reindex(days)  # blank on non-report days

    # Stock LEVEL vs the normal level for that week (previous 5 years)
    level = stocks / 1000
    week = level.index.isocalendar().week.values
    normal = level.groupby(week).transform(
        lambda s: s.shift(1).rolling(5, min_periods=3).mean())
    level_gap = (level / normal - 1) * 100
    f["inv_vs_normal_pct"] = _as_of(level_gap, inv.release_dates(level.index), days)

    # --- CFTC positioning --------------------------------------------------
    cot = md.load_cot()
    net = (cot["mm_long"] - cot["mm_short"]) / cot["open_interest"] * 100
    # Where today's positioning sits within the last 3 years (0 = most
    # bearish, 1 = most bullish). Only uses past reports.
    pct = net.rolling(156, min_periods=52).apply(
        lambda w: (w < w[-1]).mean(), raw=True)
    known = cot["report_date"] + pd.Timedelta(days=6)  # following Monday
    f["mm_net_pct_oi"] = _as_of(net, known, days)
    f["mm_positioning_rank"] = _as_of(pct, known, days)

    # --- Dollar ------------------------------------------------------------
    f["dollar_vs_50d_pct"] = dollar_trend(md.load_dollar(), days)

    # --- News spikes about supply threats (GDELT, from 2017) -----------------
    f["supply_news"] = None
    spikes = news.all_spikes(news.load_timelines())
    spikes = spikes[spikes["topic"].isin(SUPPLY_TOPICS)]
    if len(spikes):
        # first trading day strictly AFTER the spike day (its coverage is only
        # complete after that day's close)
        usable = days.searchsorted(spikes["spike_day"], side="right")
        ok = usable < len(days)
        topic = pd.Series(spikes["topic"].values[ok], index=days[usable[ok]])
        topic = topic[~topic.index.duplicated(keep="last")]
        f["supply_news"] = topic.reindex(days)
    f.attrs["news_start"] = news.load_timelines()["date"].min()
    return f


# ---------------------------------------------------------------------------
# The strategies. Each takes the features table, returns a position series.
# ---------------------------------------------------------------------------
def buy_and_hold(f: pd.DataFrame) -> pd.Series:
    """Benchmark: always own oil."""
    return pd.Series(1.0, index=f.index)


def trend_200d(f: pd.DataFrame) -> pd.Series:
    """Own oil only while its price is above its 200-day average."""
    gap = f["trend_gap_pct"]
    return (gap > 0).astype(float).where(gap.notna())


def big_build_rebound(f: pd.DataFrame, hold_days: int = 4) -> pd.Series:
    """After a much-bigger-than-normal inventory build, buy at that day's
    close and hold for 4 trading days (testing whether the market overreacts)."""
    signal = (f["inv_report"] == "big_build").astype(float)
    return signal.rolling(hold_days, min_periods=1).max()


def tight_inventories(f: pd.DataFrame) -> pd.Series:
    """Own oil while U.S. crude stocks are below normal for the time of year."""
    gap = f["inv_vs_normal_pct"]
    return (gap < 0).astype(float).where(gap.notna())


def crowded_short(f: pd.DataFrame) -> pd.Series:
    """Contrarian: own oil when hedge funds are more bearish than they've
    been 75% of the time in the last 3 years."""
    rank = f["mm_positioning_rank"]
    return (rank <= 0.25).astype(float).where(rank.notna())


def weak_dollar(f: pd.DataFrame) -> pd.Series:
    """Own oil while the dollar is below its 50-day average."""
    d = f["dollar_vs_50d_pct"]
    return (d < 0).astype(float).where(d.notna())


def supply_news(f: pd.DataFrame, hold_days: int = 5) -> pd.Series:
    """After a news spike about a supply threat (tanker or facility attacks,
    Middle East conflict, sanctions), buy at the next close and hold for a
    week (5 trading days). News history starts in 2017, so this rule has no
    'build' period: everything it shows is out-of-sample."""
    signal = f["supply_news"].notna().astype(float)
    position = signal.rolling(hold_days, min_periods=1).max()
    start = f.attrs.get("news_start")
    return position.where(f.index >= start) if start is not None else position


STRATEGIES = {
    "buy_and_hold": ("Buy and hold (benchmark)", buy_and_hold),
    "trend_200d": ("Trend: above 200-day average", trend_200d),
    "big_build_rebound": ("Big inventory build rebound", big_build_rebound),
    "tight_inventories": ("Inventories below normal", tight_inventories),
    "crowded_short": ("Hedge funds crowded short", crowded_short),
    "weak_dollar": ("Weak dollar", weak_dollar),
    "supply_news": ("Supply-scare news", supply_news),
}
