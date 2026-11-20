"""A simulated copy of every source, so the pipeline can be tested without the network.

The simulated answers use the real formats (Eurostat JSON-stat 2.0, the EU tax database's SOAP XML,
the open VAT list's JSON and the ECB's XML feed). The VAT rates and rate changes are the real ones
as of November 2026; the Eurostat and exchange-rate numbers are made up.
"""
import json
import math
from datetime import date, timedelta
from urllib.parse import parse_qs, urlparse

import pytest

from pipeline import eurostat, fx, vat
from pipeline.countries import CODES, OPEN_VAT_LIST_CODE

TODAY = date(2026, 11, 20)

# Standard VAT rate history: (first day in force, rate). Real rates, November 2026.
VAT_HISTORY = {code: [("0000-01-01", rate)] for code, rate in {
    "AT": 20, "BE": 21, "BG": 20, "CY": 19, "CZ": 21, "DE": 19, "DK": 25, "EE": 22, "EL": 23, "ES": 21,
    "FI": 24, "FR": 20, "HR": 25, "HU": 27, "IE": 23, "IT": 22, "LT": 21, "LU": 17, "LV": 21, "MT": 18,
    "NL": 21, "PL": 23, "PT": 23, "RO": 19, "SE": 25, "SI": 22, "SK": 20,
}.items()}
VAT_HISTORY["EE"].append(("2025-07-01", 24))
VAT_HISTORY["EL"].append(("2016-06-01", 24))
VAT_HISTORY["FI"].append(("2024-09-01", 25.5))
VAT_HISTORY["LU"] += [("2023-01-01", 16), ("2024-01-01", 17)]
VAT_HISTORY["RO"].append(("2025-08-01", 21))
VAT_HISTORY["SK"].append(("2025-01-01", 23))
# Periods in the open VAT list that only change a reduced rate (the standard rate stays the same).
REDUCED_ONLY_PERIODS = {"FI": "2026-01-01", "CZ": "2024-01-01"}

PHYSICAL = {p["indicator"] for p in eurostat.PRODUCTS if p["kind"] == "physical"}

# Comments the EU tax database puts on some countries' main standard rate (as returned in November 2026).
LEGAL_NOTES = {
    "BE": "&lt;p&gt;Article 1, paragraph 1, of the Royal Decree n° 20 of 20 July 1970&lt;/p&gt;",
    "CZ": "&lt;p&gt;Art. 47 of the VAT Act.&lt;/p&gt;",
    "FR": '&lt;p&gt;&lt;a href="http://bofip.impots.gouv.fr/bofip/1379-PGP" target="_blank"&gt;'
          "http://bofip.impots.gouv.fr/bofip/1379-PGP&lt;/a&gt;&lt;/p&gt;\n&lt;p&gt;Article 278 of the General Tax Code&lt;/p&gt;",
    "IE": "&lt;p&gt;The Standard Rate of VAT was temporarily reduced from 23% to 21% from 1 September 2020 to "
          "28 February 2021. It has been restored to 23% from 1 March 2021.&lt;/p&gt;",
    "LU": "&lt;p&gt;Art. 39(3) of VAT law&lt;/p&gt;",
}


def jsonstat(dims, cells, status=None, updated="2026-04-17T11:00:00+0200"):
    """A JSON-stat 2.0 dataset like Eurostat's: dims is [(name, [codes])], cells maps code tuples to values."""
    ids = [name for name, _ in dims]
    sizes = [len(codes) for _, codes in dims]
    positions = [{code: i for i, code in enumerate(codes)} for _, codes in dims]

    def flat(key):
        index = 0
        for pos, size, code in zip(positions, sizes, key):
            index = index * size + pos[code]
        return str(index)

    doc = {
        "version": "2.0", "class": "dataset", "label": "test", "source": "ESTAT", "updated": updated,
        "id": ids, "size": sizes,
        "dimension": {name: {"label": name, "category": {"index": pos, "label": {c: c for c in pos}}}
                      for (name, _), pos in zip(dims, positions)},
        "value": {flat(key): value for key, value in cells.items()},
    }
    if status:
        doc["status"] = {flat(key): flag for key, flag in status.items()}
    return doc


def standard_rate_on(code, on):
    rate = None
    for start, value in VAT_HISTORY[code]:
        if start <= on:
            rate = value
    return float(rate)


class World:
    """Answers the pipeline's requests the way the real sources do."""

    def __init__(self):
        self.fail = set()
        self.open_list_overrides = {}
        self.tedb_overrides = {}  # (code, iso date) -> rate
        self.drop_population_age = None
        self.ecb_jump = False
        self.ecb_drop = set()
        self.ecb_latest = date(2026, 11, 19)
        self.unit_mix_up = False
        self.calls = []

    # Eurostat ------------------------------------------------------------------------------------
    @staticmethod
    def share(indicator, code, year, unit="PC_IND"):
        i = CODES.index(code)
        if indicator in PHYSICAL and year >= 2025:
            return None  # physical goods were last asked in 2024, as in the real survey
        if indicator == "I_BAPP2" and year == 2024 and code == "CY":
            return None  # one country short in 2024, as in the real table
        base = {"I_BUY3": 60, "I_BPG_FOR": 30, "I_BPG_EU": 20, "I_BPG_WRLD": 12}.get(indicator, 15)
        value = base + (i * 7 % 23) * 0.5 + (year - 2020) * 0.3
        if indicator.startswith("I_BPG_") and unit == "PC_IND":
            value *= 0.7  # share of all people, smaller than the share of online buyers
        return round(value, 2)

    @staticmethod
    def years_for(indicator):
        if indicator.startswith("I_BPG_"):
            return [2021, 2022, 2023]
        return [2022, 2023, 2024, 2025]

    def population(self, code, age, year):
        return 10_000 + CODES.index(code) * 2_000 + int(age[1:]) * 10 + (year - 2024) * 50

    def eurostat(self, dataset, params):
        geos = params["geo"]
        if dataset == "demo_pjan":
            years = params["time"]
            ages = [a for a in params["age"] if a != self.drop_population_age]
            dims = [("freq", ["A"]), ("unit", ["NR"]), ("age", params["age"]), ("sex", ["T"]), ("geo", geos), ("time", years)]
            cells, status = {}, {}
            for age in ages:
                for geo in geos:
                    for year in years:
                        key = ("A", "NR", age, "T", geo, year)
                        cells[key] = self.population(geo, age, int(year))
                        if geo == "FR" and year == "2025":
                            status[key] = "p"
                        if geo == "RO" and year == "2025":
                            status[key] = "e"
            return jsonstat(dims, cells, status)
        indicator, unit = params["indic_is"][0], params["unit"][0]
        since = int(params.get("sinceTimePeriod", ["2020"])[0])
        years = [y for y in self.years_for(indicator) if y >= since]
        dims = [("freq", ["A"]), ("ind_type", ["IND_TOTAL"]), ("indic_is", [indicator]), ("unit", [unit]),
                ("geo", geos), ("time", [str(y) for y in years])]
        cells = {}
        for geo in geos:
            for year in years:
                value = self.share(indicator, geo, year, unit)
                if self.unit_mix_up and unit == "PC_IND" and indicator == "I_BPG_FOR":
                    value = 95.0
                if value is not None:
                    cells[("A", "IND_TOTAL", indicator, unit, geo, str(year))] = value
        return jsonstat(dims, cells)

    # EU tax database -----------------------------------------------------------------------------
    def tedb(self, body):
        text = body.decode()
        codes = [part.split("<")[0] for part in text.split("<t:isoCode>")[1:]]
        on = text.split("<t:situationOn>")[1].split("<")[0]
        ns = vat.NAMESPACE
        records = []
        for code in codes:
            rate = self.tedb_overrides.get((code, on), standard_rate_on(code, on))
            # Real quirks: legal references on the main rate, an "Import" entry for Germany at the same
            # rate, and a separate Canary Islands entry for Spain.
            records.append(self.record(code, "STANDARD", "DEFAULT", rate, LEGAL_NOTES.get(code, "")))
            if code == "ES":
                records.append(self.record(code, "STANDARD", "DEFAULT", 7.0, "VAT - Canary Islands - "))
            if code == "DE":
                records.append(self.record(code, "STANDARD", "DEFAULT", rate, "VAT - Import - "))
            records.append(self.record(code, "REDUCED", "REDUCED_RATE", 10.0))
        return (
            '<?xml version="1.0" encoding="UTF-8"?><soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
            f'<soap:Body><retrieveVatRatesRespMsg xmlns="{ns}"><additionalInformation xmlns="{ns}:types"/>'
            + "".join(records) + "</retrieveVatRatesRespMsg></soap:Body></soap:Envelope>"
        ).encode()

    @staticmethod
    def record(code, kind, rate_type, value, comment=""):
        note = f"<comment>{comment}</comment>" if comment else ""
        return (f'<vatRateResults xmlns="{vat.NAMESPACE}:types"><memberState>{code}</memberState><type>{kind}</type>'
                f"<rate><type>{rate_type}</type><value>{value}</value></rate>"
                f"<situationOn>2026-07-01+02:00</situationOn>{note}</vatRateResults>")

    def open_list(self):
        items = {}
        for code in CODES:
            periods = [{"effective_from": start, "rates": {"standard": rate, "reduced": 10}} for start, rate in VAT_HISTORY[code]]
            if code in REDUCED_ONLY_PERIODS:
                start = REDUCED_ONLY_PERIODS[code]
                periods.append({"effective_from": start, "rates": {"standard": standard_rate_on(code, start), "reduced": 9}})
            if code in self.open_list_overrides:
                periods.append({"effective_from": "2026-11-01", "rates": {"standard": self.open_list_overrides[code]}})
            items[OPEN_VAT_LIST_CODE.get(code, code)] = periods
        items["GB"] = [{"effective_from": "0000-01-01", "rates": {"standard": 20}}]
        return json.dumps({"details": "https://github.com/ibericode/vat-rates", "version": 4, "items": items}).encode()

    # ECB -----------------------------------------------------------------------------------------
    def ecb(self):
        base = {"USD": 1.16, "GBP": 0.87, "CZK": 24.3, "DKK": 7.46, "HUF": 390.0, "PLN": 4.25, "RON": 5.08, "SEK": 11.0, "JPY": 175.0}
        days, current = [], self.ecb_latest
        while len(days) < 64:
            if current.weekday() < 5:
                days.append(current)
            current -= timedelta(days=1)
        cubes = []
        for n, day in enumerate(days):  # newest first, like the real feed
            rates = []
            for currency, rate in base.items():
                if currency in self.ecb_drop and n == 0:
                    continue
                value = rate * (1 + 0.02 * math.sin(n / 9 + len(currency)))
                if self.ecb_jump and currency == "PLN" and n == 10:
                    value *= 1.5
                rates.append(f'<Cube currency="{currency}" rate="{value:.4f}"/>')
            cubes.append(f'<Cube time="{day.isoformat()}">{"".join(rates)}</Cube>')
        return (
            '<?xml version="1.0" encoding="UTF-8"?><gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01" '
            'xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref"><gesmes:subject>Reference rates</gesmes:subject>'
            "<gesmes:Sender><gesmes:name>European Central Bank</gesmes:name></gesmes:Sender>"
            f'<Cube>{"".join(cubes)}</Cube></gesmes:Envelope>'
        ).encode()

    # Router --------------------------------------------------------------------------------------
    def fetch(self, url, data=None, headers=None):
        self.calls.append(url)
        if url.startswith(eurostat.API):
            if "eurostat" in self.fail:
                raise RuntimeError("could not reach Eurostat (simulated)")
            parsed = urlparse(url)
            dataset = parsed.path.rsplit("/", 1)[-1]
            return json.dumps(self.eurostat(dataset, parse_qs(parsed.query))).encode()
        if url == vat.TEDB_URL:
            if "tedb" in self.fail:
                raise RuntimeError("could not reach the EU tax database (simulated)")
            assert headers and headers.get("SOAPAction") == vat.SOAP_ACTION
            return self.tedb(data)
        if url == vat.OPEN_VAT_LIST_URL:
            return self.open_list()
        if url == fx.ECB_URL:
            if "ecb" in self.fail:
                raise RuntimeError("could not reach the ECB (simulated)")
            return self.ecb()
        raise AssertionError(f"unexpected request: {url}")


@pytest.fixture
def world():
    return World()


@pytest.fixture
def today():
    return TODAY
