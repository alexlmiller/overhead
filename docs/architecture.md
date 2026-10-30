# Runtime contracts

## Display and selection

The static `web/` page reads HA on the same origin. Signed-in browsers use HA's
`hassTokens` storage and a scoped WebSocket subscription. Optional local TV mode
polls the explicitly enabled IP-restricted feed every 2 seconds. Demo mode uses
synthetic data and cannot authenticate or call HA services.

The REST package polls adsb.fi every 5 seconds using home coordinates rounded to
two decimals and a 15-NM search radius. Exact home coordinates remain in HA and
are sent to authorized display clients. OpenStreetMap tile requests reveal the
viewed map region to the tile server. No font or logo CDN requests are needed.

The radius helper controls alerts; surrounding aircraft are context only.
Reject stale/malformed positions. Selection follows the chosen aircraft for an
additional 2 miles. History retains 20 distinct in-boundary sightings; the UI
shows the latest five, excluding aircraft still nearby. Nearby cards page in
pairs every 8 seconds. High-churn entities are recorder-excluded.

Frontend entity IDs and HA script IDs retain the `office_aircraft_*` prefix for
compatibility. `scripts/configure.py` maps TV/household entities in a separate
installation tree. It does not alter the source checkout or embed coordinates.
The optional example automation needs user-owned wake/Art actions; it does not
assume those exist on a new HA instance. See [setup](setup.md).

## Route enrichment

ADSB.lol standing routes are cached for an hour; requests are spaced at least
5 seconds apart. Route geometry and heading reject implausible associations.
En-route ground track must be within 60° of the destination bearing, including
single-candidate routes; geographic proximity alone can accept an unrelated
cross-country flight. This may hide routes during large diversions or turns.
Climb/descent near a shared airport disambiguates adjacent legs. Accepted routes
at sightings are stored separately so later movement does not erase history.
Ambiguous or missing routes stay blank: these are reported associations, not
verified flight plans.

The Bozeman flight-board supplement is off by default. If enabled, it polls at
most every 5 minutes and uses dated arrival/departure windows, nearby position
and altitude checks. It is regional and not required elsewhere.

FlightAware is off without a key. Registration callsigns are a conservative
private-aircraft heuristic; airline misses never use the paid path. Accept only
General Aviation records matching registration and actual flight interval.
The integration's SQLite ledger reserves requests before HTTP, including failed
attempts, enforcing 25/24h and 800/31d limits. Cached matches last up to 6h;
rechecks are no sooner than 30 minutes. Authentication/payment errors pause
requests for 24h, rate limits for 1h. A corrupt ledger fails closed, never resets
spending history. Limits do not cover other consumers of the same account.

## Assets and deployment

Static files install under `/config/www/aircraft-display/`. HA caches `/local`
for 31 days: `make stamp` updates module/style content hashes. TV launch URLs
include a per-launch `t=` query. Keep fonts/logos immutable or refresh their URLs
when changing them. TV Bro's tested viewport is 960×540 CSS pixels; the display
opts out of forced dark colors and uses HA's timezone.

Aircraft names/icons and airline designators are generated from the tracked
data and documented upstream sources. See [third-party notices](../THIRD_PARTY_NOTICES.md).
No deployment-specific hostnames, credentials, runtime SQLite files or browser
storage belong in this repository.

## Route labels

Nearby cards and recent sightings show each city followed by its airport code
in smaller muted text on the same line. Long city names truncate before codes.
`?route_style=cities` or `?route_style=codes` selects a single-line alternative;
`both` is the default. `?panel_style=calm|route|detailed` compares the flight-first
(default), journey-first and original dense panel layouts. Map tags retain compact airport identifiers. Missing routes
stay hidden; unknown airports keep their exact code. Full labels remain in titles
when long names need ellipsis.

`web/airport-cities.mjs` bundles OurAirports municipality labels for IATA/ICAO
identifiers, with explicit served-city overrides in `scripts/build-airport-cities.py`.
Regenerate using `python3 scripts/build-airport-cities.py /path/to/airports.csv`
then `make stamp`. This catalog is presentation-only, never route evidence.

## Visit and route diagnostics

The integration owns `/config/office_aircraft_history.sqlite`, separate from the
paid-request ledger. It retains seven days of in-boundary visits and summarized
provider decisions; every poll prunes to 5,000 visits / 20,000 decision groups.
A ten-minute gap in in-boundary observations starts a new visit for the same
hex/callsign/registration. Short dropouts stay in one visit. Existing HA history
is imported as sightings, not reconstructed trips; receiver outages can split visits.

The journal stores identifiers, type, observation times, accepted route facts,
and provider outcomes (including heading/detour rejection, HTTP errors and budget
limits). It stores no coordinates, raw responses or credentials. Repeated outcomes
are aggregated; diagnostic sample counts are evaluations, not HTTP request counts.
Outcomes can overlap for one visit, so they are not an accuracy percentage.
`python3 scripts/route-report.py /path/to/office_aircraft_history.sqlite` reads the
seven-day summary without writing. HA exposes the same summary in the routes
sensor's `diagnostics` attribute, plus the latest 20 visits in `history`.

Recent cards match saved routes by visit ID and observation interval, including
after the six-hour provider cache expires. Source/evidence labels distinguish
standing routes, dated airport-board matches and actual-flight records; these
are provenance, not a guarantee of correctness. New diagnostics are prospective.
The journal is private runtime data and must never be committed or publicly served.
