"""Bounded route enrichment and the office TV feed policy; no HA dependencies, credentials, or network I/O here."""
from contextlib import contextmanager
from datetime import datetime, timezone
from html.parser import HTMLParser
from ipaddress import ip_address
import json
import math
import os
import re
import sqlite3
from zoneinfo import ZoneInfo

DAY = 86400
DAILY_LIMIT = 25
PERIOD_LIMIT = 800
# A leg stays plausible while flying via the aircraft adds at most this much to
# its great-circle length. Airways and weather bend real tracks by a few percent
# of long legs; stale standing data typically misses by more than the leg itself.
DETOUR_MILES, DETOUR_SHARE = 60, 0.05
# A standing route is not a dated flight plan. Require a broadly aligned
# ground track even when geometry leaves only one candidate; a cross-country
# route can pass near the aircraft while it is flying toward a different city.
MAX_TRACK_ERROR = 60
# Regional operators fly partner-marketed flights under their own prefix and the
# same number, e.g. SKW3676 for Delta 3676 on the BZN board.
REGIONAL_PARTNERS = {
    "SKW": ("DAL", "UAL", "AAL", "ASA"), "QXE": ("ASA",), "RPA": ("UAL", "AAL", "DAL"),
    "ENY": ("AAL",), "PDT": ("AAL",), "JIA": ("AAL",), "ASH": ("UAL", "AAL"), "EDV": ("DAL",),
    "GJS": ("UAL", "DAL"), "CPZ": ("DAL", "AAL"), "UCA": ("UAL",), "AWI": ("UAL", "AAL"),
}
SIGHTING = ("latitude", "longitude", "heading", "speed_kt", "altitude_ft", "vertical_rate", "observed")


def ident(value):
    value = str(value or "").strip().upper()
    return value if re.fullmatch(r"[A-Z0-9-]{2,10}", value) else ""


def provider(a):
    call, reg = ident(a.get("callsign")), ident(a.get("registration"))
    if str(a.get("callsign") or "").strip() and not call:
        return None
    # Registration callsigns are a conservative proxy, not proof of ownership.
    if reg and (not call or call.replace("-", "") == reg.replace("-", "")):
        return "flightaware"
    if re.fullmatch(r"[A-Z]{3}[0-9][A-Z0-9]{0,5}", call):
        return "adsblol"
    return None


def key(a):
    return f"{a['hex']}:{ident(a.get('callsign')) or ident(a.get('registration'))}"


def distance(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    h = math.sin((p2-p1)/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(math.radians(lon2-lon1)/2)**2
    return 3958.7613 * 2 * math.asin(math.sqrt(min(1, max(0, h))))


def finite(value, low=-math.inf, high=math.inf):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and low <= value <= high)


def position(lat, lon):
    return finite(lat, -85, 85) and finite(lon, -180, 180)


def observations(raw, stamp, home, radius, history, now):
    """Fresh airborne positions plus recent in-boundary registration sightings."""
    if not 0 <= now-stamp <= 15 or not position(*home):
        return []
    found = {}
    for a in history[-20:] if isinstance(history, list) else []:
        if (isinstance(a, dict) and re.fullmatch(r"[0-9a-f]{6}", str(a.get("hex", "")))
                and isinstance(a.get("last_seen"), (int, float)) and 0 <= now-a["last_seen"] <= 6*3600):
            found[a["hex"]] = {**a, "observed": a["last_seen"], "live": False, "inside": True}
    for a in raw if isinstance(raw, list) else []:
        if not isinstance(a, dict):
            continue
        lat, lon, seen = a.get("lat"), a.get("lon"), a.get("seen_pos", 999)
        hexid = str(a.get("hex", "")).lower()
        if (not re.fullmatch(r"[0-9a-f]{6}", hexid) or not position(lat, lon)
                or not isinstance(seen, (int, float)) or not 0 <= now-stamp+seen <= 20
                or not isinstance(a.get("alt_baro"), (int, float))):
            continue
        rate = a.get("baro_rate") if finite(a.get("baro_rate")) else a.get("geom_rate")
        found[hexid] = {"hex": hexid, "callsign": ident(a.get("flight")), "registration": ident(a.get("r")),
                        "latitude": lat, "longitude": lon, "heading": a.get("track"), "speed_kt": a.get("gs"),
                        "altitude_ft": a["alt_baro"], "vertical_rate": rate if finite(rate) else None,
                        "observed": stamp-seen, "live": True,
                        "inside": distance(*home, lat, lon) <= radius}
    return sorted(found.values(), key=lambda a: (not (a["live"] and a["inside"]), -a["observed"]))


def bearing(lat1, lon1, lat2, lon2):
    p1, p2, dl = math.radians(lat1), math.radians(lat2), math.radians(lon2-lon1)
    return math.atan2(math.sin(dl)*math.cos(p2), math.cos(p1)*math.sin(p2)-math.sin(p1)*math.cos(p2)*math.cos(dl))


def commercial_route(payload, a, previous=None):
    """Select one plausible leg; `previous` (origin, destination) only breaks ties."""
    if not isinstance(payload, dict) or ident(payload.get("callsign")) != ident(a.get("callsign")):
        return None
    airports = payload.get("_airports")
    if not isinstance(airports, list) or not 2 <= len(airports) <= 12:
        return None
    if any(not isinstance(p, dict) or not position(p.get("lat"), p.get("lon")) for p in airports):
        return None
    p = (a["latitude"], a["longitude"])
    heading, climb = a.get("heading"), a.get("vertical_rate")
    has_track = finite(heading, 0, 360) and finite(a.get("speed_kt"), 120)
    has_climb = finite(climb)
    airport_code = lambda airport: ident(airport.get("iata")) or ident(airport.get("icao"))
    legs = {}
    for start, end in zip(airports, airports[1:]):
        origin, destination = airport_code(start), airport_code(end)
        if not origin or not destination or origin == destination:
            continue
        direct = distance(start["lat"], start["lon"], end["lat"], end["lon"])
        from_origin, to_destination = distance(*p, start["lat"], start["lon"]), distance(*p, end["lat"], end["lon"])
        detour = from_origin+to_destination-direct
        if detour > max(DETOUR_MILES, DETOUR_SHARE*direct):
            continue
        departing, arriving = from_origin <= 40 < to_destination, to_destination <= 40 < from_origin
        # Near one end of a leg, an arrival does not climb away and a departure does not descend;
        # neither cruises at airliner altitude within 25 mi of that airport.
        if has_climb and ((arriving and climb >= 1000) or (departing and climb <= -1000)):
            continue
        if finite(a.get("altitude_ft"), 25000) and min(from_origin, to_destination) <= 25:
            continue
        # Track is useful en route, but turns near an airport must not decide
        # which half of a same-callsign round trip is in progress.
        error = None
        if has_track and min(from_origin, to_destination) > 25:
            toward_destination = math.degrees(bearing(*p, end["lat"], end["lon"])) % 360
            error = abs((heading-toward_destination+180) % 360-180)
            if error > MAX_TRACK_ERROR:
                continue
        legs[(origin, destination)] = {"origin": origin, "destination": destination, "detour": detour,
                                       "track_error": error, "departing": departing, "arriving": arriving}
    candidates = sorted(legs.values(), key=lambda leg: leg["detour"])
    if not candidates:
        return None
    nearby = [leg for leg in candidates if leg["detour"]-candidates[0]["detour"] < 30]
    selected = nearby[0] if len(nearby) == 1 else None
    # Ties: en-route track, then a clear climb or descent near the shared airport,
    # then the leg already chosen for this flight. Otherwise the route stays blank.
    for chosen in (lambda leg: leg["track_error"] is not None and leg["track_error"] <= MAX_TRACK_ERROR,
                   lambda leg: has_climb and ((climb <= -500 and leg["arriving"]) or (climb >= 500 and leg["departing"])),
                   lambda leg: (leg["origin"], leg["destination"]) == previous):
        matched = [leg for leg in nearby if chosen(leg)] if not selected else []
        if len(matched) == 1:
            selected = matched[0]
    if not selected:
        return None
    return {"origin": selected["origin"], "destination": selected["destination"], "flight": ident(a["callsign"]),
            "source": "ADSB.lol", "valid_from": a["observed"]-120, "valid_until": a["observed"]+120}


class AirportBoard(HTMLParser):
    """Read the airport's public, dated HTML board without scripts or cookies."""
    def __init__(self):
        super().__init__()
        self.depth, self.table, self.rows = 0, None, []

    def handle_starttag(self, tag, attrs):
        if tag != "div":
            return
        self.depth += 1
        attrs = dict(attrs)
        if attrs.get("id") in ("arrivals-data", "departures-data"):
            self.table = {"depth": self.depth, "arrival": attrs["id"] == "arrivals-data", "day": 0}
        classes = attrs.get("class", "").split()
        if self.table and "day-divider" in classes:
            self.table["day"] += 1
        if self.table and self.table["day"] == 0 and "flight-row" in classes and "header-row" not in classes:
            self.rows.append((self.table["arrival"], attrs.get("title", "")))

    def handle_endtag(self, tag):
        if tag == "div":
            if self.table and self.table["depth"] == self.depth:
                self.table = None
            self.depth -= 1


BOARD_AIRLINES = {"Alaska": "ASA", "Allegiant": "AAY", "American": "AAL", "Delta": "DAL", "Southwest": "SWA",
                  "United": "UAL", "JetBlue": "JBU", "Sun Country": "SCX", "Frontier": "FFT", "Spirit": "NKS",
                  "Breeze": "MXY", "Avelo": "VXP", "Air Canada": "ACA", "WestJet": "WJA"}
# BZN's published destinations, keyed by board labels with case and punctuation removed.
# Labels ending in a destination code ("New York-LGA") resolve without an entry.
BOARD_CITIES = {
    "atlanta": "ATL", "austin": "AUS", "boise": "BOI", "boston": "BOS", "charlotte": "CLT",
    "chicagoohare": "ORD", "chicagoord": "ORD", "chicagomdw": "MDW", "chicagomidway": "MDW",
    "dallasftworth": "DFW", "dallasfortworth": "DFW", "dallaslove": "DAL", "dallaslovefield": "DAL",
    "denver": "DEN", "detroit": "DTW", "houston": "IAH", "lasvegas": "LAS", "losangeles": "LAX",
    "minneapolis": "MSP", "minneapolisstpaul": "MSP", "nashville": "BNA", "newark": "EWR",
    "newyorkjfk": "JFK", "newyorklga": "LGA", "newyorklaguardia": "LGA", "phoenix": "PHX",
    "phoenixmesa": "AZA", "portland": "PDX", "portlandor": "PDX", "saltlakecity": "SLC",
    "sandiego": "SAN", "sanfrancisco": "SFO", "seattle": "SEA", "seattletacoma": "SEA",
    "washingtondulles": "IAD", "washingtondc": "IAD",
}


def board_city(label):
    code = re.search(r"[-\s]([A-Z]{3})$", label)
    if code and code[1] in BOARD_CITIES.values():
        return code[1]
    return BOARD_CITIES.get(re.sub(r"[^a-z]", "", label.lower()))


def airport_board(html, now, unmapped=None):
    """Reject stale pages and future-day rows; keep only bounded flight facts.

    Unknown airline or city labels are added to `unmapped` for diagnostics."""
    date = re.search(r'class="current-date"[^>]*>([^<]+)<', html)
    clock = re.search(r'class="current-time"[^>]*>([^<]+)<', html)
    if not date or not clock:
        return []
    try:
        updated = datetime.strptime(date[1].strip()+" "+clock[1].strip(), "%B %d, %Y %I:%M%p").replace(tzinfo=ZoneInfo("America/Denver"))
    except ValueError:
        return []
    if not -120 <= now-updated.timestamp() <= 900:
        return []
    parser = AirportBoard()
    parser.feed(html)
    rows = []
    for arrival, title in parser.rows[:250]:
        fields = [s.strip() for s in title.split(" - ")]
        if len(fields) != 5:
            continue
        airline, number, city, local_time, status = fields
        code = board_city(city)
        if airline not in BOARD_AIRLINES or not code:
            if unmapped is not None:
                unmapped.add((city if airline in BOARD_AIRLINES else airline)[:40])
            continue
        if not re.fullmatch(r"[0-9]{1,4}", number) or "cancel" in status.lower() or "divert" in status.lower():
            continue
        try:
            clock = datetime.strptime(local_time, "%I:%M%p")
            at = updated.replace(hour=clock.hour, minute=clock.minute, second=0, microsecond=0).timestamp()
        except ValueError:
            continue
        rows.append({"flight": BOARD_AIRLINES[airline]+number, "origin": code if arrival else "BZN",
                     "destination": "BZN" if arrival else code, "source": "BZN Airport",
                     "valid_from": at-(45 if arrival else 10)*60,
                     "valid_until": at+(15 if arrival else 45)*60})
    return rows


def merge_board(old, new, now):
    """Flights leave the rolling board once they land or depart; keep them for their window."""
    rows = {(r["flight"], r["origin"], r["destination"]): r for r in old if r["valid_until"] > now-6*3600}
    rows.update({(r["flight"], r["origin"], r["destination"]): r for r in new})
    return sorted(rows.values(), key=lambda r: r["valid_from"])[-300:]


def marketed(callsign):
    """The callsign plus partner flights a regional operator flies under the same number."""
    call = ident(callsign)
    parts = re.fullmatch(r"([A-Z]{3})([0-9]{1,4})", call)
    return {call, *(partner+parts[2] for partner in REGIONAL_PARTNERS.get(parts[1], ()))} if parts else {call}


def airport_route(rows, a):
    if a["live"] and (not position(a.get("latitude"), a.get("longitude"))
                      or distance(a["latitude"], a["longitude"], 45.7775, -111.153) > 40
                      or a.get("altitude_ft", 99999) > 22000):
        return None
    if not a["live"] and not a["inside"]:
        return None
    flights = marketed(a.get("callsign"))
    matches = {(r["origin"], r["destination"]): r for r in rows
               if r["flight"] in flights and r["valid_from"] <= a["observed"] <= r["valid_until"]}
    # Label the aircraft's own callsign, not the partner's marketed flight number.
    return {**next(iter(matches.values())), "flight": ident(a.get("callsign"))} if len(matches) == 1 else None


def timestamp(value):
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError, AttributeError):
        return None


def private_routes(payload, registration, now):
    """Discard all but safe route fields; never infer a flight from its schedule."""
    results = []
    flights = payload.get("flights", []) if isinstance(payload, dict) else []
    for f in flights[:15] if isinstance(flights, list) else []:
        if (not isinstance(f, dict) or ident(f.get("registration")) != registration
                or f.get("type") != "General_Aviation" or f.get("cancelled") or f.get("diverted")):
            continue
        start, landed = timestamp(f.get("actual_off")), timestamp(f.get("actual_on"))
        eta = timestamp(f.get("estimated_on"))
        if start is None or start > now or (landed is None and eta is None):
            continue
        end = landed if landed is not None else min(start+12*3600, eta+1800)
        if end < start:
            continue
        def airport(p):
            if not isinstance(p, dict):
                return ""
            return ident(p.get("code_iata")) or ident(p.get("code_icao")) or ident(p.get("code"))
        origin, destination = airport(f.get("origin")), airport(f.get("destination"))
        if origin and destination and origin != destination:
            results.append({"origin": origin, "destination": destination, "flight": registration,
                            "source": "FlightAware", "valid_from": start, "valid_until": end})
    return results


def match_private(routes, observed):
    matched = [r for r in routes if r["valid_from"] <= observed <= r["valid_until"]]
    return matched[0] if len(matched) == 1 else None


class Ledger:
    """Integration-owned SQLite cache and durable, conservative request budget."""
    def __init__(self, path):
        self.path = str(path)
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)
        os.chmod(self.path, 0o600)
        with self.connect() as db:
            db.executescript("CREATE TABLE IF NOT EXISTS requests (at REAL NOT NULL);"
                             "CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, expires REAL NOT NULL, value TEXT NOT NULL);")
            if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise ValueError("Invalid route ledger")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        try:
            with db:
                yield db
        finally:
            db.close()

    def reserve(self, now):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            daily, period = self._counts(db, now)
            if daily >= DAILY_LIMIT or period >= PERIOD_LIMIT:
                return False
            db.execute("INSERT INTO requests VALUES (?)", (now,))
            db.execute("DELETE FROM requests WHERE at < ?", (now-31*DAY,))
        return True  # COMMIT precedes network request, even if the request fails.

    @staticmethod
    def _counts(db, now):
        return tuple(db.execute("SELECT COUNT(*) FROM requests WHERE at > ?", (now-window,)).fetchone()[0]
                     for window in (DAY, 31*DAY))

    def counts(self, now):
        with self.connect() as db:
            return self._counts(db, now)

    def get(self, key, now):
        with self.connect() as db:
            row = db.execute("SELECT value FROM cache WHERE key=? AND expires>?", (key, now)).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, key, value, expires, now):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO cache VALUES (?,?,?)", (key, expires, json.dumps(value, allow_nan=False)))
            db.execute("DELETE FROM cache WHERE expires<=?", (now,))

    def delete(self, key):
        with self.connect() as db:
            db.execute("DELETE FROM cache WHERE key=?", (key,))

    def routes(self, now):
        with self.connect() as db:
            rows = db.execute("SELECT value FROM cache WHERE (key LIKE 'route:%' OR key LIKE 'past-route:%') AND expires>? ORDER BY expires DESC LIMIT 100", (now,))
            return [json.loads(row[0]) for row in rows]


class Enricher:
    def __init__(self, ledger, run, request, use_airport_board=False, use_flightaware=True):
        self.ledger, self.run, self.request = ledger, run, request
        self.use_airport_board = use_airport_board
        self.use_flightaware = use_flightaware
        self.status = {"adsblol": "idle", "flightaware": "idle" if use_flightaware else "disabled"}

    async def get(self, k, now):
        return await self.run(self.ledger.get, k, now)

    async def put(self, k, v, expires, now):
        await self.run(self.ledger.put, k, v, expires, now)

    async def publish(self, a, route, now):
        if route:
            entry = {**route, "hex": a["hex"], "callsign": ident(a.get("callsign")),
                     "registration": ident(a.get("registration")), "expires": now+6*3600}
            await self.put("route:"+key(a), entry, now+6*3600, now)
            # Preserve the route at the in-boundary sighting, independently of
            # later live positions, route rejection, and integration restarts.
            if route["source"] != "FlightAware" and a["inside"] and (a["live"] or a.get("recovered")):
                await self.put("past-route:"+key(a), {**entry, "historical": True}, now+6*3600, now)
        elif a["live"]:
            await self.run(self.ledger.delete, "route:"+key(a))

    async def previous(self, a, now):
        """The leg already shown for this flight, while it is still current."""
        route = await self.get("route:"+key(a), now)
        if route and route["valid_until"] >= a["observed"]-600:
            return route["origin"], route["destination"]
        return None

    async def tick(self, aircraft, now):
        free = []
        for a in aircraft:
            if provider(a) != "adsblol":
                continue
            if a["live"]:
                if a["inside"]:
                    seen = {k: a.get(k) if finite(a.get(k)) else None for k in SIGHTING}
                    await self.put("sighting:"+key(a), seen, now+6*3600, now)
                free.append(a)
            elif now-a["observed"] <= 1800 and not await self.get("past-route:"+key(a), now):
                # A lookup can miss the minute a plane spends inside the boundary;
                # retry from the integration's own last in-boundary position.
                seen = await self.get("sighting:"+key(a), now)
                if seen and abs(seen["observed"]-a["observed"]) <= 60:
                    free.append({**a, **seen, "recovered": True})
        missing = []
        for a in free:
            cached = await self.get("lol:"+ident(a["callsign"]), now)
            if cached is None:
                missing.append(a)
            elif cached:
                await self.publish(a, commercial_route(cached, a, await self.previous(a, now)), now)
        if missing and not await self.get("cooldown:adsblol", now):
            await self.put("cooldown:adsblol", True, now+5, now)
            a = missing[0]
            status, payload = await self.request("adsblol", {
                "callsign": a["callsign"]})
            self.status["adsblol"] = str(status)
            if (status == 200 and isinstance(payload, dict)) or status == 404:
                data = payload if isinstance(payload, dict) and payload.get("callsign") == a["callsign"] else {}
                await self.put("lol:"+a["callsign"], data, now+(3600 if data else 1800), now)
                await self.publish(a, commercial_route(data, a, await self.previous(a, now)), now)
            else:
                await self.put("cooldown:adsblol", True, now+(900 if status == 429 else 60), now)
        commercial = [a for a in aircraft if provider(a) == "adsblol"]
        if self.use_airport_board and commercial:
            board = await self.get("bzn:board", now) or []
            if not await self.get("cooldown:bzn", now):
                await self.put("cooldown:bzn", True, now+300, now)
                status, payload = await self.request("bzn", {})
                self.status["bzn_airport"] = str(status)
                if status == 200 and isinstance(payload, dict):
                    board = merge_board(board, payload.get("routes", []), now)
                    await self.put("bzn:board", board, now+6*3600, now)
                    self.status["bzn_unmapped"] = ", ".join(payload.get("unmapped") or []) or "none"
                elif status in (401, 403, 429):
                    await self.put("cooldown:bzn", True, now+DAY, now)
            for a in commercial:
                route = airport_route(board, a)
                if route:
                    await self.publish(a, route, now)
        paid_this_tick = False
        for a in aircraft:
            if not self.use_flightaware or provider(a) != "flightaware" or not a["inside"]:
                continue
            cache_key = "fa:"+key(a)
            cached = await self.get(cache_key, now)
            route = match_private(cached["routes"], a["observed"]) if cached else None
            if route:
                await self.publish(a, route, now)
                if not a["live"] or now-cached["queried"] < 1800:
                    continue
            if (paid_this_tick or (cached and (not a["live"] or now-cached["queried"] < 1800))
                    or await self.get("cooldown:flightaware", now)):
                continue
            if not await self.run(self.ledger.reserve, now):
                self.status["flightaware"] = "budget_exhausted"
                continue
            paid_this_tick = True
            # Reserve a miss before HTTP too: failed/crashed calls cannot hot-loop on restart.
            await self.put(cache_key, {"routes": [], "queried": now}, now+6*3600, now)
            observed = datetime.fromtimestamp(a["observed"], timezone.utc)
            start = datetime.fromtimestamp(a["observed"]-12*3600, timezone.utc)
            end = datetime.fromtimestamp(min(now, a["observed"]+12*3600), timezone.utc)
            status, payload = await self.request("flightaware", {"registration": ident(a["registration"]),
                "start": start.strftime("%Y-%m-%dT%H:%M:%SZ"), "end": end.strftime("%Y-%m-%dT%H:%M:%SZ")})
            self.status["flightaware"] = str(status)
            if status == 200:
                routes = private_routes(payload, ident(a["registration"]), now)
                await self.put(cache_key, {"routes": routes, "queried": now}, now+6*3600, now)
                await self.publish(a, match_private(routes, observed.timestamp()), now)
            else:
                delay = DAY if status in (401, 402, 403) else 3600 if status == 429 else 60
                await self.put("cooldown:flightaware", True, now+delay, now)
        return await self.run(self.ledger.routes, now)


# Office TV feed: the page's entities, readable without an HA login by the TV
# alone. Overhead's aircraft sensors are served whole; household context only as
# far as the page reads it (never zone.home's persons or other player details).
TV_FEED_ENTITIES = {
    "sensor.office_aircraft_current": None, "sensor.office_aircraft_feed": None,
    "sensor.office_aircraft_candidate": None, "sensor.office_aircraft_routes": None,
    "zone.home": ("latitude", "longitude"),
    "input_number.office_aircraft_radius": (), "input_select.office_aircraft_session": (),
    "input_boolean.office_aircraft_alerts": (), "input_select.house_mode": (),
    "remote.overhead_tv": (),
    "media_player.overhead_tv": ("app_id",),
}
TV_HEADER = "X-Office-TV"
TV_FINISHED_SCRIPT = "script.office_tv_aircraft_finished"


def tv_address(value):
    """One exact IP address, IPv4-mapped IPv6 as IPv4; networks and names raise ValueError."""
    address = ip_address(str(value).strip())
    return getattr(address, "ipv4_mapped", None) or address


# No unauthenticated TV feed unless explicitly configured by the installer.
TV_ADDRESSES = frozenset()


def tv_peer(peername):
    """The connection's own TCP peer; forwarding headers are never consulted."""
    try:
        return tv_address(peername[0])
    except (TypeError, IndexError, ValueError):
        return None


def tv_permitted(peer, allowed, cloud, header):
    """Only a listed TV address on a direct LAN connection, never through HA Cloud."""
    return header == "1" and not cloud and peer is not None and peer in allowed


def tv_snapshot(get, time_zone):
    """Page-shaped states for the feed; missing entities are omitted."""
    states = {}
    for entity_id, keep in TV_FEED_ENTITIES.items():
        if (state := get(entity_id)) is None:
            continue
        attributes = state.attributes
        states[entity_id] = {"state": state.state, "attributes": dict(attributes) if keep is None
                             else {key: attributes[key] for key in keep if key in attributes}}
    return {"time_zone": time_zone, "states": states}
