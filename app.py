"""
The website's front door: it decides which page to show.

    streamlit run app.py      (Streamlit Cloud runs this file too)

Pages:
  /       home.py   all the markets we cover, each with its live price
  /oil    oil.py    the oil site
  /gas    gas.py    the natural gas site

To add a market: build its page, add it to sites.py (for the homepage card)
and add an st.Page line below.
"""

import importlib
import os

import streamlit as st

import alerts
import conditions
import credentials
import daily_move
import event_study
import fetch_prices
import gas_review
import gas_storage
import glossary
import live_prices
import markets
import mediacloud_news
import news
import news_feeds
import news_page
import recap
import signals
import sites
import storylines
import storylines_page
import ui
import weather

st.set_page_config(page_title="Market Tracker · commodity news and market history",
                   page_icon=":material/monitoring:", layout="wide")

# Streamlit Cloud can keep OLD copies of our files after an update (new page +
# old ui.py = crash). Reload the shared ones whenever any changed on disk, so
# every page starts from current code. (oil.py does the same for its own.)
SHARED = [credentials, event_study, fetch_prices, live_prices, markets, mediacloud_news, news, news_feeds,
          daily_move, signals, ui, storylines, storylines_page, glossary, news_page, gas_storage, sites,
          weather, recap, conditions, gas_review, alerts]


@st.cache_resource
def _versions() -> dict:
    return {}      # one per server process: {module name: file timestamp}


seen = _versions()
current = {m.__name__: os.path.getmtime(m.__file__) for m in SHARED}
if seen != current:
    for module in SHARED:
        importlib.reload(module)
    seen.clear()
    seen.update(current)

pages = [
    st.Page("home.py", title="All markets", icon=":material/home:", default=True),
    st.Page("oil.py", title="Oil", icon=":material/water_drop:", url_path="oil"),
    st.Page("gas.py", title="Natural gas", icon=":material/local_fire_department:", url_path="gas"),
]
st.navigation(pages, position="hidden").run()
