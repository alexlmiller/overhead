#!/usr/bin/env python3
"""Read-only seven-day route diagnostics; run locally against the HA-owned journal."""
import argparse
import json
import pathlib
import sqlite3
import time

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('database', type=pathlib.Path)
args = parser.parse_args()
cutoff = time.time()-7*86400
with sqlite3.connect(args.database.resolve().as_uri()+'?mode=ro', uri=True) as db:
    db.row_factory = sqlite3.Row
    summary = dict(db.execute('SELECT COUNT(*) AS visits,MIN(first_seen) AS earliest,MAX(last_seen) AS latest '
                              'FROM visits WHERE last_seen>=?', (cutoff,)).fetchone())
    summary['decisions'] = [dict(row) for row in db.execute('SELECT source,reason,COUNT(DISTINCT visit_id) AS visits '
                           'FROM decisions WHERE last_at>=? GROUP BY source,reason ORDER BY source,reason', (cutoff,))]
print(json.dumps(summary, indent=2))
