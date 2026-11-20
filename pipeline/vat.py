"""VAT: the standard rate in each EU country, from the EU's own tax database, cross-checked.

Source of record: the European Commission's Taxes in Europe Database (TEDB), through its public
VAT retrieval web service. Second source: the open VAT list ibericode/vat-rates. The two must agree
on every country before anything is published.
"""
import json
import xml.etree.ElementTree as ET
from datetime import date, timedelta

from .countries import CODES, EU27, OPEN_VAT_LIST_CODE
from .errors import DataError

TEDB_URL = "https://ec.europa.eu/taxation_customs/tedb/ws/"
TEDB_PAGE = "https://ec.europa.eu/taxation_customs/tedb/"
SOAP_ACTION = "urn:ec.europa.eu:taxud:tedb:services:v1:VatRetrievalService/RetrieveVatRates"
NAMESPACE = "urn:ec.europa.eu:taxud:tedb:services:v1:IVatRetrievalService"
HEADERS = {"Content-Type": "text/xml; charset=UTF-8", "SOAPAction": SOAP_ACTION}

OPEN_VAT_LIST_URL = "https://raw.githubusercontent.com/ibericode/vat-rates/master/vat-rates.json"
OPEN_VAT_LIST_PAGE = "https://github.com/ibericode/vat-rates"

CHANGE_WINDOW_DAYS = 3 * 365 + 1  # standard-rate changes from the last three years are shown

# A fact the database's own note doesn't spell out, added to its regional entry.
REGION_NOTES = {"Canary Islands": "which are outside the EU VAT area"}

MIN_RATE, MAX_RATE = 15.0, 30.0  # EU law sets a 15% floor for the standard rate


def soap_request(codes, on):
    states = "".join(f"<t:isoCode>{code}</t:isoCode>" for code in codes)
    return (
        '<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" '
        f'xmlns:m="{NAMESPACE}" xmlns:t="{NAMESPACE}:types"><soapenv:Header/><soapenv:Body>'
        f"<m:retrieveVatRatesReqMsg><t:memberStates>{states}</t:memberStates>"
        f"<t:situationOn>{on.isoformat()}</t:situationOn></m:retrieveVatRatesReqMsg>"
        "</soapenv:Body></soapenv:Envelope>"
    ).encode("utf-8")


def _name(tag):
    return tag.rsplit("}", 1)[-1]


def parse_tedb(body):
    """Every rate record in a TEDB answer: country, STANDARD/REDUCED, rate type, value and note."""
    try:
        root = ET.fromstring(body)
    except ET.ParseError as error:
        raise DataError(f"the EU tax database sent something that is not XML ({error})") from None
    for element in root.iter():
        if _name(element.tag) == "Fault":
            text = " ".join(t.strip() for t in element.itertext() if t.strip())
            raise DataError(f"the EU tax database returned an error: {text[:200]}")
    records = []
    for element in root.iter():
        if _name(element.tag) != "vatRateResults":
            continue
        record = {"country": "", "type": "", "rate_type": "", "value": None, "comment": ""}
        for child in element:
            name = _name(child.tag)
            if name == "memberState":
                record["country"] = (child.text or "").strip()
            elif name == "type":
                record["type"] = (child.text or "").strip()
            elif name == "rate":
                for part in child:
                    if _name(part.tag) == "type":
                        record["rate_type"] = (part.text or "").strip()
                    elif _name(part.tag) == "value" and (part.text or "").strip():
                        record["value"] = float(part.text)
            elif name == "comment":
                record["comment"] = (child.text or "").strip()
        records.append(record)
    if not records:
        raise DataError("the EU tax database returned no VAT rates")
    return records


def region_name(comment):
    """'VAT - Canary Islands - ' -> 'Canary Islands'."""
    parts = [part.strip(" -") for part in comment.split(" - ")]
    return ", ".join(p for p in parts if p and p.upper() != "VAT") or comment.strip(" -")


def standard_rates(records, codes):
    """Mainland standard rate per country, plus any regional standard rates the database lists.

    The database can list more than one STANDARD rate for a country (Spain: 21%, and 7% for the
    Canary Islands). The mainland rate is the one without a regional note; there must be exactly one.
    """
    result = {}
    for code in codes:
        standard = [
            r for r in records
            if r["country"] == code and r["type"] == "STANDARD" and r["rate_type"] == "DEFAULT" and r["value"] is not None
        ]
        mainland = sorted({r["value"] for r in standard if not r["comment"]})
        if len(mainland) != 1:
            raise DataError(
                f"{EU27[code][0]}: expected one standard VAT rate without a regional note, found {mainland or 'none'}"
            )
        regional = sorted({(region_name(r["comment"]), r["value"]) for r in standard if r["comment"]})
        result[code] = {
            "rate": mainland[0],
            "regional": [{"region": n, "rate": v, "note": REGION_NOTES.get(n, "")} for n, v in regional],
            "change": None,
        }
    return result


def tedb_rates(fetch, codes, on):
    return standard_rates(parse_tedb(fetch(TEDB_URL, data=soap_request(codes, on), headers=HEADERS)), codes)


def open_list_periods(doc, code):
    key = OPEN_VAT_LIST_CODE.get(code, code)
    periods = (doc.get("items") or {}).get(key)
    if not periods:
        raise DataError(f"{EU27[code][0]} is missing from the open VAT list (looked for '{key}')")
    return sorted(periods, key=lambda period: period["effective_from"])


def open_list_rate(doc, code, on):
    current = [p for p in open_list_periods(doc, code) if p["effective_from"] <= on.isoformat()]
    if not current:
        raise DataError(f"{EU27[code][0]}: the open VAT list has no rate in force on {on.isoformat()}")
    return float(current[-1]["rates"]["standard"])


def last_standard_change(doc, code, on):
    """The latest change to the standard rate on or before `on`.

    Periods in the open list also start when only a reduced rate changes (Finland, 1 January 2026),
    so a change is dated only when the standard rate itself is different from the period before.
    """
    previous, change = None, None
    for period in open_list_periods(doc, code):
        if period["effective_from"] > on.isoformat():
            break
        rate = float(period["rates"]["standard"])
        if previous is not None and rate != previous:
            change = {"date": period["effective_from"], "from": previous, "to": rate}
        previous = rate
    return change


def pull(fetch, today):
    """Standard VAT for all 27 countries, cross-checked, with recent changes confirmed. Raises DataError."""
    rates = tedb_rates(fetch, CODES, today)
    for code, entry in rates.items():
        if not MIN_RATE <= entry["rate"] <= MAX_RATE:
            raise DataError(f"{EU27[code][0]}: a standard VAT rate of {entry['rate']:g}% is outside {MIN_RATE:g}-{MAX_RATE:g}%")

    try:
        open_list = json.loads(fetch(OPEN_VAT_LIST_URL))
    except json.JSONDecodeError as error:
        raise DataError(f"the open VAT list is not valid JSON ({error})") from None
    differences = []
    for code in CODES:
        second = open_list_rate(open_list, code, today)
        if second != rates[code]["rate"]:
            differences.append(f"{EU27[code][0]} {rates[code]['rate']:g}% vs {second:g}%")
    if differences:
        raise DataError("VAT rates differ between the EU tax database and the open VAT list: " + "; ".join(differences))

    confirmed, unconfirmed = [], []
    cutoff = today - timedelta(days=CHANGE_WINDOW_DAYS)
    for code in CODES:
        change = last_standard_change(open_list, code, today)
        if not change or date.fromisoformat(change["date"]) < cutoff:
            continue
        day = date.fromisoformat(change["date"])
        try:
            before = tedb_rates(fetch, [code], day - timedelta(days=1))[code]["rate"]
            after = tedb_rates(fetch, [code], day)[code]["rate"]
        except Exception:  # an unconfirmed change is simply not shown
            before = after = None
        if before == change["from"] and after == change["to"]:
            rates[code]["change"] = change
            confirmed.append(code)
        else:
            unconfirmed.append(code)

    by_name = lambda codes: ", ".join(EU27[c][0] for c in sorted(codes, key=lambda c: EU27[c][0]))  # noqa: E731
    checks = [
        {"ok": True, "text": "All 27 standard VAT rates match the open VAT list"},
        {"ok": True, "text": "Greece matched across codes EL and GR"},
    ]
    for code in CODES:
        for regional in rates[code]["regional"]:
            checks.append({"ok": True, "text": (
                f"{EU27[code][0]}: {regional['region']} {regional['rate']:g}% kept apart from {rates[code]['rate']:g}%"
            )})
    if confirmed:
        checks.append({"ok": True, "text": (
            f"Rate changes since {cutoff.year} confirmed in the EU database ({len(confirmed)})"
        )})
    if unconfirmed:
        checks.append({"ok": False, "text": f"Rate change not confirmed in the EU database, so not shown: {by_name(unconfirmed)}"})
    return {"rates": rates, "tedb_page": TEDB_PAGE, "open_list_page": OPEN_VAT_LIST_PAGE, "checks": checks}
