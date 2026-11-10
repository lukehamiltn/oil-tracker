"""
Where to read more about a one-line newswire flash.

Benzinga's newsdesk "flashes" are a single headline with no article behind
them, but they usually name where the news came from: "UKMTO says...",
"EIA says in its Short-Term Energy Outlook...", "...to Al Mayadeen".
For each flash we find:
  - the source it cites: official bodies link straight to their own page;
    news outlets get a search of their own site around the story's date
  - a general web search for the story's key words, limited to the days
    around it (works for older stories too)
"""

import re
from urllib.parse import quote

import pandas as pd

# Official bodies: name, how it appears in headlines, the page with their statements
OFFICIAL = [
    ("EIA Short-Term Energy Outlook", r"short[- ]term energy outlook|\bSTEO\b",
     "https://www.eia.gov/outlooks/steo/"),
    ("EIA weekly petroleum report", r"\bEIA\b.{0,60}\b(inventor|stockpile|crude stocks|"
     r"weekly petroleum)", "https://www.eia.gov/petroleum/supply/weekly/"),
    ("EIA", r"\bEIA\b|Energy Information Administration", "https://www.eia.gov/"),
    ("IEA", r"\bIEA\b|International Energy Agency", "https://www.iea.org/news"),
    ("OPEC", r"\bOPEC\b(?! ?\+)(?=.{0,40}\b(says|said|statement|secretary|report|bulletin))",
     "https://www.opec.org/opec_web/en/press_room/28.htm"),
    ("UKMTO", r"\bUKMTO\b|UK Maritime Trade Operations", "https://www.ukmto.org/"),
    ("U.S. Central Command", r"\bCENTCOM\b|Central Command",
     "https://www.centcom.mil/MEDIA/PRESS-RELEASES/"),
    ("Baker Hughes rig count", r"Baker Hughes.{0,40}rig|rig count", "https://rigcount.bakerhughes.com/"),
    ("Saudi Aramco", r"\bAramco\b", "https://www.aramco.com/en/news-media/news"),
    ("U.S. Treasury (sanctions)", r"\b(Treasury|OFAC)\b.{0,60}sanction",
     "https://home.treasury.gov/news/press-releases"),
    ("White House", r"\bWhite House\b(?=.{0,30}\b(says|said|statement|official))",
     "https://www.whitehouse.gov/news/"),
]

# News outlets: name, how it appears, their web address
OUTLETS = [
    ("Reuters", r"\bReuters\b", "reuters.com"),
    ("Bloomberg", r"\bBloomberg\b", "bloomberg.com"),
    ("Al Jazeera", r"\bAl Jazeera\b", "aljazeera.com"),
    ("Al Arabiya", r"\bAl Arabiya\b", "alarabiya.net"),
    ("Al Mayadeen", r"\bAl Mayadeen\b", "almayadeen.net"),
    ("Al Hadath", r"\bAl Hadath\b", "alhadath.net"),
    ("Press TV", r"\bPress TV\b", "presstv.ir"),
    ("IRNA", r"\bIRNA\b", "irna.ir"),
    ("Tasnim", r"\bTasnim\b", "tasnimnews.com"),
    ("Fars", r"\bFars\b", "farsnews.ir"),
    ("Saudi Press Agency", r"\bSaudi Press Agency\b|\bSPA\b", "spa.gov.sa"),
    ("Times of Israel", r"\bTimes of Israel\b", "timesofisrael.com"),
    ("CNBC", r"\bCNBC\b", "cnbc.com"),
    ("Wall Street Journal", r"\bWall Street Journal\b|\bWSJ\b", "wsj.com"),
    ("Financial Times", r"\bFinancial Times\b|\bFT\b", "ft.com"),
    ("Axios", r"\bAxios\b", "axios.com"),
    ("Argus", r"\bArgus\b", "argusmedia.com"),
    ("S&P Global Platts", r"\bPlatts\b", "spglobal.com"),
    ("Lloyd's List", r"\bLloyd'?s List\b", "lloydslist.com"),
    ("TankerTrackers", r"\bTankerTrackers\b", "tankertrackers.com"),
    ("Kpler", r"\bKpler\b", "kpler.com"),
    ("Fox News", r"\bFox News\b", "foxnews.com"),
    ("CNN", r"\bCNN\b", "cnn.com"),
    ("Ajel News", r"\bAjel\b", "ajel.sa"),
]

# Words that carry no search meaning in a wire headline
FILLER = set("""
says said say reports reported report reportedly earlier sources source posts post told tells
told according per via citing cites update updates breaking just new also amid after before
the a an of to in on at for and or but with by from as is are was were be been it its this that
these those will would could should may might has have had not no than then there their they
we our us he she his her them who whom which what when where why how all any some more most
very into over under about out up down off again further once here x
""".split())


def _search_window(day: pd.Timestamp) -> str:
    """Google's custom date range: from the day before to two days after."""
    start, end = day - pd.Timedelta(days=1), day + pd.Timedelta(days=2)
    return f"cdr:1,cd_min:{start:%m/%d/%Y},cd_max:{end:%m/%d/%Y}"


def key_words(headline: str, limit: int = 12) -> str:
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9'.\-]*", headline)
    kept = [w for w in words if w.lower().strip("'.") not in FILLER]
    return " ".join(kept[:limit])


def web_search(headline: str, day: pd.Timestamp, site: str | None = None) -> str:
    query = key_words(headline) + (f" site:{site}" if site else "")
    return ("https://www.google.com/search?q=" + quote(query)
            + "&tbs=" + quote(_search_window(day)))


def links(headline: str, time) -> list[tuple[str, str]]:
    """[(label, url), ...]: the cited source(s) first, then a web search."""
    day = pd.Timestamp(time).tz_localize(None) if pd.Timestamp(time).tzinfo else pd.Timestamp(time)
    day = day.normalize()
    found = []
    for name, pattern, url in OFFICIAL:
        if re.search(pattern, headline, re.IGNORECASE if name != "EIA" else 0):
            found.append((name, url))
            break                                  # the most specific match only
    for name, pattern, site in OUTLETS:
        if re.search(pattern, headline) and all(name != n for n, _ in found):
            found.append((name, web_search(headline, day, site)))
            if len(found) >= 2:
                break
    found.append(("Search the web", web_search(headline, day)))
    return found


if __name__ == "__main__":
    import market_news as mn
    live = mn.latest()
    for _, h in live[live["summary"].map(mn.is_flash)].iterrows():
        print(h["headline"][:100])
        for label, url in links(h["headline"], h["time"]):
            print(f"   {label}: {url[:110]}")
