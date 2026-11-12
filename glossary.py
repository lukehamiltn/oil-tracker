"""
The Oil 101 window: the words the oil market (and this site) uses, in plain
English. Opened from the button in the header.
"""

import html

import streamlit as st

# {group: [(term, explanation), ...]}
TERMS = {
    "Prices and benchmarks": [
        ("Barrel", "The unit oil is priced in: 42 U.S. gallons (about 159 litres). The world "
                   "uses around 100 million barrels a day."),
        ("Brent", "Oil from the North Sea, and the price most of the world's oil is sold "
                  "against. When people quote 'the oil price' outside the U.S., they usually "
                  "mean Brent."),
        ("WTI (West Texas Intermediate)", "The U.S. benchmark, delivered at Cushing, Oklahoma. "
                                          "Usually a few dollars cheaper than Brent."),
        ("Spot price", "The price for oil delivered right away. Official daily spot prices "
                       "(from the U.S. Energy Information Administration) arrive about a week "
                       "late."),
        ("Futures contract", "An agreement today on the price of oil delivered in a future "
                             "month. Most oil trading happens in futures, so they show the "
                             "market's price minute by minute."),
        ("Front month", "The futures contract for the nearest delivery month, the one most "
                        "traded. The live prices at the top of the site are front-month "
                        "futures."),
        ("Benchmark", "A widely traded oil whose price others are set against (for example, "
                      "'Brent plus $2')."),
    ],
    "Market signals": [
        ("Futures curve", "The prices for oil delivered in each of the coming months, drawn as "
                          "a line. Its slope says whether oil is scarce now or plentiful."),
        ("Backwardation", "When oil for delivery soon costs more than oil for later. A sign "
                          "supplies are tight right now: buyers pay extra to get oil sooner."),
        ("Contango", "When oil for later costs more than oil now. A sign of plenty of supply; "
                     "the higher later price pays traders to store oil."),
        ("Brent–WTI spread", "Brent's price minus WTI's. Wider means world oil is dear next to "
                             "U.S. oil."),
        ("Crack spread / refining margin", "What refiners earn turning crude into gasoline and "
                                           "diesel (the value of the fuel minus the cost of "
                                           "the crude). The common '3-2-1' version assumes 3 "
                                           "barrels of crude make 2 of gasoline and 1 of "
                                           "diesel."),
        ("Volatility", "How violently prices swing, usually given as a yearly rate. 30% "
                       "means a typical year's move is about 30% up or down."),
    ],
    "Supply": [
        ("OPEC", "The Organization of the Petroleum Exporting Countries, led by Saudi Arabia. "
                 "Members agree how much oil to pump to steer prices."),
        ("OPEC+", "OPEC plus other producers, most importantly Russia, which coordinate "
                  "output since 2016. Their meetings are some of the biggest scheduled oil "
                  "events."),
        ("Production quota / cut", "The output limits OPEC+ sets. A cut means pumping less "
                                   "to push prices up; an increase means pumping more."),
        ("Spare capacity", "Oil that producers could pump quickly but choose not to, mostly in "
                           "Saudi Arabia and the UAE. Little spare capacity makes prices jumpier."),
        ("Strait of Hormuz", "The narrow sea lane out of the Persian Gulf. About a fifth of "
                             "the world's oil passes through it, so threats to it move prices."),
        ("Sanctions and price cap", "Limits on buying a country's oil (Iran, Russia, "
                                    "Venezuela). The price cap lets Russian oil be shipped "
                                    "only if it's sold below a set price."),
        ("Shale oil", "Oil from U.S. rock formations (Texas, North Dakota), produced by "
                      "fracking. It made the U.S. the world's largest producer."),
        ("SPR (Strategic Petroleum Reserve)", "The U.S. government's emergency oil stockpile, "
                                              "held in salt caverns on the Gulf Coast."),
    ],
    "Demand and the economy": [
        ("Refinery runs", "How much crude refineries are processing. More runs means more "
                          "crude buying."),
        ("Gasoline and diesel (heating oil)", "The main fuels made from crude. Heating oil is "
                                              "traded as the stand-in for diesel."),
        ("The dollar", "Oil is priced in dollars, so a weaker dollar makes oil cheaper for "
                       "everyone else and tends to lift its price."),
        ("Interest rates (the Fed)", "Higher rates slow the economy and strengthen the dollar, "
                                     "both usually bad for oil prices."),
        ("Recession", "A shrinking economy. Oil demand falls with it, and so do prices."),
    ],
    "Reports and data": [
        ("EIA weekly report", "The U.S. Energy Information Administration's Wednesday report "
                              "on U.S. crude and fuel stocks. Bigger-than-expected stock "
                              "builds tend to push prices down."),
        ("Inventories (stocks)", "Oil held in storage. Stocks above normal mean plenty of "
                                 "supply; below normal means tightness."),
        ("Cushing", "The Oklahoma storage hub where WTI futures are delivered. Its stock "
                    "levels are watched closely."),
        ("OPEC monthly report", "OPEC's report on supply, demand and its members' output, "
                                "out around the middle of each month. It often brings a burst "
                                "of headlines but rarely a decision."),
        ("COT report (hedge fund positioning)", "A weekly U.S. report showing how many bets "
                                                "on rising or falling prices big speculators "
                                                "hold."),
    ],
    "Words used on this site": [
        ("Coverage (× normal)", "How much of all worldwide news is about a topic, compared "
                                "with its usual share. 3× normal means three times as many "
                                "stories as usual."),
        ("Spiking", "A news topic with at least twice its normal coverage and enough stories "
                    "(50 over 3 days worldwide), so a few articles can't trigger it."),
        ("Storyline and wave", "A storyline is a big story that runs for months (the Iran war, "
                               "Russia sanctions). A wave is a stretch when its coverage ran "
                               "far above normal."),
        ("Like this before", "Past moments whose news looked like today's, and what oil did "
                             "over the next day, week and month."),
        ("No clear pattern", "The average move after similar events could easily be luck. "
                             "We test this by comparing with random days."),
        ("200-day average", "Brent's average price over the last 200 trading days (about 10 "
                            "months). Above it is usually read as an uptrend."),
        ("Backtest", "Testing a trading rule on past prices to see how it would have done. "
                     "Past results don't promise future ones."),
        ("Buy and hold", "Buying once and never selling. The yardstick every trading rule is "
                         "measured against."),
        ("Paper trading", "Trading with pretend money in a real market. The site's bots trade "
                          "this way."),
    ],
}


@st.dialog("Oil 101", width="large")
def show() -> None:
    st.caption("The words the oil market uses, in plain English.")
    query = st.text_input("Find a word", placeholder="Search, e.g. contango",
                          key="glossary_search", label_visibility="collapsed").strip().lower()
    found = 0
    for group, terms in TERMS.items():
        shown = [(t, e) for t, e in terms
                 if not query or query in t.lower() or query in e.lower()]
        if not shown:
            continue
        found += len(shown)
        rows = "".join(f'<div class="term"><b>{html.escape(t)}</b>'
                       f'<span>{html.escape(e)}</span></div>' for t, e in shown)
        st.markdown(f'<div class="term-group">{html.escape(group)}</div>{rows}',
                    unsafe_allow_html=True)
    if not found:
        st.info("No matching words. Try a shorter search.")
