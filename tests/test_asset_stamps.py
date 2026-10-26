"""The TV's 31-day HA cache only refreshes files whose URL changes."""
import importlib.util
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('stamp_assets', ROOT/'scripts/stamp-assets.py')
s = importlib.util.module_from_spec(spec)
spec.loader.exec_module(s)


class AssetStampTests(unittest.TestCase):
    def test_references_carry_current_content_hashes(self):
        for name in s.STAMPED:
            text = (s.WEB/name).read_text(encoding='utf-8')
            self.assertEqual(s.stamp(text), text, f'{name} has stale ?v= stamps; run make stamp')

    def test_every_local_module_and_stylesheet_reference_is_stamped(self):
        for name in s.STAMPED:
            text = (s.WEB/name).read_text(encoding='utf-8')
            unstamped = re.findall(r"""["'](?:\./)?[\w/-]+\.(?:mjs|css)["']""", text)
            self.assertEqual(unstamped, [], name)

    def test_a_changed_leaf_changes_every_url_above_it(self):
        display = (s.WEB/'display.mjs').read_text(encoding='utf-8')
        with self.subTest('stamp tracks content'):
            self.assertIn(f"core.mjs?v={s.digest(s.WEB/'core.mjs')}", display)
        edited = s.stamp(display.replace('core.mjs?v=', 'core.mjs?v=old'))
        self.assertEqual(edited, display)


if __name__ == '__main__':
    unittest.main()
