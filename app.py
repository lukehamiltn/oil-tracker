"""
The website's front door: it decides which page to show.

    streamlit run app.py      (Streamlit Cloud runs this file too)

Pages:
  /       home.py   all the markets we cover, each with its live price
  /oil    oil.py    the oil site
  /gas    gas.py    the natural gas site
  /gold   gold.py   the gold site

To add a market: build its page, add it to sites.py (for the homepage card)
and add an st.Page line below.
"""

import importlib
import os
import sys

import streamlit as st

st.set_page_config(page_title="Market Tracker · commodity news and market history",
                   page_icon=":material/monitoring:", layout="wide")

# Streamlit Cloud can keep OLD copies of our files after an update (new page +
# old ui.py = crash). So our shared files are loaded one at a time, in this
# order (each after the files it uses), and any copy already in memory is
# reloaded when the file changed on disk: a new file never meets an old copy
# of something it needs. Once one file is reloaded, every file after it is
# too (they may hold on to parts of it). oil.py does the same for its own.
SHARED = ["credentials", "event_study", "fetch_prices", "live_prices", "markets", "news", "flash_sources",
          "market_news", "mediacloud_news", "news_feeds", "daily_move", "signals", "ui", "spike_details", "glossary",
          "storylines", "weather", "gas_storage", "sites", "fed_events", "recap", "conditions", "news_page",
          "storylines_page", "commodity_news", "gas_review", "gold_review", "methodology", "alerts"]


@st.cache_resource
def _versions() -> dict:
    return {}      # one per server process: {module name: file timestamp}


seen = _versions()
changed = False
for name in SHARED:
    in_memory = name in sys.modules
    module = importlib.import_module(name)
    stamp = os.path.getmtime(module.__file__)
    if in_memory and (changed or seen.get(name) != stamp):
        importlib.reload(module)
        changed = True
    seen[name] = stamp

pages = [
    st.Page("home.py", title="All markets", icon=":material/home:", default=True),
    st.Page("oil.py", title="Oil", icon=":material/water_drop:", url_path="oil"),
    st.Page("gas.py", title="Natural gas", icon=":material/local_fire_department:", url_path="gas"),
    st.Page("gold.py", title="Gold", icon=":material/diamond:", url_path="gold"),
]
st.navigation(pages, position="hidden").run()
