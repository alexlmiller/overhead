# Overhead

A quiet, full-screen aircraft display for Home Assistant and any modern browser.
See nearby aircraft, flight routes, aircraft types, and the last five sightings
on a map. Optional Android TV automations interrupt artwork when aircraft pass
nearby, then return to it afterward.

**Developer preview · MIT licensed code.** Tested on a Hisense CanvasTV with
TV Bro. Manual package installation; not yet a HACS/UI-configured integration.

## Try the display

```sh
python3 -m http.server 8767 --bind 127.0.0.1 --directory web
# Open http://127.0.0.1:8767/index.html?demo=1
```

No Home Assistant, account, API key or build step is needed for the demo.
The fictional flights cannot call HA services. Preview scenes:
`&scene=quiet`, `stale`, `sparse`, `cluster`, or `busy`.
Map tiles require internet access.

## Install on Home Assistant

1. Back up your HA configuration. Set your home location in HA; exact coordinates
   are read from `zone.home`, never compiled into this repository.
2. Copy `custom_components/office_aircraft_routes/` into HA's
   `/config/custom_components/office_aircraft_routes/`.
3. Copy the three YAML files in `home_assistant/packages/` into `/config/packages/`.
   Enable `homeassistant: packages: !include_dir_named packages` in your existing
   `configuration.yaml` (merge this under the existing `homeassistant:` key).
   Existing installations must keep their current helpers instead of duplicating
   `aircraft-helpers-package.yaml`.
4. Copy `web/` contents into `/config/www/aircraft-display/`.
5. Check the complete HA configuration and restart HA once. Check that
   `sensor.office_aircraft_feed` updates and `sensor.office_aircraft_routes` exists.
6. Sign into HA in your browser, then open
   `https://YOUR-HA/local/aircraft-display/index.html` on the **same origin**.
   Use a private/trusted display: it shows your home location.

Free commercial-route lookups work without a paid key. Missing routes remain
blank. The source prefix `office_aircraft_*` is retained for compatibility;
there is no requirement to have an office or a particular TV.

### Optional TV controls and providers

Copy `examples/installation.json` **outside this repo**, replace the example
entity IDs/URL, and generate a separate installation tree:

```sh
python3 scripts/configure.py --config /path/to/installation.json --output /tmp/overhead-install
```

Install the generated tree using the same paths above. It leaves source intact
and refreshes asset cache hashes. `tv_addresses` enables an IP-restricted local
TV feed; its default is empty (disabled). See [security and TV setup](docs/setup.md).
`use_bzn_board` enables the optional Bozeman airport route supplement.
`key_file` points to a server-only FlightAware key file; never put the key itself
in JSON, static assets or Git. FlightAware is optional, limited to registration
callsigns and capped at 25 attempts/24h and 800/31d. Confirm your provider terms
and permissions, including combined data use, before enabling it.

## Develop

Python 3.12+ and Node.js 22+. The frontend has no npm dependencies.

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
make test PYTHON=.venv/bin/python
make serve
```

Check at a 960×540 CSS viewport (TV Bro). Run `make stamp` after frontend edits;
HA caches static files for 31 days. [Architecture](docs/architecture.md) covers
selection, route validation, privacy and spending safeguards.

## Sources and license

Positions: [adsb.fi](https://adsb.fi/). Commercial routes:
[ADSB.lol](https://www.adsb.lol/). Optional routes:
[Bozeman Airport](https://bozemanairport.com/flights) and
[FlightAware AeroAPI](https://www.flightaware.com/commercial/aeroapi/).
Maps: [OpenStreetMap contributors](https://www.openstreetmap.org/copyright).

Original code is [MIT](LICENSE). Bundled fonts, datasets and airline marks retain
their respective terms and attribution; see [third-party notices](THIRD_PARTY_NOTICES.md).
