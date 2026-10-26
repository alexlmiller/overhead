"""Curated type names stay valid and in sync with the generated display table."""
import importlib.util
import json
from pathlib import Path
import re
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('build_types', ROOT/'scripts/build-aircraft-types.py')
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)
ROWS = [
    {'Designator':'C172','ManufacturerCode':'CESSNA','ModelFullName':'172 Skyhawk'},
    {'Designator':'C172','ManufacturerCode':'CESSNA','ModelFullName':'172'},
    {'Designator':'C172','ManufacturerCode':'CESSNA','ModelFullName':'T-41 Mescalero'},
    {'Designator':'C172','ManufacturerCode':'REIMS','ModelFullName':'F172 Skyhawk'},
    {'Designator':'GLF6','ManufacturerCode':'GULFSTREAM AEROSPACE','ModelFullName':'G-6 Gulfstream G650'},
    {'Designator':'DC6','ManufacturerCode':'DOUGLAS','ModelFullName':'DC-6'},
    {'Designator':'DC6','ManufacturerCode':'DOUGLAS','ModelFullName':'R6D Liftmaster'},
    {'Designator':'DC6','ManufacturerCode':'DOUGLAS','ModelFullName':'C-118 Liftmaster'},
    {'Designator':'TAYB','ManufacturerCode':'TAYLORCRAFT (1)','ModelFullName':'BC (Ace)'},
    {'Designator':'MD11','ManufacturerCode':'MCDONNELL DOUGLAS','ModelFullName':'MD-11'},
    {'Designator':'DH8B','ManufacturerCode':'DE HAVILLAND CANADA','ModelFullName':'DHC-8-200 Dash 8'},
]


def committed():
    text = (ROOT/'web/aircraft-types.mjs').read_text(encoding='utf-8')
    return {m[1]: json.loads(m[2]) for m in re.finditer(r'^"([A-Z0-9]{2,4})":("(?:[^"\\]|\\.)*"),?$', text, re.M)}


class AircraftTypeTests(unittest.TestCase):
    def test_committed_table_contains_every_curated_name(self):
        table, curated = committed(), b.load_curated()
        self.assertGreater(len(table), 2500)
        self.assertEqual({code: table.get(code) for code in curated}, curated)

    def test_generated_names_use_the_main_manufacturers_family_name(self):
        names = b.generated(ROWS)
        self.assertEqual(names, {'C172':'Cessna 172 Skyhawk','GLF6':'Gulfstream G650','DC6':'Douglas DC-6',
                                 'TAYB':'Taylorcraft BC','MD11':'McDonnell Douglas MD-11','DH8B':'DHC-8-200 Dash 8'})

    def test_curated_names_override_and_must_exist(self):
        self.assertEqual(b.build(ROWS, {'C172':'Cessna Skyhawk','BALL':'Balloon'})['C172'], 'Cessna Skyhawk')
        with self.assertRaisesRegex(ValueError, 'C17Z'):
            b.build(ROWS, {'C17Z':'Typo'})
        with self.assertRaisesRegex(ValueError, 'Icon designators missing.*F16'):
            b.require(ROWS, {'F16'}, 'Icon designators')
        rendered = b.render({'C25B':'Cessna Citation CJ3'}, {'C25B':'jet.L','LJ35':'jet.L'}, '2026-09-24')
        self.assertIn('"C25B":"Cessna Citation CJ3"\n}));', rendered)
        self.assertIn('"jet.L":"C25B LJ35"\n});', rendered)

    def test_icons_follow_description_wake_and_engine_placement(self):
        cases = {'B738':('L2J','M','airliner.M'), 'B77W':('L2J','H','widebody.H'), 'A388':('L4J','J','quad.J'),
                 'C25B':('L2J','L','jet.L'), 'CL60':('L2J','M','jet.M'), 'F16':('L1J','M','fighter.M'),
                 'C172':('L1P','L','single.L'), 'BE20':('L2T','L/M','twin.LM'), 'C130':('L4T','M','propquad.M'),
                 'H60':('H2T','M','helicopter.M'), 'V22':('T2T','M','twin.M'), 'DA42':('L2P','L','twin.L')}
        icons = b.icons([{'Designator':code,'Description':description,'WTC':wake}
                         for code, (description, wake, _) in cases.items()])
        self.assertEqual({code: icons[code] for code in cases}, {code: icon for code, (*_, icon) in cases.items()})
        self.assertEqual((icons['BALL'], icons['GLID']), ('balloon.L', 'glider.L'))

    def test_curated_file_rejects_malformed_duplicate_and_long_entries(self):
        for body in ('C25B Cessna Citation CJ3\n', 'c25b\tCitation\n', 'C25B\t\n',
                     'C25B\tCitation\nC25B\tCitation\n', 'C25B\t'+'x'*29+'\n'):
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp)/'names.tsv'
                path.write_text('# comment\n\n'+body, encoding='utf-8')
                with self.assertRaises(ValueError):
                    b.load_curated(path)


if __name__ == '__main__':
    unittest.main()
