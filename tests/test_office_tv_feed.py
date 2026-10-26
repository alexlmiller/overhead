"""The office TV feed answers only the TV and serves only the page's data."""
from ipaddress import IPv4Address, IPv6Address
import importlib.util
from pathlib import Path
import re
from types import SimpleNamespace
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('routes_model', ROOT/'custom_components/office_aircraft_routes/model.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
TV = IPv4Address('192.0.2.60')
ALLOWED = frozenset({TV})


def state(value, **attributes):
    return SimpleNamespace(state=value, attributes=attributes)


class AccessTests(unittest.TestCase):
    def test_addresses_are_exact(self):
        self.assertEqual(m.tv_address(' 192.0.2.60 '), TV)
        self.assertEqual(m.tv_address('::ffff:192.0.2.60'), TV)
        self.assertEqual(m.tv_address('fd00::60'), IPv6Address('fd00::60'))
        for value in ('192.0.2.0/24', '192.0.2.60/32', 'tv.home.example', '', '192.0.2'):
            with self.assertRaises(ValueError, msg=value):
                m.tv_address(value)

    def test_peer_comes_from_the_socket_only(self):
        self.assertEqual(m.tv_peer(('192.0.2.60', 52100)), TV)
        self.assertEqual(m.tv_peer(('::ffff:192.0.2.60', 52100, 0, 0)), TV)
        for peername in (None, (), ('not-an-address', 1), 'garbage'):
            self.assertIsNone(m.tv_peer(peername), peername)

    def test_only_the_tv_on_the_lan_with_the_page_header(self):
        self.assertTrue(m.tv_permitted(TV, ALLOWED, False, '1'))
        refused = {
            'another LAN device': (IPv4Address('192.0.2.61'), ALLOWED, False, '1'),
            'a proxy or HA Cloud peer': (IPv4Address('172.30.32.2'), ALLOWED, False, '1'),
            'HA Cloud, even from the TV address': (TV, ALLOWED, True, '1'),
            'no page header': (TV, ALLOWED, False, None),
            'another header value': (TV, ALLOWED, False, 'true'),
            'unknown peer': (None, ALLOWED, False, '1'),
            'feed disabled': (TV, frozenset(), False, '1'),
        }
        for reason, args in refused.items():
            self.assertFalse(m.tv_permitted(*args), reason)


class SnapshotTests(unittest.TestCase):
    def states(self):
        return {
            'sensor.office_aircraft_feed': state('1800000000', ac=[{'hex': 'a12345'}], friendly_name='Feed'),
            'sensor.office_aircraft_routes': state('1', routes=[], providers={'bzn_airport': '200'}),
            'zone.home': state('2', latitude=40.0, longitude=-100.0, radius=100, persons=['person.someone']),
            'input_select.house_mode': state('Home', options=['Home', 'Away', 'Sleep'], friendly_name='House'),
            'media_player.overhead_tv': state(
                'on', app_id='com.phlox.tvwebbrowser', media_title='Private', entity_picture='/api/x?token=y'),
            'remote.overhead_tv': state('on', activity_list=['Art']),
            'lock.front_door': state('unlocked'),
            'person.someone': state('home', latitude=40.0, longitude=-100.0),
        }

    def test_household_context_is_trimmed_to_what_the_page_reads(self):
        states = self.states()
        feed = m.tv_snapshot(states.get, 'America/Denver')
        self.assertEqual(feed['time_zone'], 'America/Denver')
        s = feed['states']
        self.assertEqual(s['zone.home'], {'state': '2', 'attributes': {'latitude': 40.0, 'longitude': -100.0}})
        self.assertEqual(s['input_select.house_mode'], {'state': 'Home', 'attributes': {}})
        self.assertEqual(s['remote.overhead_tv'], {'state': 'on', 'attributes': {}})
        self.assertEqual(s['media_player.overhead_tv']['attributes'],
                         {'app_id': 'com.phlox.tvwebbrowser'})
        self.assertEqual(s['sensor.office_aircraft_feed']['attributes']['ac'], [{'hex': 'a12345'}])
        self.assertIn('providers', s['sensor.office_aircraft_routes']['attributes'])

    def test_unlisted_and_missing_entities_never_appear(self):
        s = m.tv_snapshot(self.states().get, None)['states']
        self.assertNotIn('lock.front_door', s)
        self.assertNotIn('person.someone', s)
        self.assertNotIn('sensor.office_aircraft_current', s)
        self.assertLessEqual(set(s), set(m.TV_FEED_ENTITIES))

    def test_the_feed_serves_exactly_the_page_entities(self):
        core = (ROOT/'web/core.mjs').read_text()
        ids = re.search(r'export const IDS = Object\.freeze\(\{(.*?)\}\);', core, re.S).group(1)
        self.assertEqual(set(re.findall(r"'([a-z_]+\.[a-z0-9_]+)'", ids)), set(m.TV_FEED_ENTITIES))


class DeploymentTests(unittest.TestCase):
    def test_public_default_disables_tokenless_feed(self):
        self.assertEqual(m.TV_ADDRESSES, frozenset())

    def test_routes_package_keeps_the_running_schema(self):
        # HA checks package YAML against the already-loaded integration before
        # the restart that loads new code, so a new key fails the deploy lane.
        package = yaml.safe_load((ROOT/'home_assistant/packages/aircraft-routes-package.yaml').read_text())
        self.assertEqual(package['office_aircraft_routes'], {})


if __name__ == '__main__':
    unittest.main()
