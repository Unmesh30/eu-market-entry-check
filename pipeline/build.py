"""Pull every source, check it, and build the one-page dashboard.

    python -m pipeline.build --data data/latest.json --out site

If a source fails a check, the page keeps that source's last good data and says so on screen.
"""
import argparse
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

from . import eurostat, fx, vat
from .countries import CURRENCY_NAMES, EU27, currencies
from .http import fetch as http_fetch

ROOT = Path(__file__).resolve().parent.parent
SITE_SOURCE = ROOT / "site_src"

SOURCE_LABELS = {"eurostat": "Eurostat", "vat": "VAT", "fx": "exchange-rate"}

# A rule rather than a data feed: written down from the European Commission's guidance with its end
# date, so the page stops showing it by itself once it expires.
CUSTOMS_RULE = {
    "from": "2026-07-01",
    "until": "2028-07-01",
    "duty_eur": 3,
    "max_value_eur": 150,
    "url": (
        "https://taxation-customs.ec.europa.eu/news/guidance-and-legal-text-temporary-flat-fee-"
        "low-value-imports-which-will-apply-until-1-july-2028-2026-06-08_en"
    ),
    "checked": "2026-11-20",
}

AUTHOR = {
    "name": "Unmesh Achar",
    "linkedin": "https://www.linkedin.com/in/unmesh-achar-319467210/",
    "code": "https://github.com/Unmesh30/eu-market-entry-check",
}


def collect(fetch, now, previous=None):
    """Pull and check every source. A source that fails keeps its last good data and adds a warning."""
    today = now.date()
    stamp = now.strftime("%Y-%m-%dT%H:%MZ")
    pulls = {
        "eurostat": lambda: eurostat.pull(fetch, today),
        "vat": lambda: vat.pull(fetch, today),
        "fx": lambda: fx.pull(fetch, today, currencies()),
    }
    data = {
        "generated_at": stamp,
        "warnings": [],
        "countries": {code: {"name": name, "currency": currency} for code, (name, currency) in EU27.items()},
        "currency_names": CURRENCY_NAMES,
        "flag_meanings": eurostat.FLAG_MEANINGS,
        "customs": CUSTOMS_RULE,
        "author": AUTHOR,
        "sources": {},
    }
    for name, pull in pulls.items():
        try:
            block = pull()
            block["pulled_at"] = stamp
            block["fresh"] = True
        except Exception as error:  # keep this source's last good data, and say so
            old = ((previous or {}).get("sources") or {}).get(name)
            if not old:
                raise
            block = {**old, "fresh": False}
            data["warnings"].append(
                f"Today's {SOURCE_LABELS[name]} update failed ({error}). "
                f"Showing the last good {SOURCE_LABELS[name]} data, pulled {old['pulled_at']}."
            )
        data["sources"][name] = block
    return data


def render(data):
    """The page template with the calculator code and the data put in."""
    page = (SITE_SOURCE / "index.html").read_text(encoding="utf-8")
    calc = (SITE_SOURCE / "calc.js").read_text(encoding="utf-8")
    if "/*CALC*/" not in page or "__DATA__" not in page:
        raise RuntimeError("site_src/index.html is missing its /*CALC*/ or __DATA__ marker")
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return page.replace("/*CALC*/", calc).replace("__DATA__", payload)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Pull, check and build the EU market-entry check.")
    parser.add_argument("--data", default="data/latest.json", help="last good data; updated in place")
    parser.add_argument("--out", default="site", help="folder for the built page")
    args = parser.parse_args(argv)

    data_path = Path(args.data)
    previous = json.loads(data_path.read_text(encoding="utf-8")) if data_path.exists() else None
    data = collect(http_fetch, datetime.now(timezone.utc), previous)

    data_path.parent.mkdir(parents=True, exist_ok=True)
    data_path.write_text(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "index.html").write_text(render(data), encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")
    preview = ROOT / "docs" / "preview.png"  # the picture shown when the link is shared
    if preview.exists():
        shutil.copyfile(preview, out / "preview.png")

    for warning in data["warnings"]:
        print(f"::warning::{warning}")
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as handle:
            handle.write(f"warnings={len(data['warnings'])}\n")
    print(f"Built {out / 'index.html'} with data pulled {data['generated_at']} ({len(data['warnings'])} warning(s))")


if __name__ == "__main__":
    main()
