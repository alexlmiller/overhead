# Third-party notices

The MIT license covers Overhead's original code, not third-party services,
fonts, datasets, trademarks or imagery. The maintainer has confirmed distribution
terms for the bundled datasets and logos. Preserve their source attribution.

- **Instrument Serif / DM Sans:** unmodified Google Fonts TTFs, SIL Open Font
  License. License texts are in `web/fonts/`; [sources](web/fonts/README.md).
- **Aircraft types:** generated factual manufacturer/model/type data from
  [ICAO Doc 8643](https://doc8643.icao.int/), with the curated display-name table in
  `data/aircraft-type-names.tsv`. Generator: `scripts/build-aircraft-types.py`.
- **Airline designators and marks:** `data/airlines.txt` and locally bundled PNGs
  from [Jxck-S/airline-logos](https://github.com/Jxck-S/airline-logos), pinned by
  `scripts/fetch-airline-logos.py`. Airline names and logos belong to their
  respective owners, identify flights, and do not imply endorsement. This
  project does not relicense those marks under MIT.
- **Maps:** fetched at runtime from OpenStreetMap; visible attribution must be
  retained. [Copyright/data license](https://www.openstreetmap.org/copyright)
  and [tile usage policy](https://operations.osmfoundation.org/policies/tiles/).
- **Flight providers:** no live provider records, account credentials, or runtime
  route database are distributed. Runtime data access remains subject to each
  provider's terms; the software license does not grant provider permissions.
