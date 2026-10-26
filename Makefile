PYTHON ?= python3
NODE ?= node
PORT ?= 8767

.PHONY: test test-python test-web serve stamp aircraft-types airline-logos airlines

test: test-python test-web

test-python:
	$(PYTHON) -m unittest discover -s tests -p 'test_*.py'

test-web:
	$(NODE) --test tests/test-office-aircraft-display.mjs tests/test-office-aircraft-routes.mjs tests/test-aircraft-types.mjs
	$(NODE) tests/test-office-aircraft-session.js

serve:
	$(PYTHON) -m http.server $(PORT) --bind 127.0.0.1 --directory web

# Refresh ?v= content hashes in web/ after editing it; tests fail while stale.
stamp:
	$(PYTHON) scripts/stamp-assets.py

# Regenerate web/aircraft-types.mjs; downloads ICAO Doc 8643 unless ICAO=saved.json.
aircraft-types:
	$(PYTHON) scripts/build-aircraft-types.py $(if $(ICAO),--icao $(ICAO))
	$(PYTHON) scripts/stamp-assets.py

# Refetch bundled airline logos for data/airlines.txt; `airlines` regenerates offline.
airline-logos:
	$(PYTHON) scripts/fetch-airline-logos.py
	$(PYTHON) scripts/stamp-assets.py

airlines:
	$(PYTHON) scripts/fetch-airline-logos.py --offline
	$(PYTHON) scripts/stamp-assets.py
