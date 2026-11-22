"""Research > Forecast model: can a small model predict next week's oil price,
and how often has it been right? The calculations are in forecast.py; the
walk-forward test is re-run every weekday evening by a GitHub job and saved,
so this page only reads the results."""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import forecast as fc
import ui

GREEN, RED = "#1d8a5e", "#c43a39"


@st.cache_data(ttl=60 * 60, show_spinner=False)
def _backtest(version: float) -> pd.DataFrame:
    return fc.load_backtest()


@st.cache_data(ttl=60 * 60, show_spinner=False)
def _now(_features: pd.DataFrame, version: str) -> dict:
    return fc.this_week(fc.table(_features))


def _pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def render(now_features: pd.DataFrame, prices: pd.Series) -> None:
    st.subheader("Can a model predict oil?", anchor=False)
    st.markdown(
        "A small machine-learning model reads the same facts as the strategy lab (Brent's trend "
        "and momentum, how much it's swinging, U.S. crude stocks, hedge-fund positioning, the "
        "dollar and supply-scare news) and guesses whether **Brent will be higher one week "
        "later**. Then we check how often it's right, on weeks it had **never seen**.")

    path = fc.BACKTEST_PATH
    preds = _backtest(path.stat().st_mtime if path.exists() else 0)
    if preds.empty:
        st.info("The model's track record isn't ready yet. It's re-tested every weekday evening.")
        return

    card = fc.scorecard(preds).set_index("Method")
    simple, trees = card.loc["Model: simple"], card.loc["Model: trees"]
    always = card.loc["Always guess up", "Right"]
    best_model = max(simple["Right"], trees["Right"])
    beats = best_model > always and min(simple["p vs always-up"], trees["p vs always-up"]) < 0.05
    verdict = ("It beats simple guessing" if beats else "No real skill (yet)")
    verdict_note = ("better than always guessing up, unlikely to be luck" if beats else
                    f"always guessing \"up\" did better: {_pct(always)}")
    first = preds.index[0]
    ui.kpi_row([
        ("Model right (simple)", _pct(simple["Right"]), f"of {int(simple['Weeks'])} weeks since {first:%Y}", None),
        ("Model right (trees)", _pct(trees["Right"]), "a fancier model, same facts", None),
        ("Always guess \"up\"", _pct(always), "the bar to beat", None),
        ("Verdict", verdict, verdict_note, GREEN if beats else None),
    ])
    ui.tip("Every month the model is retrained on everything known up to then, and then predicts "
           "the next month, which it hasn't seen: the way it would really have worked. Weeks are "
           "counted separately (they don't overlap), so a lucky streak can't be counted twice. "
           "'Always guess up' is the fair yardstick because oil rose in slightly more weeks than it fell.",
           "How the test works")

    # This week's forecast ----------------------------------------------------------
    st.write("")
    st.markdown("**This week's forecast**")
    now = _now(now_features, f"{now_features.index[-1]}-{len(now_features)}")
    p = now["simple"]
    lean = "higher" if p >= 0.5 else "lower"
    sure = abs(p - 0.5)
    strength = "barely leans" if sure < 0.04 else "leans" if sure < 0.1 else "is fairly sure"
    target = now["day"] + pd.tseries.offsets.BDay(fc.HORIZON)
    ui.kpi_row([
        ("Chance Brent is higher by " + ui.day(target, year=False), _pct(p),
         f"the model {strength} {lean} (trees model: {_pct(now['trees'])})", None),
        ("Should you trade on it?", "No", "its track record above is no better than guessing", None),
    ], columns=2)

    drivers = now.get("drivers", [])[:5]
    if drivers:
        st.markdown("**What's pushing this week's guess**")
        fig = go.Figure(go.Bar(
            x=[d[2] for d in drivers][::-1], y=[d[0] for d in drivers][::-1], orientation="h",
            marker_color=[GREEN if d[2] > 0 else RED for d in drivers][::-1],
            hovertemplate="%{y}: %{x:+.2f}<extra></extra>"))
        ui.base_layout(fig, 260, xaxis_title="← towards lower · towards higher →", showlegend=False)
        st.plotly_chart(fig, width="stretch", config=ui.CHART_CONFIG, key="forecast_drivers")
        ui.tip("How much each fact moves the simple model's guess today: its learned weight times how "
               "unusual today's reading is. Green pushes towards 'higher', red towards 'lower'. Small "
               "bars all round mean the model doesn't see anything unusual.", "How to read this")

    # Track record over time --------------------------------------------------------
    st.write("")
    st.markdown("**Right or wrong, year by year**")
    rolling = fc.rolling_accuracy(preds)
    fig = go.Figure()
    styles = {"Model: simple": ("#1f3a5f", 2.4), "Model: trees": ("#eb6834", 1.6), "Always guess up": ("#9a988f", 1.6)}
    for name, (color, width) in styles.items():
        fig.add_trace(go.Scatter(x=rolling.index, y=rolling[name], name=name, mode="lines",
                                 line=dict(color=color, width=width, dash="dot" if name == "Always guess up" else None),
                                 hovertemplate=f"{name}: %{{y:.0f}}%<extra></extra>"))
    fig.add_hline(y=50, line_color="#c3c2b7", line_width=1, annotation_text="coin flip",
                  annotation_position="bottom right", annotation_font_size=11)
    ui.base_layout(fig, 340, hovermode="x unified", yaxis_ticksuffix="%", yaxis_title="Weeks right (past year)")
    st.plotly_chart(fig, width="stretch", config=ui.CHART_CONFIG, key="forecast_rolling")
    ui.tip("Each point is the share of the previous 52 weeks the method got right. The model drifts "
           "above and below 50% the way a coin would: good years and bad years come and go without "
           "a lasting edge.", "How to read this")

    sure_simple = fc.confident(preds, "simple")
    if sure_simple["n"]:
        st.caption(f"On the {sure_simple['n']} weeks the simple model was most sure (below 42% or above 58%), "
                   f"it was right {_pct(sure_simple['right'])} of the time.")

    # Live record -------------------------------------------------------------------
    st.write("")
    st.markdown("**Live record**")
    live = fc.score_log(fc.load_log(), prices)
    if len(live) < 4:
        started = fc.load_log()["date"].min() if len(fc.load_log()) else None
        st.caption("Since " + (ui.day(pd.Timestamp(started)) if started else "now") + ", the model's forecast is "
                   "saved every weekday before anyone knows the answer, then scored a week later. Once a "
                   "few weeks have passed, its real-time record will show here: the hardest test of all.")
    else:
        hits = int(((live["simple"] > 0.5).astype(float) == live["up"]).sum())
        st.caption(f"Forecasts saved in real time and scored a week later: right {hits} of {len(live)} "
                   f"({hits / len(live) * 100:.0f}%).")

    ui.tip("Prices react to news nobody can see coming (a tanker attack, an OPEC surprise), and anything "
           "that reliably predicted next week would be traded away by professionals almost at once. So a "
           "model with no edge is the expected, honest result, which is why this site shows what usually "
           "happened after events rather than promising where prices will go.",
           "Why is it so hard?")
