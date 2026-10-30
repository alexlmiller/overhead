#!/usr/bin/env python3
"""Build offline city labels from a locally downloaded OurAirports airports.csv."""
import csv
import json
import pathlib
import sys

# Served-city labels where the airport municipality differs from the familiar metro.
METROS = {'BZN': 'Bozeman', 'FCA': 'Kalispell', 'JFK': 'New York', 'LGA': 'New York',
          'EWR': 'Newark', 'DFW': 'Dallas–Fort Worth', 'DCA': 'Washington',
          'IAD': 'Washington', 'SFO': 'San Francisco', 'CDG': 'Paris', 'LHR': 'London'}
rows = list(csv.DictReader(pathlib.Path(sys.argv[1]).open(encoding='utf-8')))
cities = {}
# Skip closed facilities; only internationally identified airports, not local codes.
for row in rows:
    if row['type'] == 'closed' or not row['municipality'].strip():
        continue
    iata = row['iata_code'].strip()
    city = METROS.get(iata, row['municipality'].strip())
    for code in (iata, row.get('icao_code', '').strip()):
        if code:
            cities[code] = city
out = pathlib.Path(__file__).resolve().parents[1] / 'web/airport-cities.mjs'
out.write_text('// Generated from OurAirports public-domain data; see docs/architecture.md.\n'
               'export const AIRPORT_CITIES = ' + json.dumps(cities, ensure_ascii=False, sort_keys=True,
                                                            separators=(',', ':')) + ';\n', encoding='utf-8')
print(f'{len(cities)} airport identifiers; {out.stat().st_size} bytes')
