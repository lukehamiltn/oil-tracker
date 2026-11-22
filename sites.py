"""The markets the website covers, as shown on the homepage. Each one has its
own page (see app.py). `live` is the key used by live_prices.py."""

SITES = [
    {
        "key": "oil",
        "name": "Oil",
        "page": "oil.py",
        "live": "BRENT",
        "price_label": "Brent crude",
        "unit": "a barrel",
        "color": "#1f3a5f",
        "blurb": "Wars, OPEC+ decisions, sanctions and weekly U.S. stock reports: today's oil news "
                 "set against similar moments in the past, and what prices did next.",
        "features": ["Live Brent & WTI", "News spikes & storylines", "OPEC+, EIA & Fed history",
                     "Market signals", "Forecast model"],
    },
    {
        "key": "gas",
        "name": "Natural gas",
        "page": "gas.py",
        "live": "NATGAS",
        "price_label": "Henry Hub gas",
        "unit": "per MMBtu",
        "color": "#0f766e",
        "blurb": "Cold snaps, LNG exports, European supply and the weekly storage report: the "
                 "news that moves U.S. natural gas, and how prices reacted before.",
        "features": ["Live Henry Hub price", "Weather outlook", "Weekly storage reports", "News spikes & storylines",
                     "Market conditions", "Spike alerts"],
    },
]
