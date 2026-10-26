"""The airline list stays valid and in sync with the generated page module."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('fetch_logos', ROOT/'scripts/fetch-airline-logos.py')
f = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f)


class AirlineTests(unittest.TestCase):
    def test_generated_module_matches_the_list_and_bundled_logos(self):
        airlines = f.load_airlines()
        logos = [code for code in airlines if (f.LOGOS/f'{code}.png').exists()]
        self.assertEqual(f.MODULE.read_text(encoding='utf-8'), f.render(logos, airlines), 'run make airlines')
        self.assertEqual((airlines['UAL'], airlines['SKW'], airlines['EJA']), ('UA', 'OO', ''))

    def test_list_rejects_malformed_or_duplicate_entries(self):
        for body in ('UAL UA\n', 'UA UA United\n', 'UAL UAL United\n', 'UAL ua United\n', 'UAL UA United\nUAL UA Again\n'):
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp)/'airlines.txt'
                path.write_text('# comment\n\n'+body, encoding='utf-8')
                with self.assertRaises(ValueError, msg=body):
                    f.load_airlines(path)


if __name__ == '__main__':
    unittest.main()
