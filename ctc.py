#!/usr/bin/env python3
"""
Cycle-Train-Cycle (CTC) London: true MVP.

Usage:
    python ctc.py "SW11 5TN" "N1 2UN"
    python ctc.py "SW11 5TN" "E1 1FR"
Optional: export TFL_APP_KEY=your_key   (free from the TfL API portal)

What it does:
  1. Geocodes two postcodes (postcodes.io, no key needed).
  2. Finds the 3 nearest stations from a hard-coded list to each end.
  3. Estimates the cycle legs from straight-line distance.
  4. Asks the TfL Journey Planner for the train leg for each station pair,
     keeping only direct journeys (no train changes).
  5. Prints the fastest CTC option next to the normal TfL journey time.

Everything here is deliberately crude. Cycle times are estimates,
station coordinates are approximate, and bike rules are a tiny hard-coded
table. Verify all of it before trusting the output.
"""

import math
import os
import sys

import requests

# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------

CYCLE_KMH = 15.0          # average cycling speed
DETOUR_FACTOR = 1.3       # straight-line distance -> rough road distance
STATION_BUFFER_MIN = 5    # carrying bike, finding platform, etc.
NEAREST_N = 3             # stations considered at each end
MAX_CYCLE_KM = 8.0        # ignore stations further than this from an end
MAX_CHANGES = 0           # direct trains only: no changes with a bike

TFL_BASE = "https://api.tfl.gov.uk"
TFL_APP_KEY = os.environ.get("TFL_APP_KEY")
DEBUG = os.environ.get("CTC_DEBUG")  # set CTC_DEBUG=1 to see why pairs are dropped

# Modes we ask TfL to use for the train leg.
RAIL_MODES = "overground,elizabeth-line,national-rail,dlr"

# --------------------------------------------------------------------------
# Bike rules (hard-coded, VERIFY against current TfL / operator policy)
# --------------------------------------------------------------------------
# mode id -> (allowed, note)
BIKE_RULES = {
    "overground":     (True,  "Check peak-time restrictions"),
    "elizabeth-line": (True,  "Check peak-time restrictions"),
    "dlr":            (True,  "Check peak-time restrictions"),
    "national-rail":  (True,  "Rules vary by operator; some need a reservation"),
    "tube":           (False, "Bikes not allowed"),
    "bus":            (False, "Bikes not allowed"),
}
IGNORED_MODES = {"walking", "cycle"}  # not rail legs; skip when checking rules

# --------------------------------------------------------------------------
# Stations: (name, lat, lon). Approximate. Check which allow bikes.
# --------------------------------------------------------------------------
STATIONS = [
    ("Clapham Junction", 51.4642, -0.1704),
    ("Waterloo", 51.5031, -0.1132),
    ("Victoria", 51.4952, -0.1441),
    ("London Bridge", 51.5052, -0.0864),
    ("Liverpool Street", 51.5178, -0.0823),
    ("King's Cross", 51.5309, -0.1233),
    ("Euston", 51.5282, -0.1337),
    ("Paddington", 51.5154, -0.1755),
    ("Marylebone", 51.5225, -0.1631),
    ("Highbury & Islington", 51.5460, -0.1040),
    ("Stratford", 51.5416, -0.0042),
    ("Richmond", 51.4633, -0.3013),
    ("Wimbledon", 51.4214, -0.2064),
    ("Balham", 51.4431, -0.1525),
    ("Brixton", 51.4627, -0.1145),
    ("Peckham Rye", 51.4695, -0.0694),
    ("Hackney Central", 51.5472, -0.0560),
    ("Willesden Junction", 51.5321, -0.2439),
    ("West Hampstead", 51.5469, -0.1906),
    ("Finsbury Park", 51.5642, -0.1065),
    ("Blackfriars", 51.5119, -0.1038),
    ("Farringdon", 51.5203, -0.1053),
    ("Canada Water", 51.4982, -0.0502),
    ("Lewisham", 51.4650, -0.0140),
    ("Greenwich", 51.4781, -0.0149),
    ("Ealing Broadway", 51.5152, -0.3019),
    ("Kingston", 51.4126, -0.3011),
    ("West Croydon", 51.3785, -0.1028),
    ("Tottenham Hale", 51.5882, -0.0594),
    ("Walthamstow Central", 51.5830, -0.0197),
    ("Romford", 51.5746, 0.1827),
    ("Bromley South", 51.3869, 0.0173),
    ("Sutton", 51.3590, -0.1917),
    ("Harrow & Wealdstone", 51.5920, -0.3350),
    ("Barking", 51.5396, 0.0809),
    # Windrush line (Highbury & Islington - New Cross / Clapham Jn / Crystal Palace / West Croydon)
    ("Canonbury", 51.5486, -0.0924),
    ("Dalston Junction", 51.5461, -0.0751),
    ("Haggerston", 51.5387, -0.0757),
    ("Hoxton", 51.5315, -0.0756),
    ("Shoreditch High Street", 51.5233, -0.0752),
    ("Whitechapel", 51.5195, -0.0612),
    ("Shadwell", 51.5116, -0.0570),
    ("Wapping", 51.5043, -0.0558),
    ("Rotherhithe", 51.5009, -0.0520),
    ("Surrey Quays", 51.4930, -0.0478),
    ("New Cross Gate", 51.4755, -0.0402),
    ("Brockley", 51.4647, -0.0376),
    ("Honor Oak Park", 51.4504, -0.0455),
    ("Forest Hill", 51.4392, -0.0530),
    ("Sydenham", 51.4271, -0.0541),
    ("Penge West", 51.4178, -0.0607),
    ("Anerley", 51.4125, -0.0657),
    ("Norwood Junction", 51.3971, -0.0751),
    ("Crystal Palace", 51.4182, -0.0724),
    ("Queens Road Peckham", 51.4736, -0.0573),
    ("Denmark Hill", 51.4681, -0.0894),
    ("Clapham High Street", 51.4651, -0.1327),
    ("Wandsworth Road", 51.4699, -0.1388),
    ("Battersea Park", 51.4778, -0.1475),
    # Mildmay line (Stratford - Highbury & Islington - Willesden Jn - Richmond / Clapham Jn)
    ("Hackney Wick", 51.5436, -0.0252),
    ("Homerton", 51.5469, -0.0420),
    ("Dalston Kingsland", 51.5483, -0.0752),
    ("Caledonian Road & Barnsbury", 51.5483, -0.1180),
    ("Camden Road", 51.5419, -0.1385),
    ("Kentish Town West", 51.5465, -0.1467),
    ("Gospel Oak", 51.5555, -0.1512),
    ("Hampstead Heath", 51.5552, -0.1656),
    ("Finchley Road & Frognal", 51.5500, -0.1833),
    ("Brondesbury", 51.5450, -0.2025),
    ("Acton Central", 51.5088, -0.2631),
    ("Gunnersbury", 51.4915, -0.2754),
    ("Kew Gardens", 51.4770, -0.2851),
]

# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def debug(msg):
    if DEBUG:
        print(f"[debug] {msg}", file=sys.stderr)


def haversine_km(a, b):
    """Straight-line distance in km between two (lat, lon) points."""
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(h))


def minutes(distance_km, speed_kmh):
    """Estimated minutes to cover a straight-line distance."""
    return distance_km * DETOUR_FACTOR / speed_kmh * 60


def geocode(postcode):
    """Postcode -> (lat, lon) using postcodes.io."""
    url = f"https://api.postcodes.io/postcodes/{postcode.replace(' ', '')}"
    r = requests.get(url, timeout=10)
    if r.status_code != 200:
        sys.exit(f"Could not geocode postcode: {postcode}")
    result = r.json()["result"]
    return (result["latitude"], result["longitude"])


def nearest_stations(point, n=NEAREST_N):
    """The n nearest stations to a point, within MAX_CYCLE_KM."""
    ranked = sorted(
        ((haversine_km(point, (lat, lon)), name, lat, lon) for name, lat, lon in STATIONS)
    )
    return [s for s in ranked[:n] if s[0] <= MAX_CYCLE_KM]


def count_changes(journey):
    """Number of changes: train/rail legs minus one. Walking legs don't count."""
    rail_legs = [leg for leg in journey["legs"] if leg["mode"]["id"] not in IGNORED_MODES]
    return max(len(rail_legs) - 1, 0)


def tfl_journey(origin, destination, modes=None, max_changes=None):
    """
    Call the TfL Journey Planner. origin/destination are (lat, lon).
    Returns the fastest journey dict (with at most max_changes changes
    if set), or None if nothing usable.
    """
    frm = f"{origin[0]},{origin[1]}"
    to = f"{destination[0]},{destination[1]}"
    params = {"journeyPreference": "LeastTime"}
    if modes:
        params["mode"] = modes
    if TFL_APP_KEY:
        params["app_key"] = TFL_APP_KEY

    r = requests.get(f"{TFL_BASE}/Journey/JourneyResults/{frm}/to/{to}", params=params, timeout=15)
    debug(f"TfL {frm} -> {to}: HTTP {r.status_code}")
    if r.status_code != 200:
        return None
    journeys = r.json().get("journeys", [])
    debug(f"  {len(journeys)} journeys, changes: {[count_changes(j) for j in journeys]}")
    if max_changes is not None:
        journeys = [j for j in journeys if count_changes(j) <= max_changes]
    return min(journeys, key=lambda j: j["duration"]) if journeys else None


def check_bike_rules(journey):
    """
    Returns (allowed, notes). allowed is False if any leg uses a mode
    where bikes are not allowed. Unknown modes are treated as not allowed.
    """
    notes = []
    for leg in journey["legs"]:
        mode = leg["mode"]["id"]
        if mode in IGNORED_MODES:
            continue
        allowed, note = BIKE_RULES.get(mode, (False, "Unknown mode, assuming no bikes"))
        if not allowed:
            return False, [f"{mode}: {note}"]
        if note not in notes:
            notes.append(note)
    return True, notes


def describe_rail(journey):
    """Short text for the rail part of a TfL journey."""
    parts = []
    for leg in journey["legs"]:
        mode = leg["mode"]["id"]
        if mode in IGNORED_MODES:
            continue
        options = leg.get("routeOptions") or [{}]
        line = options[0].get("name") or mode
        parts.append(f"{line} ({leg['duration']} min)")
    return ", then ".join(parts) if parts else "rail"


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------


def main():
    if len(sys.argv) != 3:
        sys.exit('Usage: python ctc.py "SW11 1AA" "N5 1QG"')

    a_pc, b_pc = sys.argv[1], sys.argv[2]
    a, b = geocode(a_pc), geocode(b_pc)

    origin_stations = nearest_stations(a)
    dest_stations = nearest_stations(b)
    if not origin_stations or not dest_stations:
        sys.exit("No stations in the list are close enough to one end of the journey.")

    options = []
    for d1, n1, la1, lo1 in origin_stations:
        for d2, n2, la2, lo2 in dest_stations:
            if n1 == n2:
                continue

            journey = tfl_journey((la1, lo1), (la2, lo2), modes=RAIL_MODES, max_changes=MAX_CHANGES)
            if not journey:
                debug(f"{n1} -> {n2}: no journey within the change limit")
                continue
            allowed, notes = check_bike_rules(journey)
            if not allowed:
                debug(f"{n1} -> {n2}: rejected by bike rules ({notes[0]})")
                continue

            first_leg = minutes(d1, CYCLE_KMH)
            last_leg = minutes(d2, CYCLE_KMH)

            total = first_leg + STATION_BUFFER_MIN + journey["duration"] + last_leg
            options.append({
                "total": total,
                "first": (n1, d1, first_leg),
                "rail": describe_rail(journey),
                "rail_min": journey["duration"],
                "changes": count_changes(journey),
                "last": (n2, d2, last_leg),
                "notes": notes,
            })

    options.sort(key=lambda o: o["total"])

    baseline = tfl_journey(a, b)
    all_cycle = minutes(haversine_km(a, b), CYCLE_KMH)

    print(f"\n{a_pc.upper()}  ->  {b_pc.upper()}\n")

    if not options:
        print("No cycle-train-cycle option found.")
    for i, o in enumerate(options[:3], start=1):
        n1, d1, t1 = o["first"]
        n2, d2, t2 = o["last"]
        print(f"Option {i}: about {round(o['total'])} min door to door")
        print(f"  1. Cycle ~{round(t1)} min ({d1 * DETOUR_FACTOR:.1f} km) to {n1}")
        print(f"  2. Train: {o['rail']}, total {o['rail_min']} min, {o['changes']} change(s) (+{STATION_BUFFER_MIN} min buffer)")
        print(f"  3. Cycle ~{round(t2)} min ({d2 * DETOUR_FACTOR:.1f} km) from {n2}")
        print(f"  Bike notes: {'; '.join(o['notes'])}\n")

    print("For comparison:")
    if baseline:
        print(f"  TfL fastest (no bike): {baseline['duration']} min")
    else:
        print("  TfL fastest: unavailable")
    print(f"  Cycling all the way (estimate): ~{round(all_cycle)} min")
    print("\nCycle times are straight-line estimates. Check current bike policy before travelling.")


if __name__ == "__main__":
    main()