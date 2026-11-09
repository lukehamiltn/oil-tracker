# Oil Tracker

Today's oil news, matched to similar moments in the past, and what the market
did next. Plus: event studies (EIA, OPEC+, Fed), backtested trading rules,
today's market conditions vs history, and two paper-trading bots on live prices.

**Live site: https://oil-tracker-q7rqjuftmvvqnrgbkzwjcd.streamlit.app/**

## Goal

> "When news like *this* happened before, here's what oil did next."

## Data sources

All free; government data unless noted.

- **Worldwide news:** the GDELT Project: daily coverage of 8 oil news topics
  since 2017 (saved in `news_data/timelines.csv`, refreshed daily by
  `.github/workflows/news.yml`)
- **Market news:** Benzinga via Alpaca: every story about oil funds and oil
  companies since 2015 (saved in `news_data/market_news/`, one file per month,
  refreshed every 3 hours). Powers the live headlines and the instant search
- **Prices:** Brent and WTI crude, NY Harbor gasoline and heating oil, Henry Hub
  natural gas (EIA, via FRED), the broad dollar index (FRED) and the XLE
  energy-stock fund (Alpaca). Every event is measured in all of them (`markets.py`)
- **Inventories:** EIA weekly U.S. crude stocks (public spreadsheet, no API key)
- **OPEC+ decisions:** hand-verified list in `events/opec_decisions.csv`
- **Fed rate decisions:** Fed target rate (FRED `DFEDTAR` / `DFEDTARU`)
- **Positioning:** CFTC Commitments of Traders, managed money in NYMEX WTI
- **Dollar:** Federal Reserve broad dollar index (FRED `DTWEXBGS`)
- **Live prices and paper account:** Alpaca (BNO fund)

EIA stopped publishing NYMEX futures prices in April 2024, so there is no free
current futures curve.

## How to run

```powershell
# one-time setup
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt

# download / refresh data into data/oil.db
.venv\Scripts\python.exe fetch_prices.py        # all market prices
.venv\Scripts\python.exe inventory_events.py    # EIA weekly inventories
.venv\Scripts\python.exe market_data.py         # CFTC positioning + dollar index
.venv\Scripts\python.exe fed_events.py          # Fed rate changes
.venv\Scripts\python.exe news.py update         # news coverage history (slow: GDELT rate limits)
.venv\Scripts\python.exe market_news.py update  # market news archive (fast)
.venv\Scripts\python.exe market_news.py latest  # latest tagged oil headlines

# analysis
.venv\Scripts\python.exe event_study.py         # OPEC+ event study
.venv\Scripts\python.exe backtest.py            # backtest rules in strategies.py
.venv\Scripts\python.exe plot_prices.py         # price chart to data/oil_prices.png

# paper-trading bots (needs Alpaca paper keys in .env); --dry-run places no orders
.venv\Scripts\python.exe bot.py --dry-run

# start the website, then open http://localhost:8501 (Ctrl+C to stop)
.venv\Scripts\streamlit.exe run app.py
```

## Website tabs

`app.py` loads the data and lays out the page. Shared styling and chart pieces
are in `ui.py`; the site theme is in `.streamlit/config.toml`.

| Tab | File | What it shows |
|---|---|---|
| News | `news_page.py`, `news.py`, `market_news.py` | Today's headlines by topic, past news spikes, Brent's reaction, custom search |
| Event history | `history_page.py` | Every past event on one price chart; click one for its headlines and every market's reaction |
| Trading bots | `bot_dashboard.py` | Both bots' value, positions, trades vs holding BNO |
| Market conditions | `conditions.py` | Today's indicators vs history, and the most similar past days |
| Strategy lab | `lab_page.py`, `backtest.py`, `strategies.py` | Backtests, 2007-2016 build vs 2017-now test |
| Scheduled events | `inventory_events.py`, `event_study.py`, `fed_events.py` | Reaction to EIA reports, OPEC+ decisions, Fed rate changes |

## Paper trading bots

`bot.py` runs two bots ($50k each, labelled orders in one Alpaca paper account):
*Weak dollar* (own BNO while the dollar is below its 50-day average) and *Trend*
(own BNO while BNO is above its 200-day average). They run on
weekdays in the 2 hours before the close via GitHub Actions (`.github/workflows/bot.yml`).

The site itself is visited every hour by `.github/workflows/keep_awake.yml`
(`scripts/keep_awake.py`), so Streamlit Cloud never puts it to sleep and
real visitors don't wait for it to start up.

Keys are never committed. They live in:
- `.env` locally (`ALPACA_API_KEY=...`, `ALPACA_SECRET_KEY=...`)
- GitHub: Settings → Secrets and variables → Actions (for the bots)
- Streamlit Cloud: app Settings → Secrets (for the website's bot tab)

## Roadmap

1. [x] Price pipeline, event studies (EIA, OPEC+, Fed), website
2. [x] Backtester with out-of-sample test
3. [x] Paper-trading bots on live prices
4. [x] Market conditions page
5. [x] News: GDELT topics + Alpaca market news archive, spikes, headlines, instant search
6. [x] Site redesign (clean research style)
7. [ ] Custom domain / paid hosting
