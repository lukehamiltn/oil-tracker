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


# How often each word appears across saved headlines (filled by prepare()):
# the rarer a word, the better it pins down one story ("Heydari", "Hormuz"),
# while words like "says" or "oil" are in thousands of headlines.
_DOC_FREQ: dict[str, int] = {}


def prepare(headlines) -> None:
    """Learn which words are common from a big set of headlines (once per server)."""
    counts: dict[str, int] = {}
    for h in headlines:
        for w in set(re.findall(r"[a-z0-9][a-z0-9'.\-]*", str(h).lower())):
            counts[w] = counts.get(w, 0) + 1
    _DOC_FREQ.clear()
    _DOC_FREQ.update(counts)


# Everyday headline words: rare in a business-news archive, but useless for
# pinning down a story in a web search
GENERIC = set("""
move moved moves moving consider considers considering considered receive received receives
circulating circulate traders trader headline headlines rose rise rises rising risen fell fall
falls falling reaffirm reaffirms reaffirmed prior except frank relatively relative improvement
improve improves expect expects expected expectation expense expenses takeaway takeaways drop
dropping drops dropped major national direct push pushes pushing working work works nearby head
heads continue continues continued continuing flat compared compare sustainable assume assumes
assumed most return returns returned gradually gradual average averages averaged depleted
throughout forecast forecasts forecasting growth asked ask asks provide provides clear response
conditions condition day days done future reopen reopened open opens opened close closes
reportedly order leader incident master reports week weeks month months year years today
tomorrow yesterday time times first second third last next high higher highest low lower lowest
record big bigger biggest small large larger key main top latest late early level levels deal
deals talks talk plan plans planned warns warn warned warning set sets see sees seeing seen
government official officials minister secretary president spokesperson spokesman chief
general state states statement statements comment comments comments call calls called want wants
need needs needed make makes made take takes taking took give gives given keep keeps kept
expected unexpected despite following follow follows ahead behind around near amid
outlook short term long sharply slightly strong weak weaker stronger increase increased
increases decrease decreased decreases change changes changed remain remains remained
possible possibly likely unlikely potential potentially could would should total estimate
estimates estimated vs versus compared prior previous previously current currently
""".split())


def _search_window(day: pd.Timestamp) -> str:
    """Recent stories: the past week. Older ones: the day before to two days after."""
    if pd.Timestamp.now().normalize() - day <= pd.Timedelta(days=6):
        return "qdr:w"
    start, end = day - pd.Timedelta(days=1), day + pd.Timedelta(days=2)
    return f"cdr:1,cd_min:{start:%m/%d/%Y},cd_max:{end:%m/%d/%Y}"


def key_words(headline: str, limit: int = 5, skip: str = "") -> str:
    """A short search for the story: the headline's subject (its first two
    meaningful words, e.g. "OPEC October", "Occidental Petroleum") plus its
    most distinctive other words, in their original order. (Searching for the
    whole headline usually finds nothing.)"""
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9'\-]*(?:\.[A-Za-z0-9]+)*", headline)
    skip_words = set(skip.lower().split())
    content = []
    for i, w in enumerate(words):
        w = w.strip("'-.").removesuffix("'s").removesuffix("’s")
        low = w.lower()
        if (low in FILLER or low in GENERIC or low in skip_words or (len(low) < 3 and not low.isupper())
                or re.fullmatch(r"[\d.,]+[mbk]?", low)):
            continue
        content.append((i, w, _DOC_FREQ.get(low, 0)))
    subject = content[:2]
    rest = sorted(content[2:], key=lambda c: c[2])[:max(limit - len(subject), 0)]
    chosen = sorted(subject + rest, key=lambda c: c[0])
    seen, out = set(), []
    for _, w, _ in chosen:
        if w.lower() not in seen:
            seen.add(w.lower())
            out.append(w)
    return " ".join(out)


def web_search(headline: str, day: pd.Timestamp, site: str | None = None,
               skip: str = "") -> str:
    query = key_words(headline, skip=skip) + (f" site:{site}" if site else "")
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
            found.append((name, web_search(headline, day, site, skip=name)))
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
