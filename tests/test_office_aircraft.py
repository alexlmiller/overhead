"""Selection and interruption regression cases, using synthetic positions only."""
import datetime
import ast
import importlib.util
import json
import math
import re
from pathlib import Path
import unittest

import yaml
from jinja2.nativetypes import NativeEnvironment

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = yaml.safe_load((ROOT / 'home_assistant/packages/aircraft-package.yaml').read_text())
SPEC = importlib.util.spec_from_file_location('aircraft_config', ROOT / 'scripts/office-aircraft-config.py')
CONFIG = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CONFIG)


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.clock = 1800000000
        self.states = {'sensor.office_aircraft_feed': str(self.clock),
                       'input_number.office_aircraft_radius': '3',
                       'input_text.office_aircraft_selected': ''}
        self.aircraft = []
        self.env = NativeEnvironment()
        self.env.filters['regex_match'] = lambda value, pattern: bool(re.match(pattern, value))
        self.env.globals.update(
            states=lambda entity: self.states.get(entity, 'unknown'),
            state_attr=self.attribute,
            now=lambda: datetime.datetime.fromtimestamp(self.clock, datetime.timezone.utc),
            as_timestamp=lambda value: value.timestamp(), cos=math.cos, sqrt=math.sqrt,
        )
        self.template = self.env.from_string(PACKAGE['template'][0]['variables']['selection'])

    def attribute(self, entity, key):
        if entity == 'zone.home':
            return {'latitude': 40.0, 'longitude': -100.0}[key]
        if entity == 'sensor.office_aircraft_feed' and key == 'ac':
            return self.aircraft
        return None

    def plane(self, hex_id='abcdef', miles=1, **kwargs):
        return dict(hex=hex_id, lat=40.0 + miles / (3958.7613 * math.pi / 180),
                    lon=-100.0, alt_baro=10000, seen_pos=1, **kwargs)

    def result(self):
        # HA strips rendered whitespace before its native-value parse.
        result = self.template.render()
        return ast.literal_eval(result.strip()) if isinstance(result, str) else result

    def test_miles_are_not_double_converted(self):
        self.aircraft = [self.plane(miles=2)]
        self.assertAlmostEqual(self.result()['candidate']['distance_mi'], 2)

    def test_closest_airborne_fresh_position_wins(self):
        self.aircraft = [self.plane('aaaaaa', 2), self.plane('bbbbbb', 1),
                         dict(self.plane('cccccc', .1), alt_baro='ground'),
                         dict(self.plane('dddddd', .2), seen_pos=60)]
        self.assertEqual(self.result()['candidate']['hex'], 'bbbbbb')

    def test_selected_plane_stays_until_exit_radius(self):
        self.states['input_text.office_aircraft_selected'] = 'aaaaaa'
        self.aircraft = [self.plane('aaaaaa', 4), self.plane('bbbbbb', 1)]
        self.assertEqual(self.result()['current']['hex'], 'aaaaaa')
        self.assertEqual(self.result()['candidate']['hex'], 'bbbbbb')
        self.aircraft[0] = self.plane('aaaaaa', 5.1)
        self.assertEqual(self.result()['current'], {})

    def test_stale_feed_and_old_positions_fail_closed(self):
        self.aircraft = [self.plane()]
        self.states['sensor.office_aircraft_feed'] = str(self.clock - 16)
        self.assertEqual(self.result()['candidate'], {})
        self.assertFalse(self.result()['feed_fresh'])
        self.states['sensor.office_aircraft_feed'] = str(self.clock - 14)
        self.aircraft[0]['seen_pos'] = 7
        self.assertEqual(self.result()['candidate'], {})

    def test_feed_failure_and_incomplete_aircraft(self):
        self.aircraft = [None, {}, {'hex': 'abcdef'}, self.plane(miles=4)]
        self.assertEqual(self.result()['candidate'], {})
        self.states['sensor.office_aircraft_feed'] = 'unavailable'
        self.assertFalse(self.result()['feed_fresh'])

    def test_future_feed_rejected(self):
        self.aircraft = [self.plane()]
        self.states['sensor.office_aircraft_feed'] = str(self.clock + 20)
        self.assertFalse(self.result()['feed_fresh'])

    def test_feed_timestamp_units(self):
        template = self.env.from_string(PACKAGE['rest'][0]['sensor'][0]['value_template'])
        for stamp in [self.clock, self.clock * 1000]:
            self.assertEqual(float(template.render(value_json={'now': stamp})), self.clock)

    def test_malformed_aircraft_list_is_empty(self):
        self.aircraft = 42
        self.assertEqual(self.result()['candidate'], {})

    def test_multiple_aircraft_and_background_do_not_change_alert_boundary(self):
        self.aircraft = [self.plane('aaaaaa', 1), self.plane('bbbbbb', 2), self.plane('cccccc', 4)]
        result = self.result()
        self.assertEqual([a['hex'] for a in result['inside']], ['aaaaaa', 'bbbbbb'])
        self.assertEqual(result['candidate']['hex'], 'aaaaaa')
        self.aircraft = [self.plane('cccccc', 4)]
        self.assertEqual(self.result()['candidate'], {})
        self.assertEqual(self.result()['inside'], [])

    def history(self, previous):
        template = PACKAGE['template'][0]['sensor'][0]['attributes']['history']
        rendered = self.env.from_string(template).render(selection=self.result(), this={'attributes': {'history': previous}})
        return ast.literal_eval(rendered.strip()) if isinstance(rendered, str) else rendered

    def test_recent_sightings_update_all_nearby_planes_without_background_or_duplicates(self):
        self.aircraft = [self.plane('aaaaaa', 1, flight='UAL123'), self.plane('bbbbbb', 2), self.plane('cccccc', 4)]
        old = self.history([])
        self.assertEqual(len(old), 2)
        self.assertNotIn('cccccc', [a['hex'] for a in old])
        self.clock += 5
        self.states['sensor.office_aircraft_feed'] = str(self.clock)
        updated = self.history(old)
        self.assertEqual(len(updated), 2)
        self.assertEqual(updated[0]['last_seen'], self.clock - 1)
        self.aircraft = []
        self.assertEqual(self.history(updated), updated)
        self.states['sensor.office_aircraft_feed'] = 'unavailable'
        self.assertEqual(self.history(updated), updated)

    def test_recent_sightings_are_bounded_newest_first_and_survive_a_restored_snapshot(self):
        old = [dict(hex=f'{i:06x}', callsign='', registration='', last_seen=self.clock-i) for i in range(30)]
        result = self.history(old)
        self.assertEqual(len(result), 20)
        self.assertEqual(result[0]['hex'], '000000')
        self.assertEqual(self.history(result), result)

    def test_invalid_hex_and_coordinates_never_enter_history(self):
        self.aircraft = [self.plane('<script>', 1), dict(self.plane(), lat=95), dict(self.plane(), lon=-190)]
        self.assertEqual(self.result()['inside'], [])
        self.assertEqual(self.history([]), [])

    def test_coordinate_query_rounds_only_search_center(self):
        template = self.env.from_string(PACKAGE['rest'][0]['resource_template'])
        self.env.globals['state_attr'] = lambda entity, key: {'latitude': 40.123456, 'longitude': -100.123456}[key]
        rendered = template.render()
        self.assertIn('/lat/40.12/lon/-100.12/', rendered)
        self.assertNotIn('123456', rendered)

    def test_rest_setup_before_home_zone_exists(self):
        self.env.globals['state_attr'] = lambda entity, key: None
        template = self.env.from_string(PACKAGE['rest'][0]['resource_template'])
        self.assertIn('/lat/0/lon/0/', template.render())


class ControlTests(unittest.TestCase):
    def test_popup_guards_and_manual_controls(self):
        payload = CONFIG.payloads()
        popup = payload['scripts']['office_tv_aircraft_popup']['sequence']
        self.assertIn(CONFIG.state('input_select.house_mode', 'Home'), popup)
        self.assertIn(CONFIG.state(CONFIG.PLAYER, CONFIG.ART, 'app_id'), popup)
        finish = payload['scripts']['office_tv_aircraft_finished']
        self.assertIn(CONFIG.state(CONFIG.SESSION, 'Automatic'), finish['sequence'])
        self.assertIn({**CONFIG.state(CONFIG.CANDIDATE, 'none'), 'for': '00:00:15'}, finish['sequence'])
        self.assertNotIn('office_tv_aircraft_finished', payload['automations'])
        watches = payload['automations']['office_tv_aircraft_cancel']['triggers'][0]['entity_id']
        self.assertIn('script.office_tv_doorbell_view', watches)
        self.assertIn('script.office_tv_stacks', watches)
        self.assertTrue(all(isinstance(step, dict) for step in popup))

    def test_recent_history_fits_helper_and_blocks_duplicates(self):
        popup = CONFIG.payloads()['scripts']['office_tv_aircraft_popup']['sequence']
        history = next(x['data']['value'] for x in popup if x.get('target', {}).get('entity_id') == 'input_text.office_aircraft_recent')
        now = 1800000000
        recent = [{'h': f'{i:06x}', 't': now - i} for i in range(10)]
        env = NativeEnvironment()
        env.filters.update(from_json=lambda s, fallback: json.loads(s), to_json=json.dumps)
        env.globals.update(states=lambda entity: json.dumps(recent), now=lambda: now, as_timestamp=lambda t: t)
        result = env.from_string(history).render(aircraft='ffffff')
        self.assertEqual(len(result), 6)
        self.assertLessEqual(len(json.dumps(result)), 255)
        guard = next(x['value_template'] for x in popup if 'from_json' in x.get('value_template', ''))
        self.assertFalse(env.from_string(guard).render(aircraft='000001'))
        self.assertTrue(env.from_string(guard).render(aircraft='ffffff'))


if __name__ == '__main__':
    unittest.main()
