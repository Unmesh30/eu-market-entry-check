"""Exchange rates: what 100,000 in each EU country's currency is worth in US dollars and pounds.

Source: the European Central Bank's euro reference rates for the last 90 days, published every
working day at around 16:00 CET.
"""
import xml.etree.ElementTree as ET
from datetime import date

from .errors import DataError

ECB_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist-90d.xml"
ECB_PAGE = "https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html"
CUBE = "{http://www.ecb.int/vocabulary/2002-08-01/eurofxref}Cube"
TARGETS = ("USD", "GBP")
AMOUNT = 100_000
MAX_AGE_DAYS = 7  # weekends and holidays leave gaps; a week without rates means the feed has stopped
MAX_DAILY_MOVE = 0.10  # a 10% move in one day is far more likely a bad feed than a market move


def day_text(iso):
    """'2026-11-20' -> '20 Nov 2026'."""
    day = date.fromisoformat(iso)
    return f"{day.day} {day:%b %Y}"


def parse_ecb(body):
    """{date: {currency: units per euro}} from the ECB feed."""
    try:
        root = ET.fromstring(body)
    except ET.ParseError as error:
        raise DataError(f"the ECB feed is not valid XML ({error})") from None
    days = {}
    for cube in root.iter(CUBE):
        day = cube.get("time")
        if day:
            days[day] = {
                child.get("currency"): float(child.get("rate"))
                for child in cube
                if child.get("currency") and child.get("rate")
            }
    if not days:
        raise DataError("the ECB feed had no rates")
    return days


def value_series(days, local, target):
    """[(date, value of AMOUNT in `local` currency, expressed in `target`)] for days with both rates."""
    series = []
    for day in sorted(days):
        rates = days[day]
        if target in rates and (local == "EUR" or local in rates):
            per_euro = 1.0 if local == "EUR" else rates[local]
            series.append((day, AMOUNT * rates[target] / per_euro))
    return series


def pull(fetch, today, local_currencies):
    """Value of 100,000 of each local currency in USD and GBP, today and over 90 days. Raises DataError."""
    days = parse_ecb(fetch(ECB_URL))
    latest = max(days)
    age = (today - date.fromisoformat(latest)).days
    if age > MAX_AGE_DAYS:
        raise DataError(f"the newest ECB rates are from {latest}, {age} days old")
    needed = set(TARGETS) | {c for c in local_currencies if c != "EUR"}
    missing = sorted(needed - set(days[latest]))
    if missing:
        raise DataError(f"the ECB rates for {latest} have nothing for {', '.join(missing)}")
    ordered = sorted(days)
    for currency in sorted(needed):
        points = [(day, days[day][currency]) for day in ordered if currency in days[day]]
        for (day0, rate0), (day1, rate1) in zip(points, points[1:]):
            if abs(rate1 / rate0 - 1) > MAX_DAILY_MOVE:
                raise DataError(f"{currency} moved more than {MAX_DAILY_MOVE:.0%} between {day0} and {day1}")

    per_amount = {}
    for local in sorted(set(local_currencies)):
        per_amount[local] = {}
        for target in TARGETS:
            series = value_series(days, local, target)
            values = [value for _, value in series]
            low, high = min(values), max(values)
            per_amount[local][target] = {
                "now": series[-1][1],
                "date": series[-1][0],
                "low": low,
                "high": high,
                "range_pct": (high - low) / low * 100,
            }

    non_euro = sorted(c for c in set(local_currencies) if c != "EUR")
    checks = [
        {"ok": True, "text": f"ECB rates to {day_text(latest)}; all {len(non_euro)} non-euro currencies",
         "detail": f"{len(ordered)} working days from {day_text(ordered[0])}: {', '.join(non_euro)}"},
        {"ok": True, "text": f"No one-day move over {MAX_DAILY_MOVE:.0%} (a sign of a bad feed)"},
    ]
    return {
        "latest": latest,
        "first": ordered[0],
        "days": len(ordered),
        "amount": AMOUNT,
        "per_amount": per_amount,
        "page": ECB_PAGE,
        "checks": checks,
    }
