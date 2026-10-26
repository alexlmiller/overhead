"""Installation settings stay outside public sources and cannot inject code."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('configure', ROOT/'scripts/configure.py')
configure = importlib.util.module_from_spec(spec)
spec.loader.exec_module(configure)

class ConfigureTests(unittest.TestCase):
    def test_configured_build_preserves_distinct_entities_and_private_provider_options(self):
        original = (ROOT/'web/core.mjs').read_bytes()
        with tempfile.TemporaryDirectory() as folder:
            output = configure.build({
                'player': 'media_player.lounge', 'adb_player': 'media_player.lounge_adb',
                'remote': 'remote.lounge', 'tv_addresses': ['192.0.2.123'],
                'use_bzn_board': True, 'key_file': '/config/route-key',
            }, Path(folder)/'build')
            recovery = (output/'scripts/office-aircraft-config.py').read_text()
            self.assertIn('media_player.lounge_adb', recovery)
            self.assertNotIn('media_player.lounge_adb_adb', recovery)
            self.assertNotIn('media_player.overhead_tv', recovery)
            init = (output/'custom_components/office_aircraft_routes/__init__.py').read_text()
            self.assertIn('options.get("use_bzn_board", True)', init)
            self.assertNotIn('"use_bzn_board", default=', init)
            model = (output/'custom_components/office_aircraft_routes/model.py').read_text()
            self.assertIn("['192.0.2.123']", model)
            package = json.loads((output/'home_assistant/packages/aircraft-routes-package.yaml').read_text())
            self.assertEqual(package['office_aircraft_routes'], {'key_file': '/config/route-key'})
            for path in (output/'web').glob('*.mjs'):
                self.assertNotIn('/config/route-key', path.read_text())
            with self.assertRaises(ValueError):
                configure.build({}, output)
        self.assertEqual((ROOT/'web/core.mjs').read_bytes(), original)

    def test_public_defaults_need_no_paid_key_and_expose_no_tokenless_feed(self):
        with tempfile.TemporaryDirectory() as folder:
            output = configure.build({}, Path(folder)/'build')
            package = json.loads((output/'home_assistant/packages/aircraft-routes-package.yaml').read_text())
            self.assertEqual(package['office_aircraft_routes'], {})
            model = (output/'custom_components/office_aircraft_routes/model.py').read_text()
            self.assertIn('TV_ADDRESSES = frozenset(map(tv_address, []))', model)

    def test_invalid_settings_fail_before_creating_output(self):
        bad = [
            {'tv_addresses':['192.0.2.0/24']}, {'tv_addresses':'192.0.2.1'},
            {'player':'media_player.x\nprint(1)'}, {'player':'remote.x'},
            {'base_url':'https://user:password@example.com'},
            {'base_url':'https://example.com/path'}, {'unknown':True},
            {'key_file':'secret-value'}, {'use_bzn_board':'true'},
        ]
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)/'build'
            for config in bad:
                with self.subTest(config=config), self.assertRaises(ValueError):
                    configure.build(config, output)
                self.assertFalse(output.exists())

if __name__ == '__main__':
    unittest.main()
