"""Server-only route lookup and the office TV feed for the aircraft display."""
import asyncio
from datetime import timedelta
from http import HTTPStatus
import json
import logging
from pathlib import Path
import re
import time

import aiohttp
import voluptuous as vol
from homeassistant.components.http import HomeAssistantView
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED, EVENT_HOMEASSISTANT_STOP
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.network import is_cloud_connection

from .model import (DAILY_LIMIT, PERIOD_LIMIT, TV_ADDRESSES, TV_FINISHED_SCRIPT, TV_HEADER, tv_address, Enricher, Ledger, History,
                    airport_board, observations, tv_peer, tv_permitted, tv_snapshot)

DOMAIN = "office_aircraft_routes"
ENTITY = "sensor.office_aircraft_routes"
_LOGGER = logging.getLogger(__name__)
CONFIG_SCHEMA = vol.Schema({DOMAIN: vol.Schema({
    vol.Optional("key_file"): cv.string,
    vol.Optional("use_bzn_board"): cv.boolean,
    vol.Optional("tv_addresses"): vol.All(cv.ensure_list, [tv_address]),
})}, extra=vol.ALLOW_EXTRA)


class Coordinator:
    def __init__(self, hass, key, ledger, use_bzn_board=False, history=None):
        self.hass, self.key, self.ledger = hass, key, ledger
        self.history = history
        self.enricher = Enricher(ledger, hass.async_add_executor_job, self.request, use_airport_board=use_bzn_board, use_flightaware=bool(key), history=history)
        self.lock = asyncio.Lock()
        self.stopped = False
        self.task = None
        self.remove_timer = None

    async def request(self, provider, data):
        session = async_get_clientsession(self.hass)
        if provider == "adsblol":
            method, kwargs = "GET", {}
            # Same published data used by ADSB.lol's route API. Geographic and
            # direction checks run locally, avoiding its unreliable wrapper.
            call = data["callsign"]
            url = f"https://vrs-standing-data.adsb.lol/routes/{call[:2]}/{call}.json"
        elif provider == "bzn":
            method, url = "GET", "https://bozemanairport.com/flights"
            kwargs = {"headers": {"User-Agent": "CanvasTV-aircraft/0.1 (personal home display)"}}
        else:
            method = "GET"
            url = "https://aeroapi.flightaware.com/aeroapi/flights/"+data["registration"]
            kwargs = {"headers": {"x-apikey": self.key}, "params": {
                "ident_type": "registration", "max_pages": 1, "start": data["start"], "end": data["end"]}}
        try:
            async with session.request(method, url, **kwargs, allow_redirects=False,
                                       timeout=aiohttp.ClientTimeout(total=8)) as response:
                if response.status != 200:
                    return response.status, None
                # No error bodies, credentials or raw responses enter HA state/logs.
                body = bytearray()
                async for chunk in response.content.iter_chunked(16384):
                    body.extend(chunk)
                    if len(body) > 1024*1024:
                        return "oversize", None
                if provider == "bzn":
                    unmapped = set()
                    routes = airport_board(body.decode("utf-8"), time.time(), unmapped)
                    return 200, {"routes": routes, "unmapped": sorted(unmapped)[:5]}
                return 200, json.loads(body)
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
            return "connection_error", None

    async def update(self):
        if self.lock.locked() or self.stopped:
            return
        async with self.lock:
            now = time.time()
            try:
                feed = self.hass.states.get("sensor.office_aircraft_feed")
                home = self.hass.states.get("zone.home")
                radius = self.hass.states.get("input_number.office_aircraft_radius")
                candidate = self.hass.states.get("sensor.office_aircraft_candidate")
                aircraft = observations(feed.attributes.get("ac", []), float(feed.state),
                    (home.attributes.get("latitude"), home.attributes.get("longitude")),
                    max(1, min(10, float(radius.state))), candidate.attributes.get("history", []), now
                ) if all((feed, home, radius, candidate)) else []
                if self.history and candidate:
                    # Import retained legacy sightings without pretending to reconstruct old visits.
                    legacy = [{**a, "observed": a.get("last_seen"), "inside": True, "live": False}
                              for a in candidate.attributes.get("history", []) if isinstance(a, dict) and "hex" in a]
                    await self.hass.async_add_executor_job(self.history.observe, legacy, now)
                routes = await self.enricher.tick(aircraft, now)
                snapshot = await self.hass.async_add_executor_job(self.history.snapshot, now) if self.history else {}
                daily, period = await self.hass.async_add_executor_job(self.ledger.counts, now)
                routes = snapshot.get("routes", []) + routes
                self.hass.states.async_set(ENTITY, len(routes), {
                    "friendly_name": "Office Aircraft Routes", "routes": routes,
                    **{k: v for k, v in snapshot.items() if k != "routes"},
                    "requests_24h": daily, "requests_31d": period,
                    "limit_24h": DAILY_LIMIT, "limit_31d": PERIOD_LIMIT,
                    "providers": self.enricher.status, "updated_at": now})
            except Exception as error:  # Fail closed: no reset of the budget database.
                self.hass.states.async_set(ENTITY, "unavailable", {"error": type(error).__name__})
                _LOGGER.warning("Aircraft route update failed (%s)", type(error).__name__)

    @callback
    def schedule(self, _=None):
        if not self.stopped and (self.task is None or self.task.done()):
            self.task = self.hass.async_create_background_task(self.update(), "office aircraft routes")

    @callback
    def start(self, _=None):
        self.remove_timer = async_track_time_interval(self.hass, self.schedule, timedelta(seconds=5))
        self.schedule()

    @callback
    def stop(self, _=None):
        self.stopped = True
        if self.remove_timer:
            self.remove_timer()
        if self.task:
            self.task.cancel()


class TvView(HomeAssistantView):
    """No HA login: answers only a listed TV's own connection, never HA Cloud or a proxy."""
    requires_auth = False

    def __init__(self, hass, addresses):
        self.hass, self.addresses, self.refused_peers = hass, addresses, set()

    def refusal(self, request):
        transport = request.transport
        peer = tv_peer(transport.get_extra_info("peername") if transport else None)
        if tv_permitted(peer, self.addresses, is_cloud_connection(self.hass), request.headers.get(TV_HEADER)):
            return None
        if peer not in self.refused_peers and len(self.refused_peers) < 16:
            self.refused_peers.add(peer)  # One warning per address, bounded.
            _LOGGER.warning("Office TV feed refused a request from %s", peer or "an unknown peer")
        return self.json_message("Forbidden", HTTPStatus.FORBIDDEN)


class TvFeedView(TvView):
    """Read-only states for the office TV page."""
    url = "/api/office_tv/aircraft"
    name = "api:office_tv:aircraft"

    async def get(self, request):
        if refusal := self.refusal(request):
            return refusal
        return self.json(tv_snapshot(self.hass.states.get, self.hass.config.time_zone),
                         headers={"Cache-Control": "no-store"})


class TvFinishedView(TvView):
    """The page's only write: ask the finished script, which rechecks everything, to return to Art."""
    url = "/api/office_tv/aircraft/finished"
    name = "api:office_tv:aircraft:finished"
    last_call = float("-inf")

    async def post(self, request):
        if refusal := self.refusal(request):
            return refusal
        now = time.monotonic()
        if now-self.last_call < 5:
            return self.json_message("Too many requests", HTTPStatus.TOO_MANY_REQUESTS)
        self.last_call = now
        await self.hass.services.async_call("script", "turn_on", {"entity_id": TV_FINISHED_SCRIPT},
                                            context=self.context(request))
        return self.json_message("Accepted", HTTPStatus.ACCEPTED)


async def async_setup(hass, config):
    options = config[DOMAIN]
    allowed = frozenset(options.get("tv_addresses", TV_ADDRESSES))
    if allowed:
        # Independent of route enrichment, so the TV page works even if that cannot start.
        hass.http.register_view(TvFeedView(hass, allowed))
        hass.http.register_view(TvFinishedView(hass, allowed))
    try:
        secret = ""
        if options.get("key_file"):
            secret = (await hass.async_add_executor_job(Path(options["key_file"]).read_text)).strip()
            if not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", secret):
                raise ValueError("Invalid key format")
        ledger = await hass.async_add_executor_job(Ledger, hass.config.path("office_aircraft_routes.sqlite"))
        history = await hass.async_add_executor_job(History, hass.config.path("office_aircraft_history.sqlite"))
    except Exception as error:
        _LOGGER.error("Aircraft routes could not start (%s)", type(error).__name__)
        return False
    coordinator = Coordinator(hass, secret, ledger, options.get("use_bzn_board", False), history)
    hass.data[DOMAIN] = coordinator
    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, coordinator.stop)
    if hass.is_running:
        coordinator.start()
    else:
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, coordinator.start)
    return True
