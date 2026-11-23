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
    {
        "key": "gold",
        "name": "Gold",
        "page": "gold.py",
        "live": "GOLD",
        "price_label": "Gold",
        "unit": "an ounce",
        "color": "#b8860b",
        "blurb": "The Fed, real interest rates, safe-haven rushes and central bank buying: the news "
                 "that moves gold, and how the price reacted before.",
        "features": ["Live gold price", "Gold vs real interest rates", "Fed decisions since 2004",
                     "News spikes", "Market conditions", "Spike alerts"],
    },
]
