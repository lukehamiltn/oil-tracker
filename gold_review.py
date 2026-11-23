"""
Week in review for gold: how gold moved each week, what made the gold news,
and for each event (a Fed rate decision or a gold news spike) what history
suggested compared with what actually happened.

Used by the gold page and by the Saturday summary that
alerts.py --gold --weekly sends to the gold alert channel.
"""

import html

import pandas as pd
import streamlit as st

import fed_events as fed
import live_prices
import markets as mk
import news
import recap
import ui

MARKET = "GOLD"
HORIZON = recap.HORIZON         # trading days after each event (one week)


def expectation(results: pd.DataFrame, column: str, category: str, date: pd.Timestamp,
                sig: mk.Significance) -> dict:
    """What past events of the same type (strictly before `date`) suggested for
    gold's next week: average move, share that rose, count and verdict."""
    if results.empty:
        return {"n": 0}
    past = results[(results[column] == category) & (results["date"] < date)]
    week = past[f"day_{HORIZON}_pct"].dropna()
    if week.empty:
        return {"n": 0}
    return {"n": len(week), "avg": week.mean(), "up": (week > 0).mean(),
            "verdict": sig.check(MARKET, HORIZON, week)}


def events_between(data: dict, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    """Fed decisions and gold news spikes from start to end (inclusive), each
    with what history suggested and what gold did in the week after."""
    prices, _ = live_prices.extend(data["prices"], MARKET)
    rows = []
    decisions = data["fed"]
    for _, e in decisions[(decisions["date"] >= start) & (decisions["date"] <= end)].iterrows():
        rows.append({"day": e["date"], "kind": "fed", "category": e["decision"],
                     "label": f"Fed: {fed.LABELS[e['decision']].lower()} ({e['description']})",
                     **expectation(data["fed_react"][0], "decision", e["decision"], e["date"], data["sig"])})
    spikes = data["spikes"]
    if not spikes.empty:
        for _, e in spikes[(spikes["date"] >= start) & (spikes["date"] <= end)].iterrows():
            rows.append({"day": e["date"], "kind": "news", "category": e["topic"],
                         "label": news.topic_info(e["topic"]).get("label", e["topic"]) + " (news spike)",
                         **expectation(data["spike_react"][0], "topic", e["topic"], e["date"], data["sig"])})
    if not rows:
        return pd.DataFrame()
    out = pd.DataFrame(rows).sort_values("day")
    moves = [recap.actual_move(prices, day) for day in out["day"]]
    out["actual"] = [m for m, _ in moves]
    out["days"] = [d for _, d in moves]
    out["right_way"] = [
        None if (a is None or d < HORIZON or not n) else bool((a > 0) == (avg > 0))
        for a, d, n, avg in zip(out["actual"], out["days"], out["n"], out.get("avg", pd.Series(0, index=out.index)))]
    return out


def track_record(data: dict, months: int = 12) -> pd.DataFrame:
    """Finished events in the last year where history had something to say
    (a year, not six months: gold has fewer events than gas)."""
    today = pd.Timestamp.now(tz=live_prices.MARKET_TZ).tz_localize(None).normalize()
    events = events_between(data, today - pd.DateOffset(months=months), today)
    if events.empty:
        return events
    return events[events["right_way"].notna()]


def render(data: dict, closes: pd.Series) -> None:
    """The Week in review section. `closes`: recent gold futures closes."""
    st.subheader("Week in review", anchor=False)
    st.caption("How gold moved, what made the gold news, and for each Fed decision or news spike "
               "what history suggested compared with what actually happened.")
    weeks = recap.weeks(8)
    today = pd.Timestamp.now(tz=live_prices.MARKET_TZ).tz_localize(None).normalize()
    labels = {i: f"{m:%b} {m.day}–{f:%b} {f.day}" + (" (this week)" if i == 0 and today <= f else "")
              for i, (m, f) in enumerate(weeks)}
    pick = st.selectbox("Week", list(labels), format_func=labels.get, key="gold_review_week")
    monday, friday = weeks[pick]
    unfinished = today <= friday

    # 1. How gold moved, the real interest rate, and the top story
    cards = []
    move = recap.week_move(closes, monday, friday)
    if move is not None:
        color = "#1d8a5e" if move >= 0 else "#c43a39"
        cards.append(("Gold", f'<span style="color:{color}">{move:+.1f}%</span>',
                      "so far this week" if unfinished else "over the week", None))
    real = data["real_yield"]
    before, during = real[real.index < monday], real[(real.index >= monday) & (real.index <= friday)]
    if len(before) and len(during):
        change = during.iloc[-1] - before.iloc[-1]
        cards.append(("10-year real interest rate", f"{during.iloc[-1]:.2f}%",
                      f"{change:+.2f} points over the week"
                      + (" (rising rates usually weigh on gold)" if change > 0.05 else
                         " (falling rates usually help gold)" if change < -0.05 else ""), None))
    topics = recap.topic_week(data["timelines"], monday, friday)
    if not topics.empty:
        top = topics.iloc[0]
        cards.append(("Most covered gold story", top["label"],
                      f"{top['ratio']:.1f}× its normal share of news · {top['articles']:,} stories", None))
    if cards:
        ui.kpi_row(cards, columns=3)

    if len(topics) > 1:
        st.markdown("**What made the gold news**")
        rows = "".join(
            f'<div class="headline"><span class="flash-title">{html.escape(r.label)}</span>'
            f'<div class="meta">{r.ratio:.1f}× its normal share of worldwide news · '
            f'{r.articles:,} stories</div></div>' for r in topics.head(3).itertuples())
        st.markdown(rows, unsafe_allow_html=True)

    # 2. Events that week, history vs what happened
    events = events_between(data, monday, friday)
    st.markdown("**What happened, and what history suggested**")
    if events.empty:
        st.caption("No Fed rate change or gold news spike that week.")
    else:
        table = pd.DataFrame({
            "Day": events["day"].map(lambda d: ui.day(d, year=False, weekday=True)),
            "Event": events["label"],
            "History said (gold, next week)": [
                f"{e['avg']:+.1f}% average after {e['n']} past · {mk.VERDICTS[e['verdict']][0].lower()}"
                if e["n"] else "no past events" for _, e in events.iterrows()],
            "What happened": [
                "—" if a is None else f"{a:+.1f}%" + ("" if d == HORIZON else f" (after {d} days)")
                for a, d in zip(events["actual"], events["days"])],
            "Right way?": ["—" if r is None or pd.isna(r) else ("Yes" if r else "No") for r in events["right_way"]],
        })
        st.dataframe(table, hide_index=True, width="stretch", key="gold_review_table")
        ui.tip("'History said' is gold's average move in the week after past events of the same type (the "
               "same kind of Fed decision, or a spike in the same news topic), using only events before this "
               "one. 'What happened' is gold's move over the next 5 trading days from the close before the "
               "event. 'Right way?' compares just the direction, once the week is over.", "How to read this")

    # 3. Track record
    record = track_record(data)
    if len(record):
        hits, total = int(record["right_way"].astype(bool).sum()), len(record)
        st.markdown("**Track record**")
        ui.kpi_row([("History pointed the right way", f"{hits} of {total}",
                     f"{hits / total:.0%} of Fed decisions and gold news spikes in the last 12 months",
                     None)], columns=1)
        st.caption("Gold rose in most years since 2005, so history usually says 'up': the record depends a "
                   "lot on whether gold happened to be rising or falling at the time. The averages here "
                   "describe what usually happened; they are not forecasts.")


def weekly_message(data: dict) -> tuple[str, str]:
    """(title, message) summing up the gold week that just finished."""
    monday, friday = recap.weeks(1)[0]
    move = recap.week_move(live_prices.daily_closes(MARKET, span="3mo"), monday, friday)
    title = f"Gold week of {monday:%b} {monday.day}–{friday.day}" + (f": {move:+.1f}%" if move is not None else "")
    lines = []
    topics = recap.topic_week(data["timelines"], monday, friday)
    if not topics.empty:
        lines.append("Most covered: " + ", ".join(
            f"{r.label} ({r.ratio:.1f}x normal)" for r in topics.head(2).itertuples()) + ".")
    events = events_between(data, monday, friday)
    for _, e in events.iterrows() if not events.empty else []:
        said = f"history said {e['avg']:+.1f}%" if e["n"] else "no history"
        got = "" if e["actual"] is None else f", gold {e['actual']:+.1f}% since"
        lines.append(f"{e['day']:%a}: {e['label']} ({said}{got}).")
    record = track_record(data)
    if len(record):
        lines.append(f"Track record (12 months): history pointed the right way "
                     f"{int(record['right_way'].astype(bool).sum())} of {len(record)} times.")
    lines.append("History, not a forecast.")
    return title, "\n".join(lines)


def build(prices: pd.Series, real_yield: pd.Series, timelines: pd.DataFrame) -> dict:
    """Everything the gold page and the alerts measure, from loaded data."""
    import event_study as es
    decisions = fed.build_events(fed.load_fed())
    decisions = decisions[decisions["date"] >= prices.index[0]].reset_index(drop=True)
    spikes = news.all_spikes(timelines) if not timelines.empty else pd.DataFrame()
    return {"prices": prices, "real_yield": real_yield, "fed": decisions,
            "fed_react": es.compute_results(prices, decisions),
            "timelines": timelines, "spikes": spikes,
            "spike_react": es.compute_results(prices, spikes) if not spikes.empty else (pd.DataFrame(), {}),
            # averages shown, but a pattern must also hold on the typical move
            "sig": mk.Significance({MARKET: prices}, center="both")}


def build_data() -> dict:
    """The same data the gold page uses, for the alerts (no Streamlit)."""
    import event_study as es
    import fetch_prices
    import mediacloud_news
    fetch_prices.main()
    try:
        fed.download_fed()
    except Exception as error:
        print(f"Fed download failed, using saved data: {error}")
    return build(es.load_prices(MARKET), es.load_prices("REAL_YIELD"),
                 mediacloud_news.load(mediacloud_news.GOLD_PATH))
