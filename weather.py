"""
The U.S. weather outlook for natural gas: will the next two weeks be colder
or warmer than normal where people use the most gas?

Gas demand follows temperature. Traders measure it in "degree days": each
day's average temperature against 65°F.
  - heating degree days (HDD) = how far BELOW 65°F  -> winter heating demand
  - cooling degree days (CDD) = how far ABOVE 65°F  -> summer air-conditioning
                                                      (power plants burn gas)
We average them over big U.S. cities, weighted by population, so a cold
week in New York counts for more than one in Denver.

Forecasts and past temperatures come from Open-Meteo (open-meteo.com, free,
no key; data CC BY 4.0). "Normal" for each day of the year is the average
over 2015-2024, saved once in news_data/weather_normals.csv:

    python weather.py normals      # rebuild the normals (rarely needed)
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import requests

NORMALS_PATH = Path(__file__).parent / "news_data" / "weather_normals.csv"
BASE_F = 65.0

# Big gas-using metro areas: (name, latitude, longitude, population in millions)
CITIES = [
    ("New York", 40.71, -74.01, 19.5), ("Chicago", 41.88, -87.63, 9.4), ("Philadelphia", 39.95, -75.17, 6.2),
    ("Boston", 42.36, -71.06, 4.9), ("Detroit", 42.33, -83.05, 4.3), ("Washington", 38.91, -77.04, 6.3),
    ("Atlanta", 33.75, -84.39, 6.2), ("Dallas", 32.78, -96.80, 7.9), ("Houston", 29.76, -95.37, 7.3),
    ("Minneapolis", 44.98, -93.27, 3.7), ("Denver", 39.74, -104.99, 3.0), ("Los Angeles", 34.05, -118.24, 13.0),
    ("Phoenix", 33.45, -112.07, 5.0), ("Seattle", 47.61, -122.33, 4.0),
]
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"


def _temperatures(url: str, params: dict, timeout: float = 30) -> pd.DataFrame:
    """Daily mean temperature (°F) for every city: one column per city."""
    query = {
        "latitude": ",".join(str(c[1]) for c in CITIES),
        "longitude": ",".join(str(c[2]) for c in CITIES),
        "daily": "temperature_2m_mean", "temperature_unit": "fahrenheit", "timezone": "America/New_York",
        **params,
    }
    response = requests.get(url, params=query, timeout=timeout)
    response.raise_for_status()
    answers = response.json()
    answers = answers if isinstance(answers, list) else [answers]
    columns = {}
    for city, answer in zip(CITIES, answers):
        daily = answer["daily"]
        columns[city[0]] = pd.Series(daily["temperature_2m_mean"], index=pd.to_datetime(daily["time"]), dtype=float)
    return pd.DataFrame(columns)


def degree_days(temps: pd.DataFrame) -> pd.DataFrame:
    """Population-weighted heating and cooling degree days for each day."""
    weights = pd.Series({c[0]: c[3] for c in CITIES})
    weights = weights / weights.sum()
    hdd = (BASE_F - temps).clip(lower=0)
    cdd = (temps - BASE_F).clip(lower=0)
    return pd.DataFrame({"hdd": (hdd * weights).sum(axis=1, min_count=1),
                         "cdd": (cdd * weights).sum(axis=1, min_count=1)})


def build_normals(path: Path = NORMALS_PATH) -> None:
    """Average degree days for each day of the year over 2015-2024 (smoothed
    over two weeks, so one odd year doesn't make a bumpy line)."""
    temps = _temperatures(ARCHIVE_URL, {"start_date": "2015-01-01", "end_date": "2024-12-31"}, timeout=120)
    dd = degree_days(temps)
    dd["doy"] = np.minimum(dd.index.day_of_year, 365)
    normals = dd.groupby("doy")[["hdd", "cdd"]].mean()
    # smooth around the year (wrapping December into January)
    wrapped = pd.concat([normals.iloc[-7:], normals, normals.iloc[:7]])
    normals = wrapped.rolling(15, center=True).mean().iloc[7:-7].round(2)
    path.parent.mkdir(exist_ok=True)
    normals.to_csv(path)
    print(f"Saved normals for {len(normals)} days of the year")


def load_normals(path: Path = NORMALS_PATH) -> pd.DataFrame:
    return pd.read_csv(path, index_col="doy")


def outlook() -> dict:
    """The past week and the next 16 days, against normal.

    Returns { days: table (date, hdd, cdd, hdd_normal, cdd_normal, forecast),
              measure: "hdd" in the heating season or "cdd" in the cooling season,
              week1 / week2: % above (+) or below (-) normal for the next 7 days
              and the 7 after, in that measure }."""
    temps = _temperatures(FORECAST_URL, {"forecast_days": 16, "past_days": 7})
    dd = degree_days(temps).dropna()
    normals = load_normals()
    doy = np.minimum(dd.index.day_of_year, 365)
    dd["hdd_normal"] = normals.loc[doy, "hdd"].values
    dd["cdd_normal"] = normals.loc[doy, "cdd"].values
    today = pd.Timestamp.now(tz="America/New_York").tz_localize(None).normalize()
    dd["forecast"] = dd.index >= today
    # Heating season if heating demand is the bigger one at this time of year
    ahead = dd[dd["forecast"]]
    measure = "hdd" if ahead["hdd_normal"].sum() >= ahead["cdd_normal"].sum() else "cdd"

    def versus(part: pd.DataFrame) -> float:
        normal = part[f"{measure}_normal"].sum()
        return (part[measure].sum() / normal - 1) * 100 if normal > 0 else float("nan")

    return {"days": dd, "measure": measure, "week1": versus(ahead.iloc[:7]), "week2": versus(ahead.iloc[7:14]),
            "today": today}


def reading(view: dict) -> tuple[str, str, str]:
    """(headline, explanation, effect on prices) for the next two weeks."""
    measure, w1, w2 = view["measure"], view["week1"], view["week2"]
    both = (w1 + w2) / 2
    if measure == "hdd":
        word = "colder" if both > 0 else "warmer"
        effect = ("More heating demand than usual: usually supportive for gas prices." if both > 5 else
                  "Less heating demand than usual: usually weighs on gas prices." if both < -5 else
                  "Close to normal heating demand: weather isn't a big push either way.")
        title = (f"{word.capitalize()} than normal: heating demand {abs(both):.0f}% {'above' if both > 0 else 'below'}"
                 if abs(both) >= 5 else "About normal for the time of year")
    else:
        word = "hotter" if both > 0 else "cooler"
        effect = ("More air-conditioning than usual, so power plants burn more gas: usually supportive." if both > 5 else
                  "Less air-conditioning than usual: usually weighs on gas prices." if both < -5 else
                  "Close to normal cooling demand: weather isn't a big push either way.")
        title = (f"{word.capitalize()} than normal: cooling demand {abs(both):.0f}% {'above' if both > 0 else 'below'}"
                 if abs(both) >= 5 else "About normal for the time of year")
    detail = (f"{'Heating' if measure == 'hdd' else 'Cooling'} demand {w1:+.0f}% vs normal in days 1-7, "
              f"{w2:+.0f}% in days 8-14 (forecasts beyond a week are much less certain).")
    return title, detail, effect


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "normals":
        build_normals()
    else:
        v = outlook()
        print(v["days"].round(1).to_string())
        print(reading(v))
