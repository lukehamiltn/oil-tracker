"""
Week in review for natural gas: how gas moved each week, what made the gas
news, and for each event (a weekly storage report or a news spike) what
history suggested compared with what actually happened.

Used by the gas page (News tab) and by the Saturday summary that
alerts.py --gas --weekly sends to the gas alert channel.
"""

import html

import pandas as pd
import streamlit as st

import gas_storage as gs
import live_prices
import markets as mk
import news
import recap
import ui

MARKET = "NATGAS"
HORIZON = recap.HORIZON         # trading days after each event (one week)


def expectation(results: pd.DataFrame, column: str, category: str, date: pd.Timestamp,
                sig: mk.Significance) -> dict:
    """What past events of the same type (strictly before `date`) suggested for
    Henry Hub's next week: average move, share that rose, count and verdict."""
    if results.empty:
        return {"n": 0}
    past = results[(results[column] == category) & (results["date"] < date)]
    week = past[f"day_{HORIZON}_pct"].dropna()
    if week.empty:
        return {"n": 0}
    return {"n": len(week), "avg": week.mean(), "up": (week > 0).mean(),
            "verdict": sig.check(MARKET, HORIZON, week)}


def events_between(data: dict, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    """Storage reports and gas news spikes from start to end (inclusive), each
    with what history suggested and what Henry Hub did in the week after."""
    prices, _ = live_prices.extend(data["prices"], MARKET)
    rows = []
    storage = data["storage"]
    for _, e in storage[(storage["date"] >= start) & (storage["date"] <= end)].iterrows():
        rows.append({"day": e["date"], "kind": "storage", "category": e["category"],
                     "label": f"Storage report: {gs.LABELS[e['category']].lower()} "
                              f"({e['change_bcf']:+.0f} Bcf vs {e['normal_bcf']:+.0f} normal)",
                     **expectation(data["storage_react"][0], "category", e["category"], e["date"], data["sig"])})
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


def track_record(data: dict, months: int = 6) -> pd.DataFrame:
    """Finished events in the last few months where history had something to say."""
    today = pd.Timestamp.now(tz=live_prices.MARKET_TZ).tz_localize(None).normalize()
    events = events_between(data, today - pd.DateOffset(months=months), today)
    if events.empty:
        return events
    return events[events["right_way"].notna()]


def render(data: dict, closes: pd.Series) -> None:
    """The Week in review section. `closes`: recent Henry Hub futures closes."""
    st.subheader("Week in review", anchor=False)
    st.caption("How gas moved, what made the gas news, and for each storage report or news spike "
               "what history suggested compared with what actually happened.")
    weeks = recap.weeks(8)
    today = pd.Timestamp.now(tz=live_prices.MARKET_TZ).tz_localize(None).normalize()
    labels = {i: f"{m:%b} {m.day}–{f:%b} {f.day}" + (" (this week)" if i == 0 and today <= f else "")
              for i, (m, f) in enumerate(weeks)}
    pick = st.selectbox("Week", list(labels), format_func=labels.get, key="gas_review_week")
    monday, friday = weeks[pick]
    unfinished = today <= friday

    # 1. How gas moved, and the storage report that week
    cards = []
    move = recap.week_move(closes, monday, friday)
    if move is not None:
        color = "#1d8a5e" if move >= 0 else "#c43a39"
        cards.append(("Henry Hub gas", f'<span style="color:{color}">{move:+.1f}%</span>',
                      "so far this week" if unfinished else "over the week", None))
    storage = data["storage"]
    report = storage[(storage["date"] >= monday) & (storage["date"] <= friday)]
    if len(report):
        r = report.iloc[-1]
        cards.append(("Storage report", gs.LABELS[r["category"]],
                      f"{ui.day(r['date'], year=False, weekday=True)}: {r['change_bcf']:+.0f} Bcf vs "
                      f"{r['normal_bcf']:+.0f} normal (surprise {r['surprise_bcf']:+.0f})", None))
    topics = recap.topic_week(data["timelines"], monday, friday)
    if not topics.empty:
        top = topics.iloc[0]
        cards.append(("Most covered gas story", top["label"],
                      f"{top['ratio']:.1f}× its normal share of news · {top['articles']:,} stories", None))
    if cards:
        ui.kpi_row(cards, columns=3)

    if len(topics) > 1:
        st.markdown("**What made the gas news**")
        rows = "".join(
            f'<div class="headline"><span class="flash-title">{html.escape(r.label)}</span>'
            f'<div class="meta">{r.ratio:.1f}× its normal share of worldwide news · '
            f'{r.articles:,} stories</div></div>' for r in topics.head(3).itertuples())
        st.markdown(rows, unsafe_allow_html=True)

    # 2. Events that week, history vs what happened
    events = events_between(data, monday, friday)
    st.markdown("**What happened, and what history suggested**")
    if events.empty:
        st.caption("No storage report or gas news spike that week.")
    else:
        table = pd.DataFrame({
            "Day": events["day"].map(lambda d: ui.day(d, year=False, weekday=True)),
            "Event": events["label"],
            "History said (Henry Hub, next week)": [
                f"{e['avg']:+.1f}% avg after {e['n']} past · {mk.VERDICTS[e['verdict']][0].lower()}"
                if e["n"] else "no past events" for _, e in events.iterrows()],
            "What happened": [
                "—" if a is None else f"{a:+.1f}%" + ("" if d == HORIZON else f" (after {d} days)")
                for a, d in zip(events["actual"], events["days"])],
            "Right way?": ["—" if r is None or pd.isna(r) else ("Yes" if r else "No") for r in events["right_way"]],
        })
        st.dataframe(table, hide_index=True, width="stretch", key="gas_review_table")
        ui.tip("'History said' is the average Henry Hub move in the week after past events of the same "
               "type (the same size of storage surprise, or a spike in the same news topic), using only "
               "events before this one. 'What happened' is Henry Hub's move over the next 5 trading days "
               "from the close before the event. 'Right way?' compares just the direction, once the week "
               "is over.", "How to read this")

    # 3. Track record
    record = track_record(data)
    if len(record):
        hits, total = int(record["right_way"].astype(bool).sum()), len(record)
        st.markdown("**Track record**")
        ui.kpi_row([("History pointed the right way", f"{hits} of {total}",
                     f"{hits / total:.0%} of storage reports and gas news spikes in the last 6 months",
                     None)], columns=1)
        st.caption("Gas is driven mostly by the weather, so a storage report or a news story often "
                   "gets swamped by the next forecast. The averages here describe what usually "
                   "happened; they are not forecasts.")


def weekly_message(data: dict) -> tuple[str, str]:
    """(title, message) summing up the gas week that just finished."""
    monday, friday = recap.weeks(1)[0]
    move = recap.week_move(live_prices.daily_closes(MARKET, span="3mo"), monday, friday)
    title = f"Gas week of {monday:%b} {monday.day}–{friday.day}" + (f": Henry Hub {move:+.1f}%" if move is not None else "")
    lines = []
    topics = recap.topic_week(data["timelines"], monday, friday)
    if not topics.empty:
        lines.append("Most covered: " + ", ".join(
            f"{r.label} ({r.ratio:.1f}x normal)" for r in topics.head(2).itertuples()) + ".")
    events = events_between(data, monday, friday)
    for _, e in events.iterrows() if not events.empty else []:
        said = f"history said {e['avg']:+.1f}%" if e["n"] else "no history"
        got = "" if e["actual"] is None else f", Henry Hub {e['actual']:+.1f}% since"
        lines.append(f"{e['day']:%a}: {e['label']} ({said}{got}).")
    record = track_record(data)
    if len(record):
        lines.append(f"Track record (6 months): history pointed the right way "
                     f"{int(record['right_way'].astype(bool).sum())} of {len(record)} times.")
    lines.append("History, not a forecast.")
    return title, "\n".join(lines)


def build_data() -> dict:
    """The same data the gas page uses, for the weekly message (no Streamlit)."""
    import event_study as es
    import fetch_prices
    import mediacloud_news
    fetch_prices.main()
    prices = es.load_prices(MARKET)
    try:
        gs.download_storage()
    except Exception as error:
        print(f"Storage download failed, using saved data: {error}")
    storage = gs.build_events(gs.load_storage())
    timelines = mediacloud_news.load(mediacloud_news.GAS_PATH)
    spikes = news.all_spikes(timelines) if not timelines.empty else pd.DataFrame()
    return {"prices": prices, "storage": storage, "storage_react": es.compute_results(prices, storage),
            "timelines": timelines, "spikes": spikes,
            "spike_react": es.compute_results(prices, spikes) if not spikes.empty else (pd.DataFrame(), {}),
            "sig": mk.Significance({MARKET: prices})}
