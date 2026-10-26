#!/usr/bin/env python3
"""Print proposed HA API payloads; does not contact HA or modify live objects."""
import json

REMOTE = 'remote.overhead_tv'
PLAYER = 'media_player.overhead_tv'
SESSION = 'input_select.office_aircraft_session'
SELECTED = 'input_text.office_aircraft_selected'
CANDIDATE = 'sensor.office_aircraft_candidate'
CURRENT = 'sensor.office_aircraft_current'
ART = 'com.vt.arttv.artmode'
BROWSER = 'com.phlox.tvwebbrowser'


def state(entity, value, attribute=None):
    out = {'condition': 'state', 'entity_id': entity, 'state': value}
    if attribute:
        out['attribute'] = attribute
    return out


def action(service, entity=None, **data):
    out = {'action': service}
    if entity:
        out['target'] = {'entity_id': entity}
    if data:
        out['data'] = data
    return out


def check(template):
    return {'condition': 'template', 'value_template': template}


def payloads():
    helpers = [
        {'helper_type': 'input_boolean', 'name': 'Office Aircraft Alerts',
         'icon': 'mdi:airplane'},
        {'helper_type': 'input_number', 'name': 'Office Aircraft Radius',
         'min_value': 1, 'max_value': 10, 'step': 0.5, 'initial': 3,
         'unit_of_measurement': 'mi', 'mode': 'box'},
        {'helper_type': 'input_select', 'name': 'Office Aircraft Session',
         'options': ['Inactive', 'Automatic', 'Manual'], 'initial': 'Inactive'},
        {'helper_type': 'input_text', 'name': 'Office Aircraft Selected',
         'max_value': 8, 'initial': ''},
        {'helper_type': 'input_text', 'name': 'Office Aircraft Recent',
         'max_value': 255, 'initial': '[]'},
    ]
    open_page = [
        state(REMOTE, 'on'),
        action('androidtv.adb_command', 'media_player.overhead_tv_adb',
               command='am start -a android.intent.action.VIEW '
               '-n com.phlox.tvwebbrowser/.activity.main.MainActivity '
               "-d 'https://homeassistant.example:8123/local/aircraft-display/index.html?office_tv=1&t={{ now().timestamp() | int }}' "
               '--ez com.phlox.tvwebbrowser.EXTRA_OPEN_IN_SAME_TAB true'),
    ]
    scripts = {
        'office_tv_planes': {
            'alias': 'Office TV: Planes', 'icon': 'mdi:airplane', 'mode': 'restart',
            'description': 'Open the local airspace map and recent sightings, waking the TV if needed. Manual view stays until changed.',
            'sequence': [
                # Manual view buttons wake the TV; automatic pop-ups never do.
                {'alias': 'Wake the TV if needed (manual view button)',
                 'action': 'script.office_tv_ensure_awake'},
                state(REMOTE, 'on'),
                action('script.turn_off', 'script.office_tv_aircraft_popup'),
                action('input_select.select_option', SESSION, option='Manual'),
                # Empty selection continuously follows the nearest plane in manual mode.
                action('input_text.set_value', SELECTED, value=''),
                *open_page,
            ],
        },
        'office_tv_aircraft_popup': {
            'alias': 'Office TV: Aircraft popup', 'mode': 'single',
            'max_exceeded': 'silent',
            'description': 'Automatic interruption of Art only; lock the triggering aircraft.',
            'sequence': [
                state('input_boolean.office_aircraft_alerts', 'on'),
                state('input_select.house_mode', 'Home'),
                state(REMOTE, 'on'), state(PLAYER, ART, 'app_id'),
                state(SESSION, 'Inactive'),
                {'variables': {'aircraft': "{{ states('sensor.office_aircraft_candidate') }}"}},
                check("{{ aircraft not in ['none', 'unknown', 'unavailable', ''] }}"),
                # Six IDs fit the helper's 255-character limit including JSON spaces.
                check("{{ aircraft not in (states('input_text.office_aircraft_recent') | "
                "from_json([]) | selectattr('t', 'gt', as_timestamp(now()) - 1200) | "
                "map(attribute='h') | list) }}"),
                action('input_text.set_value', SELECTED, value='{{ aircraft }}'),
                action('input_select.select_option', SESSION, option='Automatic'),
                action('input_text.set_value', 'input_text.office_aircraft_recent', value=
                       "{% set recent = states('input_text.office_aircraft_recent') | from_json([]) "
                       "| selectattr('t', 'gt', as_timestamp(now()) - 1200) | list %}"
                       "{{ (recent[-5:] + [dict(h=aircraft, t=as_timestamp(now()) | int)]) | to_json }}"),
                state('input_select.house_mode', 'Home'),
                state(PLAYER, ART, 'app_id'),
                *open_page,
            ],
        },
    }
    # The visible TV page calls this, rather than a server timer that cannot
    # distinguish aircraft from a different page opened in the same browser.
    scripts['office_tv_aircraft_finished'] = {
        'alias': 'Office TV: Aircraft return to art', 'mode': 'single',
        'description': 'Called by the visible aircraft TV page after 15 seconds without the selected plane.',
        'sequence': [
            state(SESSION, 'Automatic'), state(REMOTE, 'on'),
            state('input_select.house_mode', 'Home'),
            state(PLAYER, BROWSER, 'app_id'),
            {**state(CURRENT, 'none'), 'for': '00:00:15'},
            {**state(CANDIDATE, 'none'), 'for': '00:00:15'},
            action('input_select.select_option', SESSION, option='Inactive'),
            action('input_text.set_value', SELECTED, value=''),
            action('script.office_tv_art_mode'),
        ],
    }
    watched = [
        'art_mode', 'cameras', 'chickens', 'doorbell_view', 'entry', 'perimeter',
        'stacks', 'turn_off', 'wake_to_art',
    ]
    automations = {
        'office_tv_aircraft_arrival': {
            'id': 'office_tv_aircraft_arrival', 'alias': 'Office TV: Nearby aircraft',
            'description': 'Start once from Art while Home. Alerts remain off until the pilot is verified.',
            'triggers': [{'trigger': 'state', 'entity_id': CANDIDATE}],
            'conditions': [state('input_boolean.office_aircraft_alerts', 'on'),
                           state('input_select.house_mode', 'Home'),
                           state(SESSION, 'Inactive'), state(REMOTE, 'on'),
                           state(PLAYER, ART, 'app_id')],
            'actions': [action('script.office_tv_aircraft_popup')],
            'mode': 'single', 'max_exceeded': 'silent',
        },
        'office_tv_aircraft_cancel': {
            'id': 'office_tv_aircraft_cancel', 'alias': 'Office TV: Cancel aircraft session',
            'description': 'Doorbell, existing view scripts, TV app changes, and House Mode take priority.',
            'triggers': [
                {'trigger': 'state', 'entity_id': ['script.office_tv_' + x for x in watched],
                 'attribute': 'last_triggered', 'id': 'control'},
                {'trigger': 'state', 'entity_id': PLAYER, 'attribute': 'app_id', 'id': 'app'},
                {'trigger': 'state', 'entity_id': REMOTE, 'to': 'off', 'id': 'control'},
                {'trigger': 'state', 'entity_id': 'input_select.house_mode', 'id': 'mode'},
                {'trigger': 'state', 'entity_id': 'input_boolean.office_aircraft_alerts',
                 'to': 'off', 'id': 'control'},
                {'trigger': 'homeassistant', 'event': 'start', 'id': 'control'},
            ],
            'conditions': [{'condition': 'or', 'conditions': [
                {'condition': 'trigger', 'id': 'control'},
                {'condition': 'and', 'conditions': [
                    {'condition': 'trigger', 'id': 'app'},
                    {'condition': 'not', 'conditions': [state(PLAYER, BROWSER, 'app_id')]},
                ]},
                {'condition': 'and', 'conditions': [
                    {'condition': 'trigger', 'id': 'mode'},
                    {'condition': 'not', 'conditions': [state('input_select.house_mode', 'Home')]},
                ]},
            ]}],
            'actions': [action('script.turn_off', 'script.office_tv_aircraft_popup'),
                        action('input_select.select_option', SESSION, option='Inactive'),
                        action('input_text.set_value', SELECTED, value='')],
            'mode': 'restart',
        },
    }
    # Merge only this view into Desktop; never replace its other views.
    dashboard_view = {
        'url_path': 'lovelace-desktop',
        'view': {
            'title': 'Aircraft', 'path': 'aircraft', 'icon': 'mdi:airplane',
            'type': 'sections', 'max_columns': 1,
            'sections': [{'type': 'grid', 'cards': [
                {'type': 'entities', 'entities': ['input_boolean.office_aircraft_alerts',
                                                'input_number.office_aircraft_radius', SESSION]},
                {'type': 'button', 'entity': 'script.office_tv_planes', 'name': 'Planes',
                 'tap_action': {'action': 'perform-action', 'perform_action': 'script.office_tv_planes'}},
            ]}],
        },
    }
    return {'helpers': helpers, 'scripts': scripts, 'automations': automations,
            'dashboard_view': dashboard_view}


if __name__ == '__main__':
    print(json.dumps(payloads(), indent=2))
