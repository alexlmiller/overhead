#!/usr/bin/env python3
"""Build a separate installation tree from public source plus local JSON settings."""
import argparse
import ipaddress
import json
from pathlib import Path
import re
import shutil
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
DEFAULTS = {
    'remote': 'remote.overhead_tv', 'player': 'media_player.overhead_tv',
    'adb_player': 'media_player.overhead_tv_adb', 'house_mode': 'input_select.house_mode',
    'wake_script': 'script.office_tv_ensure_awake', 'art_script': 'script.office_tv_art_mode',
    'base_url': 'https://homeassistant.example:8123', 'tv_addresses': [],
    'use_bzn_board': False, 'key_file': None,
}


def build(config, output):
    if not isinstance(config, dict) or set(config)-set(DEFAULTS):
        raise ValueError('Unknown configuration keys')
    settings = {**DEFAULTS, **config}
    for key in ('remote', 'player', 'adb_player', 'house_mode', 'wake_script', 'art_script'):
        value = settings[key]
        if not isinstance(value, str) or not re.fullmatch(r'[a-z_]+\.[a-z0-9_]+', value):
            raise ValueError('Invalid entity ID: '+key)
        if value.split('.')[0] != DEFAULTS[key].split('.')[0]:
            raise ValueError('Wrong entity domain: '+key)
    url = settings['base_url']
    if not isinstance(url, str) or not re.fullmatch(r'https?://[A-Za-z0-9.\-\[\]:]+', url) or not urlparse(url).hostname:
        raise ValueError('base_url must be an HTTP(S) origin without credentials, path or query')
    if not isinstance(settings['tv_addresses'], list):
        raise ValueError('tv_addresses must be a list of exact IP addresses')
    addresses = [str(ipaddress.ip_address(v)) for v in settings['tv_addresses']]
    if not isinstance(settings['use_bzn_board'], bool):
        raise ValueError('use_bzn_board must be boolean')
    key_file = settings['key_file']
    if key_file is not None and (not isinstance(key_file, str) or not key_file.startswith('/')):
        raise ValueError('key_file must be an absolute path, not a key')
    output = Path(output).resolve()
    if output == ROOT or ROOT in output.parents or output.exists():
        raise ValueError('output must be a new directory outside the source tree')
    output.mkdir(parents=True)
    for directory in ('web', 'custom_components', 'home_assistant', 'scripts'):
        shutil.copytree(ROOT/directory, output/directory, ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    replacements = {DEFAULTS[k]: settings[k] for k in ('remote','player','adb_player','house_mode','wake_script','art_script','base_url')}
    for name in ('web/core.mjs','custom_components/office_aircraft_routes/model.py','scripts/office-aircraft-config.py'):
        path = output/name
        text = path.read_text()
        for old, new in sorted(replacements.items(), key=lambda item: len(item[0]), reverse=True):
            text = text.replace(old, new)
        if name.endswith('model.py'):
            needle = 'TV_ADDRESSES = frozenset()'
            if text.count(needle) != 1:
                raise ValueError('Unexpected TV configuration marker')
            text = text.replace(needle, 'TV_ADDRESSES = frozenset(map(tv_address, '+repr(addresses)+'))')
        path.write_text(text)
    path = output/'custom_components/office_aircraft_routes/__init__.py'
    text = path.read_text()
    needle = 'options.get("use_bzn_board", False)'
    if text.count(needle) != 1:
        raise ValueError('Unexpected provider configuration marker')
    path.write_text(text.replace(needle, 'options.get("use_bzn_board", '+repr(settings['use_bzn_board'])+')'))
    package = {'office_aircraft_routes': {'key_file':key_file} if key_file else {},
               'recorder': {'exclude': {'entities':['sensor.office_aircraft_routes']}}}
    (output/'home_assistant/packages/aircraft-routes-package.yaml').write_text(json.dumps(package,indent=2)+'\n')
    # Import locally so source and configured assets share the same stamp algorithm.
    import importlib.util
    spec = importlib.util.spec_from_file_location('stamp', output/'scripts/stamp-assets.py')
    stamp = importlib.util.module_from_spec(spec); spec.loader.exec_module(stamp)
    stamp.main()
    return output

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        print(build(json.loads(args.config.read_text()), args.output))
    except (ValueError, OSError) as error:
        parser.exit(1, str(error)+'\n')
