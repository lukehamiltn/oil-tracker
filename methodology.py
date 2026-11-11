"""
The Methodology window: how the site gets its numbers, in plain words.
Opened from the button in the header and the link in the footer.
"""

import streamlit as st

import backtest as bt
import markets as mk
import news


def overview() -> None:
    st.markdown("""
Oil Tracker takes what's in the oil news today, finds the moments in the past that
looked most like it, and shows what oil and related markets did next.

Everything on the site is measured the same way: **start from the closing price on the
last trading day before an event, then look at the move one day, one week (5 trading
days) and one month (20 trading days) later.** Averages are then checked against luck
(see *Is it real?*).

Prices at the top of the page are front-month futures, about 10 minutes delayed. All
charts and research use official daily spot prices, which are published about a week
late, so the most recent few days are not yet part of the history.
""")


def news_method() -> None:
    st.markdown(f"""
**Two news sources**

- *Worldwide news* comes from Media Cloud, an open news archive run by universities.
  For each topic we save how many stories matched each day, across about 1,800
  English-language news sites, since 2015.
- *Market news* (Benzinga, via Alpaca) covers oil funds and oil companies since 2015.
  Every story is saved with the site, which is why headlines and searches are instant.

**Today's headlines** are real articles read from the public news feeds of about 30
publishers: energy press (OilPrice.com, Rigzone, World Oil, CNBC Energy, the U.S. EIA),
shipping news (gCaptain, Splash247, Hellenic Shipping News) and world and Middle East
news (Al Jazeera, BBC, The Guardian, DW, The National, Middle East Eye and others). Only
stories that mention oil, fuel, refineries, tankers, Hormuz and so on are kept, at most
three per publisher in the list. Each headline links to the full article on the
publisher's site. Benzinga's one-line newswire flashes are listed separately, linked to
matching coverage from those publishers when there is some.

**Topics** are fixed news searches (for example, attacks on tankers). For each day we
measure the topic's share of *all* news, so growth in overall coverage doesn't distort
the comparison.

**A news spike** is a day when a topic got at least {news.SPIKE_RATIO:.0f}× its normal
share of coverage (normal = the median of the previous {news.BASELINE_DAYS} days), with
at least {news.MIN_ARTICLES} articles, and among that topic's busiest 10% of days over
the previous year. Spikes have to be {news.COOLDOWN_DAYS} or more days apart, hurricane
spikes only count from June to November, and days when the archive collected unusually
few stories are skipped. The market news feed uses the same rules with a lower article
minimum, since it carries dozens of oil stories a day rather than thousands.

**Timing.** Reactions are measured from the close one business day *before* the spike,
so a story that broke the evening before isn't missed.

**Like this before** turns each headline into a list of word weights (TF-IDF), where
rare words such as places and company names count most, and compares it with every
past oil story. Matches must be at least a week apart and at least two weeks older
than the story, so one event isn't counted twice.

**Tags** on headlines are assigned by keyword, so a few stories land in the wrong topic.
""")


def reactions_method() -> None:
    st.markdown(f"""
**Several markets.** Every event is measured the same way in Brent, WTI, gasoline,
heating oil, natural gas, energy stocks (XLE) and the U.S. dollar. Markets move by very
different amounts (natural gas swings far more than the dollar), so colours compare
each move with that market's own typical move. Windows that include a zero or negative
price (WTI in April 2020) are left out of that market.

**EIA inventory surprises** are the week's change in U.S. crude stocks minus the average
change for the same week over the previous five years. Analyst forecasts would be
better, but they aren't freely available.

**OPEC+ decisions** come from a hand-checked list of major decisions since 1999.
**Fed decisions** are every change in the Fed's target rate since 1990, measured from
two business days before the change took effect.

**Market conditions** compares today's readings with every trading day since 2007.
"Most similar days" compares all six indicators at once, each scaled to its normal range.

**Strategy lab** backtests only use information that was public at the time, charge
{bt.COST_PCT:.2f}% per trade, and were designed on 2007–2016, then tested on 2017 onwards.
The *supply-scare news* rule buys at the close the day **after** a news spike about tanker
or facility attacks, Middle East conflict or sanctions (a day's news count is only complete
after the market has closed) and holds for a week. News history starts in 2015, so its
design period only covers 2015–2016.

**Spike alerts.** Every 3 hours a job checks each topic's coverage the same way as the
cards on the News tab. When a topic reaches "Spiking" it sends a push notification
(through the free ntfy app) with the latest headline and what happened after past
spikes. Each spike alerts once.

**Trading bots** trade fake money in an Alpaca paper account at real prices, checking
once each weekday in the two hours before the 4pm ET close.
""")


def is_it_real() -> None:
    st.markdown(f"""
Every average on the site is checked against luck. If an event type has 20 past cases,
we pick 20 *random* days from the same market's history, thousands of times over, and
count how often their average move is as far from normal as the events' average was.

| Label | What it means |
|---|---|
| **Strong pattern** ●● | Random days do this less than 2% of the time |
| **Possible pattern** ● | Less than 10% of the time |
| **Could be noise** | Random days do this often, so the average may be luck |
| **Too few events** | Fewer than {mk.MIN_EVENTS} cases, so we don't judge |

We tested the check itself on random dates: it called them "strong" 1.5% of the time,
close to the 2% you would expect.

Because the site checks hundreds of averages, a few "strong" labels will still be
flukes (about 1 in 50 of the checks that are really noise). A pattern is more convincing
when it shows up across related markets, for example crude *and* gasoline.
""")


def limits() -> None:
    st.markdown("""
- **Markets react to surprises.** News that was widely expected may barely move prices.
- **Small samples.** Some categories have only a handful of events, and one extreme
  case (March 2020, for example) can dominate an average.
- **Other things happen at the same time.** A move after an event isn't caused only by
  that event.
- **The past is a guide, not a promise.** Nothing here is investment advice.
""")


def sources() -> None:
    st.markdown("""
| Data | Source | Since |
|---|---|---|
| Brent, WTI, gasoline, heating oil, natural gas (daily spot) | U.S. EIA via FRED | 1987–1997 |
| Live Brent and WTI futures | Yahoo Finance (about 10 min delayed) | today |
| Energy stocks (XLE, dividends included) | Alpaca | 2016 |
| U.S. dollar (broad index) | Federal Reserve via FRED | 2006 |
| Fed target rate | Federal Reserve via FRED | 1990 |
| Weekly U.S. crude stocks | U.S. EIA | 2006 |
| Hedge-fund positioning (managed money, NYMEX WTI) | CFTC Commitments of Traders | 2006 |
| Worldwide news coverage | Media Cloud | 2015 |
| Market news headlines | Benzinga via Alpaca | 2015 |
| OPEC+ decisions | Hand-checked list | 1999 |
""")


@st.dialog("Methodology", width="large")
def show() -> None:
    sections = st.tabs(["Overview", "News", "Measuring reactions", "Is it real?",
                        "Limits", "Data sources"])
    for tab, section in zip(sections, [overview, news_method, reactions_method,
                                       is_it_real, limits, sources]):
        with tab:
            section()
