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

**"Spiking" on today's topic cards** means the last 3 days averaged at least
{news.SPIKE_RATIO:.0f}× normal coverage *and* had at least
{news.SOURCES['world']['spike_articles']} articles between them. A high ratio on fewer
articles shows as "Elevated". When one day carries most of the 3 days' articles, the card
says so ("Mostly Nov 11"), since a one-day burst is weaker than a sustained story.

**Articles vs distinct stories.** Media Cloud counts every page that matches, so one
wire story copied onto 14 sites counts 14 times, and a page that mentions OPEC in
passing counts too. Every 3 hours we also fetch the articles themselves, drop copies,
and keep only those whose headline is about the topic. Cards show both numbers, and
"Spiking" also needs at least {news.SPIKE_DISTINCT} distinct stories. The "× normal"
ratio still uses the full counts, because that is what our history since 2015 is
measured in (copies inflate past days about as much as today).

**OPEC monthly report days.** Around the middle of each month OPEC publishes its
Monthly Oil Market Report (output figures and demand forecasts). It brings a burst of
OPEC headlines without any policy decision, so cards and alerts label those bursts.
Dates come from OPEC's published schedule.

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

**Strategy lab** (Research tab) backtests only use information that was public at the time, charge
{bt.COST_PCT:.2f}% per trade, and were designed on 2007–2016, then tested on 2017 onwards.
The *supply-scare news* rule buys at the close the day **after** a news spike about tanker
or facility attacks, Middle East conflict or sanctions (a day's news count is only complete
after the market has closed) and holds for a week. News history starts in 2015, so its
design period only covers 2015–2016.

**Spike alerts.** Every 3 hours a job checks each topic's coverage the same way as the
cards on the News tab. When a topic reaches "Spiking" it sends a push notification
(through the free ntfy app) with the latest headline and what happened after past
spikes. Each spike alerts once.

**Forecast model** (Research tab) is a small machine-learning model (logistic regression,
plus gradient-boosted trees for comparison) that estimates the chance Brent is higher a week
later, from the same facts as the strategy lab. It's tested walk-forward: retrained every month
on what was known then, scored on the following month, and compared with always guessing "up".

**Trading bots** (Research tab) trade fake money in an Alpaca paper account at real prices, checking
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

A second check guards against a few extreme days: the same test is run on the
*typical* (median) move, and a pattern has to pass both. (A handful of crash-era
events, such as the Fed's emergency cuts in 2008 and 2020, can drag an average a
long way while the typical event did little.) The natural gas site judges typical
moves only, because spot gas has rare huge spikes on very cold days.

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


# ---------------------------------------------------------------------------
# The natural gas and gold sites. Their news tools and statistics work like the
# oil site's; these sections say where they differ.
# ---------------------------------------------------------------------------
def _shared_news(word: str, archive: str) -> str:
    return f"""
**Topics** are fixed searches of worldwide news (Media Cloud, about 1,600 English-language
sites, since 2015). For each day we measure the topic's share of *all* news, so growth in
overall coverage doesn't distort the comparison.

**A news spike** is a day when a topic got at least {news.SPIKE_RATIO:.0f}× its normal share
of coverage (normal = the median of the previous {news.BASELINE_DAYS} days), with enough
articles, and among that topic's busiest 10% of days over the previous year. Spikes have
to be {news.COOLDOWN_DAYS} or more days apart. Click any spike's dot on a chart to see the
biggest stories that day (one copy of each, ranked by how many sites ran it) and what
{word} did next.

**"Spiking" on today's topic cards** means the last 3 days averaged at least
{news.SPIKE_RATIO:.0f}× normal coverage on enough articles; a high ratio on few articles
shows as "Elevated".

**Timing.** Reactions are measured from the close one business day *before* the spike, so a
story that broke the evening before isn't missed.

**Headlines** come from about 30 publishers' public news feeds plus the market newswire
(Benzinga, via Alpaca), keeping stories that mention {word}. {archive}

**Storylines** are big stories that come back in waves. A wave is a stretch of at least 5
days when the storyline's coverage ran at 2.5× its normal level for the past year.
"""


def gas_overview() -> None:
    st.markdown("""
The Natural Gas Tracker takes what's in the gas news today, finds the moments in the past
that looked most like it, and shows what U.S. natural gas prices did next.

Everything is measured the same way: **start from the closing price on the last trading
day before an event, then look at the move one day, one week (5 trading days) and one
month (20 trading days) later.**

**Typical, not average.** The daily Henry Hub spot price has rare, enormous spikes on very
cold days (it rose 380% in a week in January 2024). One of those would swamp an average of
ten events, so the gas site shows the **typical (median) move**: half the events were
followed by more, half by less.

The price at the top of the page is front-month NYMEX futures, about 10 minutes delayed.
Charts use the official daily spot price, which is published about a week late.
""")


def gas_news() -> None:
    st.markdown(_shared_news("Henry Hub", "**Like this before** compares a headline's wording "
                             "(rare words such as places and company names count most) with every "
                             "past gas story in our archive since 2015."))


def gas_reactions() -> None:
    st.markdown("""
**Storage reports.** Every Thursday (later in holiday weeks) the U.S. EIA reports how much gas
is stored in the Lower 48 states. A report's **surprise** is that week's change minus the
average change for the same week over the previous five years (analyst forecasts would be
better, but they aren't freely available). Surprises are sorted into five groups of about a
fifth of reports each: within 7 Bcf of normal is "about normal", more than 27 Bcf is "much
tighter" or "much looser". Reports since 2015 are analysed.

**Weather.** Heating and cooling degree days for 14 big U.S. cities, weighted by population,
from the Open-Meteo forecast, compared with each date's 2015–2024 average.

**Market conditions** compares today's readings (trend, momentum, volatility, storage against
the 5-year average, and the price against a year ago) with every past day, and finds the
days most like today.

**Strategy lab and forecast model:** not offered for gas. Back-tested trades would have to
buy and sell at the daily spot price, which nobody can actually trade, and its cold-day
spikes would make any rule look far better or worse than it could really have done.
""")


def gas_sources() -> None:
    st.markdown("""
| Data | Source | Since |
|---|---|---|
| Henry Hub (daily spot) | U.S. EIA via FRED | 1997 |
| Live Henry Hub futures and futures curve | Yahoo Finance (about 10 min delayed) | today |
| Weekly gas storage (Lower 48) | U.S. EIA | 2010 |
| Weather forecast and normals | Open-Meteo (CC BY 4.0) | 2015 |
| Worldwide news coverage | Media Cloud | 2015 |
| Market news headlines | Benzinga via Alpaca, and publishers' news feeds | 2015 |
""")


@st.dialog("Methodology", width="large")
def show_gas() -> None:
    sections = st.tabs(["Overview", "News", "Measuring reactions", "Is it real?", "Limits", "Data sources"])
    for tab, section in zip(sections, [gas_overview, gas_news, gas_reactions, is_it_real, limits, gas_sources]):
        with tab:
            section()


def gold_overview() -> None:
    st.markdown("""
The Gold Tracker takes what's in the gold news today, finds the moments in the past that
looked most like it, and shows what gold did next.

Everything is measured the same way: **start from the closing price on the last trading day
before an event, then look at the move one day, one week (5 trading days) and one month (20
trading days) later.** Averages are then checked against luck (see *Is it real?*).

**Gold's price history** is worked out from the daily closes of GLD, the biggest gold fund
(it holds gold bars in a vault): each share holds about a tenth of an ounce, a little less
every year as the fund takes its 0.40% fee, so its price is divided by the gold behind each
share. This gives a daily gold price back to late 2004. The price at the top of the page is
COMEX gold futures, about 10 minutes delayed.
""")


def gold_news() -> None:
    st.markdown(_shared_news("gold", "Our saved gold story archive only starts in mid-2026, so the "
                             "gold site has no *Like this before* yet: it needs about a year of "
                             "stories to compare with."))


def gold_reactions() -> None:
    st.markdown(f"""
**Fed decisions** are every change in the Fed's target rate since late 2004, measured from two
business days before the change took effect. The first move of a new cycle (a turn in policy)
is kept apart from moves that continue a cycle.

**The real interest rate** is the 10-year yield on inflation-protected Treasuries (TIPS), from
the Federal Reserve: what a safe bond pays after inflation.

**Market conditions** compares today's readings (trend, momentum, volatility, the real rate and
its 3-month change, and the dollar) with every past day, and finds the days most like today.

**Popular gold rules, tested** (Research tab) turns five common beliefs about gold (buy in an
uptrend, when real interest rates fall, when the dollar weakens, when hedge funds are bearish,
when war or crisis hits the news) into rules that decide each day whether to own gold or sit in
cash, and compares them with simply holding gold. They only use information public at the time
(the real rate counts from two business days later, the dollar from a week later, hedge-fund
positioning from the Monday after its Friday release), charge {bt.COST_PCT:.2f}% per trade, and
were written down before any results were seen; 2017 onwards is the main test.

**Spike alerts** check each gold topic every 3 hours and send a push notification (through
the free ntfy app) when one starts spiking, plus a Saturday week in review.
""")


def gold_sources() -> None:
    st.markdown("""
| Data | Source | Since |
|---|---|---|
| Gold (from GLD fund closes) | Yahoo Finance; Alpaca as a backup | 2004 |
| Live gold futures | Yahoo Finance (about 10 min delayed) | today |
| 10-year real interest rate (TIPS) | Federal Reserve via FRED | 2003 |
| U.S. dollar (broad index) | Federal Reserve via FRED | 2006 |
| Fed target rate | Federal Reserve via FRED | 2004 |
| Hedge-fund positioning (managed money, COMEX gold) | CFTC Commitments of Traders | 2006 |
| Worldwide news coverage | Media Cloud | 2015 |
| Gold market news | Benzinga via Alpaca, and publishers' news feeds | mid-2026 |
""")


@st.dialog("Methodology", width="large")
def show_gold() -> None:
    sections = st.tabs(["Overview", "News", "Measuring reactions", "Is it real?", "Limits", "Data sources"])
    for tab, section in zip(sections, [gold_overview, gold_news, gold_reactions, is_it_real, limits, gold_sources]):
        with tab:
            section()
