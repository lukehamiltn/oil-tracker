# Oil Tracker

A website that tracks oil market prices and news events, and shows how the
market reacted to similar events in the past.

## Goal

> "When news like *this* happened before, here's what oil did next."

## Data sources (planned)

- **Prices:** WTI and Brent crude daily prices (EIA / FRED, public data)
- **Inventories:** EIA weekly U.S. crude stocks (public spreadsheet, no API key)
- **Scheduled events:** OPEC+ decisions (verified list), Fed rate decisions (planned)
- **News:** GDELT global news database

## How to run

```powershell
# one-time setup
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt

# download / refresh oil prices into data/oil.db
.venv\Scripts\python.exe fetch_prices.py

# draw a chart to data/oil_prices.png
.venv\Scripts\python.exe plot_prices.py

# download EIA weekly crude inventories and classify each report
.venv\Scripts\python.exe inventory_events.py

# measure how oil moved after OPEC+ decisions (events/opec_decisions.csv)
.venv\Scripts\python.exe event_study.py

# start the website, then open http://localhost:8501 (Ctrl+C to stop)
.venv\Scripts\streamlit.exe run app.py
```

## Roadmap

1. [x] Project setup
2. [x] Price pipeline: download and store historical oil prices
3. [x] Event database: OPEC+ decisions 1999-2025 (verified)
4. [x] Analysis: market reaction after similar events
5. [x] Website v1 (Streamlit)
6. [ ] Public launch: hosting, user accounts
