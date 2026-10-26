#!/usr/bin/env python3
"""Build web/aircraft-types.mjs: display names and map icons for type designators.

Curated names come from data/aircraft-type-names.tsv. Every other ICAO Doc 8643
designator gets a generated "Manufacturer Model" name, so unusual types still
read as words. Icons follow each designator's ICAO description (e.g. L2J), wake
category and the engine-placement lists below. Downloads the ICAO list unless
--icao names a saved copy.
"""
import argparse
import collections
import datetime
import json
import pathlib
import re
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
CURATED = ROOT/"data/aircraft-type-names.tsv"
OUTPUT = ROOT/"web/aircraft-types.mjs"
ICAO_URL = "https://doc8643.icao.int/external/aircrafttypes"
# Codes that ADS-B aircraft databases use for types without an ICAO designator.
SPECIAL_ICONS = {"BALL": "balloon.L", "SHIP": "balloon.M", "GLID": "glider.L", "ULAC": "single.L",
                 "PARA": "single.L", "GYRO": "helicopter.L", "UHEL": "helicopter.L", "DRON": "helicopter.L",
                 "KODI": "single.L"}
SPECIAL = set(SPECIAL_ICONS)
# ICAO descriptions do not record engine placement: rear-mounted business and
# regional jets, and military jets, are listed explicitly.
REAR_ENGINE = {
    "C500", "C501", "C510", "C525", "C25A", "C25B", "C25C", "C25M", "C550", "C551", "C55B", "C560", "C56X",
    "C650", "C680", "C68A", "C700", "C750", "E50P", "E55P", "E545", "E550", "E35L", "E135", "E145", "E45X",
    "CL30", "CL35", "CL60", "GL5T", "GLEX", "GL7T", "LJ24", "LJ25", "LJ28", "LJ31", "LJ35", "LJ40", "LJ45",
    "LJ55", "LJ60", "LJ70", "LJ75", "GLF2", "GLF3", "GLF4", "GLF5", "GLF6", "G150", "G280", "GALX", "ASTR",
    "GA5C", "GA6C", "GA7C", "GA8C", "WW24", "FA10", "FA20", "FA50", "F900", "F2TH", "FA7X", "FA8X", "FA6X",
    "H25A", "H25B", "H25C", "HA4T", "PRM1", "BE40", "HDJT", "EA50", "SF50", "PC24", "SBR1", "MU30",
    "CRJ1", "CRJ2", "CRJ7", "CRJ9", "CRJX", "MD81", "MD82", "MD83", "MD87", "MD88", "MD90", "DC91", "DC92",
    "DC93", "DC94", "DC95", "B712", "B721", "B722", "F28", "F70", "F100", "YK40", "T134",
}
FIGHTERS = {"F15", "F16", "F18H", "F18S", "F22", "F35", "F5", "F14", "F4", "F117", "A10", "A4", "T38", "EUFI",
            "MRF1", "MIR2", "RFAL", "SU27", "MG29", "TOR", "AJET", "HAWK", "L39", "L29"}
MAX_LENGTH = 28
BRANDS = {
    "AIRBUS HELICOPTERS": "Airbus", "AIRBUS HELICOPTERS-KAWASAKI": "Airbus", "BOEING VERTOL": "Boeing",
    "BRITISH AEROSPACE": "BAe", "BEECH": "Beechcraft", "GULFSTREAM AEROSPACE": "Gulfstream",
    "NORTH AMERICAN ROCKWELL": "Rockwell", "NHI": "NHIndustries",
}
ACRONYMS = {"ATR", "BAE", "BRM", "CASA", "COMAC", "EAA", "FMA", "HAL", "IAI", "ICP", "JMB", "KAI", "MBB",
            "NAF", "PZL", "SIAI", "TAI", "TL", "AIDC", "AVIC", "CAC", "HAI", "RAF", "SAI", "UTVA"}
WORD = re.compile(r"[A-Za-z][a-z]{2,}")


def load_curated(path=CURATED):
    names = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip() or line.startswith("#"):
            continue
        code, _, name = line.partition("\t")
        if not re.fullmatch(r"[A-Z0-9]{2,4}", code) or not name.strip() or name != name.strip():
            raise ValueError(f"{path.name}:{number}: expected DESIGNATOR<TAB>Name")
        if code in names:
            raise ValueError(f"{path.name}:{number}: duplicate {code}")
        if len(name) > MAX_LENGTH:
            raise ValueError(f"{path.name}:{number}: {code} name exceeds {MAX_LENGTH} characters")
        names[code] = name
    return names


def brand(manufacturer):
    name = re.sub(r"\s*\(\d+\)$", "", manufacturer).strip()
    if name in BRANDS:
        return BRANDS[name]
    words = []
    for word in name.split():
        if word in ACRONYMS:
            words.append(word)
        elif word.startswith("MC") and len(word) > 3:
            words.append("Mc"+word[2:].capitalize())
        else:
            words.append("-".join(part.capitalize() for part in word.split("-")))
    return " ".join(words)


def shorten(make, model):
    """Brand and model; the model alone when both do not fit, then whole words."""
    name = f"{make} {model}".strip()
    if len(name) > MAX_LENGTH:
        name = model
    while len(name) > MAX_LENGTH and " " in name:
        name = name.rsplit(" ", 1)[0]
    return name[:MAX_LENGTH]


def generated(rows):
    """One readable name per designator from its main manufacturer's family name."""
    maker_types = collections.Counter()
    for maker, code in {(r["ManufacturerCode"], r["Designator"]) for r in rows}:
        maker_types[maker] += 1
    by_code = collections.defaultdict(list)
    for r in rows:
        by_code[r["Designator"]].append(r)
    alnum = lambda text: re.sub(r"[^A-Z0-9]", "", text.upper())
    names = {}
    for code, entries in by_code.items():
        makers = collections.Counter(r["ManufacturerCode"] for r in entries)
        # Most variants first; a wider catalogue separates the OEM from a licensee.
        primary = max(makers, key=lambda m: (makers[m], maker_types[m], m))
        family = collections.Counter(w for r in entries for w in set(WORD.findall(r["ModelFullName"])))
        models = {re.sub(r"\s*\([^)]*\)", "", r["ModelFullName"]).strip()
                  for r in entries if r["ManufacturerCode"] == primary}
        digits = re.sub(r"\D", "", code)
        # Prefer the model named by the designator itself ("DC-6" over "R6D Liftmaster"),
        # then its number, then the most shared family name, then brevity.
        model = max(sorted(models), key=lambda m: (alnum(code) in {alnum(w) for w in m.split()},
                                                   bool(digits) and digits in re.sub(r"\D", "", m),
                                                   max((family[w] for w in WORD.findall(m)), default=0), -len(m)))
        make, words = brand(primary), re.sub(r"\s+", " ", model).split()
        # "G-6 Gulfstream G650" by Gulfstream reads as "Gulfstream G650".
        lead = next((i for i, w in enumerate(words) if w.lower() == make.split()[0].lower()), None)
        names[code] = shorten("", " ".join(words[lead:])) if lead is not None else shorten(make, " ".join(words))
    return names


def require(rows, codes, what):
    """Listed designators must exist in ICAO Doc 8643 (catches typos)."""
    unknown = sorted(set(codes)-{r["Designator"] for r in rows}-SPECIAL)
    if unknown:
        raise ValueError(f"{what} missing from ICAO Doc 8643: "+", ".join(unknown))


def build(rows, curated):
    """All designators; curated names win."""
    require(rows, curated, "Curated designators")
    return {**generated(rows), **curated}


def icons(rows):
    """Map icon per designator as "shape.wake", e.g. "jet.L" for a Citation CJ3."""
    by_code = collections.defaultdict(list)
    for r in rows:
        by_code[r["Designator"]].append(r)
    result = dict(SPECIAL_ICONS)
    for code, entries in by_code.items():
        description = collections.Counter(r["Description"] for r in entries).most_common(1)[0][0]
        wake = collections.Counter(r["WTC"] for r in entries).most_common(1)[0][0].replace("/", "")
        kind, engines, power = (description+"---")[:3]
        if kind in "HG":
            shape = "helicopter"
        elif code in FIGHTERS:
            shape = "fighter"
        elif power == "J":
            shape = ("jet" if code in REAR_ENGINE or (wake == "L" and engines in "12") else
                     "quad" if engines in "4568" else "widebody" if wake in ("H", "J") else "airliner")
        elif engines in "4568":
            shape = "propquad"
        elif engines in "23" or kind == "T":
            shape = "twin"
        else:
            shape = "single"
        result[code] = f"{shape}.{wake if wake in ('L', 'LM', 'M', 'H', 'J') else 'M'}"
    return result


def render(names, icon_map, retrieved):
    lines = [f"{json.dumps(code)}:{json.dumps(name)}" for code, name in sorted(names.items())]
    groups = collections.defaultdict(list)
    for code, icon in sorted(icon_map.items()):
        groups[icon].append(code)
    icon_lines = [f"{json.dumps(icon)}:{json.dumps(' '.join(codes))}" for icon, codes in sorted(groups.items())]
    return ("// Generated by scripts/build-aircraft-types.py; edit data/aircraft-type-names.tsv and run\n"
            f"// `make aircraft-types`. Other names derive from ICAO Doc 8643, retrieved {retrieved}.\n"
            "// Null prototype: feed-supplied codes such as \"constructor\" never resolve.\n"
            "export const AIRCRAFT_TYPES=Object.freeze(Object.assign(Object.create(null),{\n"
            + ",\n".join(lines) + "\n}));\n"
            "// Map icons grouped as \"shape.wake\"; wake is the ICAO category (L, LM, M, H, J).\n"
            "export const AIRCRAFT_ICONS=Object.freeze({\n" + ",\n".join(icon_lines) + "\n});\n")


def download():
    request = urllib.request.Request(ICAO_URL, data=b"", method="POST",
                                     headers={"User-Agent": "Overhead aircraft type build"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--icao", type=pathlib.Path, help="saved ICAO Doc 8643 JSON instead of downloading")
    args = parser.parse_args()
    rows = json.loads(args.icao.read_text(encoding="utf-8")) if args.icao else download()
    if not isinstance(rows, list) or len(rows) < 1000 or not all(r.get("Designator") for r in rows):
        raise SystemExit("ICAO response is not the expected aircraft type list")
    curated = load_curated()
    try:
        require(rows, REAR_ENGINE | FIGHTERS, "Icon designators")
        names, icon_map = build(rows, curated), icons(rows)
    except ValueError as error:
        raise SystemExit(str(error)) from None
    OUTPUT.write_text(render(names, icon_map, datetime.date.today().isoformat()), encoding="utf-8")
    print(f"Wrote {len(names)} names ({len(curated)} curated) and {len(icon_map)} icons to {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
