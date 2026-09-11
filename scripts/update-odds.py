import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
NOW = datetime.now(ET)

# GitHub Actions checks at 13:00 and 14:00 UTC so this stays at 9:00 AM
# Eastern through daylight-saving changes. Only the 9 AM Eastern run updates.
if NOW.hour != 9:
    print(f"Skipping odds update; Eastern time is {NOW:%Y-%m-%d %H:%M}.")
    raise SystemExit(0)

TEAM_NAMES = {
    "ARI": "Cardinals", "ATL": "Falcons", "BAL": "Ravens", "BUF": "Bills",
    "CAR": "Panthers", "CHI": "Bears", "CIN": "Bengals", "CLE": "Browns",
    "DAL": "Cowboys", "DEN": "Broncos", "DET": "Lions", "GB": "Packers",
    "HOU": "Texans", "IND": "Colts", "JAX": "Jaguars", "KC": "Chiefs",
    "LV": "Raiders", "LAC": "Chargers", "LAR": "Rams", "MIA": "Dolphins",
    "MIN": "Vikings", "NE": "Patriots", "NO": "Saints", "NYG": "Giants",
    "NYJ": "Jets", "PHI": "Eagles", "PIT": "Steelers", "SF": "49ers",
    "SEA": "Seahawks", "TB": "Buccaneers", "TEN": "Titans", "WSH": "Commanders",
}

start = NOW.strftime("%Y%m%d")
end = (NOW + timedelta(days=6)).strftime("%Y%m%d")
url = f"https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard?dates={start}-{end}&limit=100"
req = Request(url, headers={"User-Agent": "KirbysKnockoutPool/1.0"})

with urlopen(req, timeout=30) as response:
    data = json.load(response)

spreads = {}

def to_number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

def clean_spread(value):
    n = to_number(value)
    if n is None:
        return None
    # ESPN may occasionally return a numeric zero for a pick'em line.
    if abs(n) < 0.0001:
        return 0
    return round(n, 1)

def parse_details(details, away_abbr, home_abbr):
    if not isinstance(details, str):
        return None
    match = re.search(r"\b([A-Z]{2,3})\s+([+-]?\d+(?:\.\d+)?)", details)
    if not match:
        return None
    abbr, value = match.groups()
    if abbr not in (away_abbr, home_abbr):
        return None
    n = clean_spread(value)
    if n is None:
        return None
    return (abbr, n)

for event in data.get("events", []):
    for competition in event.get("competitions", []):
        competitors = competition.get("competitors", [])
        by_side = {c.get("homeAway"): c for c in competitors}
        home = by_side.get("home")
        away = by_side.get("away")
        if not home or not away:
            continue

        home_abbr = (home.get("team") or {}).get("abbreviation")
        away_abbr = (away.get("team") or {}).get("abbreviation")
        if home_abbr not in TEAM_NAMES or away_abbr not in TEAM_NAMES:
            continue

        odds_list = competition.get("odds") or []
        odds = next((o for o in odds_list if o.get("spread") is not None), None)
        if not odds:
            odds = odds_list[0] if odds_list else None
        if not odds:
            continue

        home_spread = None
        away_spread = None
        home_odds = odds.get("homeTeamOdds") or {}
        away_odds = odds.get("awayTeamOdds") or {}

        home_spread = clean_spread(home_odds.get("spread"))
        away_spread = clean_spread(away_odds.get("spread"))

        # Some ESPN responses expose one competition-level spread instead.
        if home_spread is None and away_spread is None:
            game_spread = clean_spread(odds.get("spread"))
            if game_spread is not None:
                home_spread = game_spread
                away_spread = -game_spread

        # Final fallback: parse details such as "LAR -3.5".
        if home_spread is None and away_spread is None:
            parsed = parse_details(odds.get("details"), away_abbr, home_abbr)
            if parsed:
                abbr, value = parsed
                if abbr == home_abbr:
                    home_spread = value
                    away_spread = -value
                else:
                    away_spread = value
                    home_spread = -value

        if home_spread is None or away_spread is None:
            continue

        spreads[TEAM_NAMES[home_abbr]] = home_spread
        spreads[TEAM_NAMES[away_abbr]] = away_spread

output = {
    "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    "updated_et": NOW.strftime("%B %-d, %Y at %-I:%M %p ET"),
    "source": "ESPN",
    "spreads": dict(sorted(spreads.items())),
}

path = Path("odds.json")
path.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
print(f"Saved {len(spreads)} team spreads to {path}.")
