# Optional TV installation

Start with the authenticated browser display in the README. Configure and test
manual viewing before enabling automatic TV interruptions. The public release
never installs or activates HA automations automatically.

## Local TV feed

Set `tv_addresses` in local installation JSON to exact reserved TV IP addresses
(no subnets or hostnames). Build and install the configured component and web
files, then restart HA. Open the page with `?office_tv=1` on the TV.

This explicitly enables two unauthenticated, IP-restricted endpoints:
`GET /api/office_tv/aircraft` and `POST /api/office_tv/aircraft/finished`.
They require a direct socket peer on the allowlist and `X-Office-TV: 1`; proxy
headers and HA Cloud are rejected. There is no bearer token in the page.
The feed includes home coordinates. A client able to take the TV's address can
read that feed and invoke the finished script. Use a trusted isolated LAN and
leave this feature off on networks where that assumption is inappropriate.

HA YAML options `tv_addresses` and `use_bzn_board` can override build defaults.
Never add a public reverse proxy's IP to this allowlist. Use same-origin HA
login instead when opening the page through a proxy.

## TV scripts

`scripts/office-aircraft-config.py` prints proposed HA API payloads; it does not
apply them. Run it from the configured installation tree for your entity IDs.
This is a **Hisense Art Mode / TV Bro example**, not a universal TV driver:

- Supply an Android TV Remote entity, corresponding media-player entity and
  Android TV ADB entity in installation JSON.
- Supply existing `wake_script` and `art_script` implementations for your TV.
  Enter native Art directly where supported; never assume Power means Art.
- The example `house_mode` entity must report `Home` to allow automatic alerts.
- Create the scripts/automations through HA's UI/API, preserving generated IDs.
  The generated helper payloads are an alternative to the helper YAML; do not
  create both. Add the generated dashboard view to a dashboard of your choosing.
- Extend the cancellation automation's watched scripts to your own camera,
  dashboard and doorbell actions. Manual controls must take precedence.
- Alerts default off. Verify manual display, automatic interruption and return,
  Sleep/Away suppression, other-app navigation, casting, and reboot first.

Manual viewing wakes the TV; automatic alerts require it already on. The visible
page requests return only for an Automatic session, after 15 seconds without the
selected aircraft and with no other aircraft inside the boundary. The finished
script independently rechecks household/TV state before calling Art.

## Paid route enrichment

Set `key_file` to a path such as `/config/overhead-flightaware.key`; create the
file on HA with mode 0600. No key means no FlightAware requests or paid-budget
reservations. An explicitly configured invalid key fails setup rather than
silently switching modes. Free commercial misses never trigger paid lookups.
The separate `office_aircraft_routes.sqlite` ledger persists attempts; do not
remove it to clear route caches. Back it up with HA configuration.

No upgrade or restart of a running installation is performed by the build tool.
When upgrading from an older integration, install the new code/restart before
adding YAML options that its old in-memory schema does not understand.
