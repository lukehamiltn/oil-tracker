"""
"Coming up": the next scheduled events that move oil, each with what
history says happened after events like it.

  - EIA weekly petroleum report: every Wednesday at 10:30am ET, or Thursday
    in a week with a federal holiday on Monday-Wednesday (worked out here).
  - OPEC+ meetings and Fed rate decisions: hand-kept in events/upcoming.csv
    (official schedules; add new dates as they're announced - the site
    health check warns when the file runs out of future dates).
"""

from pathlib import Path

import pandas as pd
from pandas.tseries.holiday import USFederalHolidayCalendar

import markets as mk

PATH = Path(__file__).parent / "events" / "upcoming.csv"
TZ = "America/New_York"


def eia_dates(start: pd.Timestamp, weeks: int = 4) -> list[pd.Timestamp]:
    """Release days of the EIA Weekly Petroleum Status Report."""
    holidays = USFederalHolidayCalendar().holidays(start - pd.Timedelta(days=7),
                                                   start + pd.Timedelta(weeks=weeks + 1))
    monday = (start - pd.Timedelta(days=start.weekday())).normalize()
    days = []
    for w in range(weeks + 1):
        week = monday + pd.Timedelta(weeks=w)
        late = any(week + pd.Timedelta(days=d) in holidays for d in range(3))   # Mon-Wed
        release = week + pd.Timedelta(days=3 if late else 2)
        if release.date() >= start.date():
            days.append(release)
    return days[:weeks]


def load_scheduled() -> pd.DataFrame:
    if not PATH.exists():
        return pd.DataFrame(columns=["date", "time_et", "kind", "title", "note", "source"])
    t = pd.read_csv(PATH, parse_dates=["date"]).fillna("")
    return t


def upcoming(now: pd.Timestamp | None = None, n: int = 4) -> pd.DataFrame:
    """The next n events (including today's, until its release time has passed)."""
    now = now or pd.Timestamp.now(tz=TZ)
    today = now.tz_localize(None).normalize() if now.tzinfo else now.normalize()
    rows = [{"date": d, "time_et": "10:30", "kind": "inventory",
             "title": "EIA weekly petroleum report",
             "note": "U.S. crude stocks: a bigger draw or build than normal can move prices",
             "source": "https://www.eia.gov/petroleum/supply/weekly/schedule.php"}
            for d in eia_dates(today)]
    scheduled = load_scheduled()
    rows += scheduled[scheduled["date"] >= today].to_dict("records")
    t = pd.DataFrame(rows)

    def passed(row) -> bool:            # today's event whose time has gone by
        if row["date"].date() != today.date() or not row["time_et"]:
            return False
        hour, minute = map(int, str(row["time_et"]).split(":"))
        return (now.hour, now.minute) >= (hour + 1, minute)   # an hour after release
    t = t[~t.apply(passed, axis=1)].sort_values("date")
    # The next event of each kind (so the weekly EIA report can't fill the list)
    return t.groupby("kind").head(1).head(n).reset_index(drop=True)


def when(date: pd.Timestamp, today: pd.Timestamp) -> str:
    days = (date.normalize() - today.normalize()).days
    return "Today" if days == 0 else "Tomorrow" if days == 1 else f"In {days} days"


# What history says, per kind of event (Brent, using the site's event studies)
def history(kind: str, data: dict) -> tuple[str, str]:
    """(one-line summary, verdict) for events of this kind."""
    sig = data["sig"]
    results = data["react"][kind]["BRENT"][0]
    if results.empty:
        return "", "few"
    if kind == "inventory":
        draws = results[results["category"] == "big_draw"]["day_1_pct"].dropna()
        builds = results[results["category"] == "big_build"]["day_1_pct"].dropna()
        verdict = sig.check("BRENT", 1, draws)
        return (f"After much bigger draws than normal, Brent rose {(draws > 0).mean():.0%} of "
                f"the time on report day (avg {draws.mean():+.1f}%); after big builds "
                f"{builds.mean():+.1f}%."), verdict
    if kind == "opec":
        week = results.groupby("decision")["day_5_pct"]
        parts, verdicts = [], {}
        for decision, label in [("cut", "cuts"), ("increase", "increases"),
                                ("no_deal", "no-deal meetings")]:
            if decision in week.groups:
                values = week.get_group(decision).dropna()
                verdicts[decision] = sig.check("BRENT", 5, values)
                parts.append(f"after {label} {values.mean():+.1f}%")
        best = min(verdicts, key=lambda d: ["strong", "possible", "noise", "few"].index(verdicts[d]))
        return "Brent a week later: " + ", ".join(parts) + ".", verdicts[best]
    if kind == "fed":
        week = results.groupby("decision")["day_5_pct"]
        parts, verdicts = [], {}
        for decision, label in [("first_cut", "a first cut"), ("cut", "further cuts"),
                                ("hike", "hikes")]:
            if decision in week.groups:
                values = week.get_group(decision).dropna()
                verdicts[decision] = sig.check("BRENT", 5, values)
                parts.append(f"after {label} {values.mean():+.1f}%")
        best = min(verdicts, key=lambda d: ["strong", "possible", "noise", "few"].index(verdicts[d]))
        return "Brent a week later: " + ", ".join(parts) + ".", verdicts[best]
    return "", "few"


def future_dates_left(kind: str) -> int:
    """How many future dates of this kind the hand-kept file still has."""
    t = load_scheduled()
    return int(((t["kind"] == kind) & (t["date"] >= pd.Timestamp.now().normalize())).sum())
