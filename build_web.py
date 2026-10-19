#!/usr/bin/env python3
"""
Build the hosted page: inject exported data into the HTML template.

    python3 export_web.py    # run the engine, write web_data.json
    python3 build_web.py     # inject it into web/template.html -> web/index.html

Keeping the template free of data means the page markup stays editable by hand
while the figures are refreshed by re-running the exporter.
"""

from __future__ import annotations

import json
import os
import sys

TEMPLATE = os.path.join("web", "template.html")
OUTPUT = os.path.join("web", "index.html")
DATA = "web_data.json"


def main() -> int:
    for path in (TEMPLATE, DATA):
        if not os.path.exists(path):
            print(f"Missing {path}. Run export_web.py first.", file=sys.stderr)
            return 1

    template = open(TEMPLATE, encoding="utf-8").read()
    if "__DATA__" not in template:
        print(f"{TEMPLATE} has no __DATA__ placeholder.", file=sys.stderr)
        return 1

    raw = open(DATA, encoding="utf-8").read()
    payload = json.loads(raw)  # fail loudly on malformed data

    # "</script>" anywhere inside the JSON would close the tag early and break
    # the page, so it is escaped. The sequence is still valid JSON.
    safe = raw.replace("</script>", "<\\/script>")

    html = template.replace("__DATA__", safe)
    open(OUTPUT, "w", encoding="utf-8").write(html)

    print(f"Built {OUTPUT} — {len(payload['companies'])} companies, "
          f"{len(html) / 1024:.0f} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
