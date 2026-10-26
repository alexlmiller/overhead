#!/usr/bin/env python3
"""Stamp web/ module and stylesheet references with content hashes (?v=<hash>).

HA serves /local with a 31-day cache, so a changed file must be requested under a
new URL. Files are stamped leaves first: display.mjs's own hash covers its
stamped imports, then index.html picks it up. `make test` fails while a stamp is
stale; run `make stamp` after editing web/.
"""
import hashlib
import pathlib
import re
import sys

WEB = pathlib.Path(__file__).resolve().parents[1]/"web"
REFERENCE = re.compile(r"(?P<path>(?:\./)?[\w/-]+\.(?:mjs|css))\?v=[\w-]+")
STAMPED = ("display.mjs", "index.html")  # dependency order


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()[:10]


def stamp(text, base=WEB):
    return REFERENCE.sub(lambda m: f"{m['path']}?v={digest(base/m['path'])}", text)


def main():
    check = "--check" in sys.argv[1:]
    stale = []
    for name in STAMPED:
        path = WEB/name
        text = path.read_text(encoding="utf-8")
        stamped = stamp(text)
        if stamped != text:
            stale.append(name)
            if not check:
                path.write_text(stamped, encoding="utf-8")
    if check and stale:
        raise SystemExit("Stale asset stamps in "+", ".join(stale)+"; run make stamp")
    print(("Stale: " if check else "Stamped: ")+(", ".join(stale) or "none"))


if __name__ == "__main__":
    main()
