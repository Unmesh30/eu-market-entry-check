"""Eurostat: who buys online in each EU country, what they buy, and how many people live there.

Everything comes from Eurostat's public dissemination API, which answers in JSON-stat 2.0.
"""
import json
from urllib.parse import urlencode

from .countries import CODES, EU27
from .errors import DataError

API = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/"
TABLE_PAGE = "https://ec.europa.eu/eurostat/databrowser/view/{dataset}/default/table?lang=en"

# Eurostat's observation flags. A number that carries one is shown with it, never without.
FLAG_MEANINGS = {
    "b": "break in series",
    "c": "confidential",
    "d": "definition differs",
    "e": "estimated",
    "f": "forecast",
    "n": "not significant",
    "p": "provisional",
    "r": "revised",
    "s": "Eurostat estimate",
    "u": "low reliability",
    "z": "not applicable",
}

# What a merchant might sell. Every share means "people aged 16-74 who bought this online in the
# last 3 months" (Eurostat's definition), so the products compare like for like.
def _product(key, label, phrase, dataset, indicator, kind):
    """`label` is the menu name; `phrase` follows "people who" and matches Eurostat's wording."""
    return {"key": key, "label": label, "phrase": phrase, "dataset": dataset, "indicator": indicator, "kind": kind}


PRODUCTS = [
    _product("all", "Anything", "bought something online", "isoc_ec_ib20", "I_BUY3", "any"),
    _product("clothes", "Clothes and shoes", "bought clothes, shoes or accessories online", "isoc_ec_ibgs", "I_BCLOT1", "physical"),
    _product("beauty", "Beauty and wellness", "bought cosmetics, beauty or wellness products online", "isoc_ec_ibgs", "I_BCBW", "physical"),
    _product("electronics", "Electronics and appliances", "bought consumer electronics or household appliances online", "isoc_ec_ibgs", "I_BEEQU1", "physical"),
    _product("computers", "Computers and phones", "bought computers, tablets, phones or accessories online", "isoc_ec_ibgs", "I_BHARD1", "physical"),
    _product("home", "Furniture and home", "bought furniture, home accessories or garden products online", "isoc_ec_ibgs", "I_BFURN1", "physical"),
    _product("sports", "Sports goods", "bought sports goods online", "isoc_ec_ibgs", "I_BSPG", "physical"),
    _product("software", "Software downloads", "bought software as a download", "isoc_ec_ibgs", "I_BSOFT2", "digital"),
    _product("games", "Game downloads", "bought games as a download", "isoc_ec_ibgs", "I_BGAMES2", "digital"),
    _product("apps", "App subscriptions", "had a paid app subscription (e.g. language, travel, weather)", "isoc_ec_ibgs", "I_BAPP2", "digital"),
]

# Share of online buyers who bought from sellers in other countries.
ABROAD = {
    "dataset": "isoc_ec_ibos",
    "unit": "PC_IND_BUY3",
    "indicators": {"any": "I_BPG_FOR", "eu": "I_BPG_EU", "non_eu": "I_BPG_WRLD"},
}

POPULATION_DATASET = "demo_pjan"
SURVEY_AGES = [f"Y{age}" for age in range(16, 75)]  # the survey covers people aged 16 to 74


def table_url(dataset, **dimensions):
    """Build an API query. A list value asks for several codes of one dimension."""
    params = [("format", "JSON"), ("lang", "EN")]
    for name, value in dimensions.items():
        for item in value if isinstance(value, (list, tuple)) else [value]:
            params.append((name, str(item)))
    return API + dataset + "?" + urlencode(params)


def load(fetch, url):
    try:
        return json.loads(fetch(url))
    except json.JSONDecodeError as error:
        raise DataError(f"Eurostat sent something that is not JSON ({error})") from None


def decode(doc):
    """Return (dimension ids, {tuple of codes: (value, flag)}) for a JSON-stat 2.0 dataset."""
    if not isinstance(doc, dict) or "id" not in doc or "size" not in doc:
        raise DataError(f"Eurostat answered without a dataset: {str(doc)[:200]}")
    ids, sizes = doc["id"], doc["size"]
    codes_by_dimension = []
    for dimension in ids:
        index = doc["dimension"][dimension]["category"]["index"]
        if isinstance(index, list):
            codes = list(index)
        else:
            codes = [None] * len(index)
            for code, position in index.items():
                codes[position] = code
        codes_by_dimension.append(codes)
    values = doc.get("value") or {}
    if isinstance(values, list):
        values = {str(i): v for i, v in enumerate(values)}
    flags = doc.get("status") or {}
    if isinstance(flags, list):
        flags = {str(i): f for i, f in enumerate(flags) if f}
    cells = {}
    for flat, value in values.items():
        if value is None:
            continue  # a gap stays a gap; it is never read as zero
        rest, coords = int(flat), []
        for size in reversed(sizes):
            coords.append(rest % size)
            rest //= size
        coords.reverse()
        key = tuple(codes_by_dimension[i][c] for i, c in enumerate(coords))
        cells[key] = (float(value), flags.get(flat, ""))
    return ids, cells


def by_country_year(doc):
    """{(country, year): (value, flag)} for a query that fixes every other dimension to one code."""
    ids, cells = decode(doc)
    for dimension, size in zip(ids, doc["size"]):
        if dimension not in ("geo", "time") and size != 1:
            raise DataError(f"Eurostat returned {size} codes for '{dimension}' where one was asked for")
    g, t = ids.index("geo"), ids.index("time")
    return {(key[g], int(key[t])): cell for key, cell in cells.items()}


def full_years(table, countries=CODES):
    """Years in which every country has a number."""
    return {year for (_, year) in table if all((country, year) in table for country in countries)}


def latest_full_year(table, countries=CODES):
    """The most recent year in which every country has a number, or None."""
    years = full_years(table, countries)
    return max(years) if years else None


def population_16_74(fetch, years):
    """People aged 16-74 on 1 January of each year, per country, with Eurostat's flags."""
    doc = load(fetch, table_url(POPULATION_DATASET, sex="T", unit="NR", age=SURVEY_AGES, geo=CODES, time=years))
    ids, cells = decode(doc)
    for dimension, size in zip(ids, doc["size"]):
        if dimension not in ("geo", "time", "age") and size != 1:
            raise DataError(f"Eurostat returned {size} codes for '{dimension}' where one was asked for")
    g, t = ids.index("geo"), ids.index("time")
    totals, counts, flags = {}, {}, {}
    for key, (value, flag) in cells.items():
        slot = (key[g], int(key[t]))
        totals[slot] = totals.get(slot, 0.0) + value
        counts[slot] = counts.get(slot, 0) + 1
        if flag:
            flags.setdefault(slot, set()).update(flag)
    result = {}
    for year in years:
        for country in CODES:
            found = counts.get((country, year), 0)
            if found != len(SURVEY_AGES):
                raise DataError(
                    f"Population aged 16-74 for {EU27[country][0]} in {year} is incomplete "
                    f"({found} of {len(SURVEY_AGES)} ages)"
                )
        result[str(year)] = {
            country: {
                "value": round(totals[(country, year)]),
                "flags": "".join(sorted(flags.get((country, year), set()))),
            }
            for country in CODES
        }
    return result, doc.get("updated")


def flag_summary(flagged):
    """'France provisional, Romania estimated' from {'FR': 'p', 'RO': 'e'}."""
    parts = []
    for country in sorted(flagged, key=lambda c: EU27[c][0]):
        words = [FLAG_MEANINGS.get(flag, flag) for flag in flagged[country]]
        parts.append(f"{EU27[country][0]} {' and '.join(words)}")
    return ", ".join(parts)


def pull(fetch, today):
    """Pull every Eurostat table the page uses and check it. Raises DataError on any gap."""
    since = today.year - 4
    updated = {}

    products = []
    for product in PRODUCTS:
        doc = load(fetch, table_url(
            product["dataset"], indic_is=product["indicator"], ind_type="IND_TOTAL",
            unit="PC_IND", geo=CODES, sinceTimePeriod=since,
        ))
        table = by_country_year(doc)
        year = latest_full_year(table)
        if year is None:
            raise DataError(f"'{product['label']}': no survey year since {since} covers all 27 countries")
        share = {country: table[(country, year)][0] for country in CODES}
        outside = [EU27[c][0] for c, v in share.items() if not 0 <= v <= 100]
        if outside:
            raise DataError(f"'{product['label']}': shares outside 0-100% for {', '.join(outside)}")
        products.append({
            **product,
            "year": year,
            "updated": doc.get("updated"),
            "share": share,
            "flags": {c: table[(c, year)][1] for c in CODES if table[(c, year)][1]},
        })
        updated[product["dataset"]] = doc.get("updated")

    abroad_tables = {}
    for key, indicator in ABROAD["indicators"].items():
        doc = load(fetch, table_url(
            ABROAD["dataset"], indic_is=indicator, ind_type="IND_TOTAL",
            unit=ABROAD["unit"], geo=CODES, sinceTimePeriod=since,
        ))
        abroad_tables[key] = by_country_year(doc)
        updated[ABROAD["dataset"]] = doc.get("updated")
    shared = set.intersection(*(full_years(table) for table in abroad_tables.values()))
    if not shared:
        raise DataError(f"Buying from sellers abroad: no survey year since {since} covers all 27 countries")
    abroad_year = max(shared)  # the latest year in which all three measures cover every country
    abroad ={"year": abroad_year, "dataset": ABROAD["dataset"], "updated": updated[ABROAD["dataset"]]}
    abroad_flags = {}
    for key, table in abroad_tables.items():
        abroad[key] = {c: table[(c, abroad_year)][0] for c in CODES}
        for c in CODES:
            if table[(c, abroad_year)][1]:
                abroad_flags.setdefault(c, set()).update(table[(c, abroad_year)][1])
    abroad["flags"] = {c: "".join(sorted(f)) for c, f in abroad_flags.items()}

    survey_years = sorted({p["year"] for p in products})
    population, updated[POPULATION_DATASET] = population_16_74(fetch, survey_years)
    for product in products:
        people = population[str(product["year"])]
        product["buyers"] = {c: round(product["share"][c] / 100 * people[c]["value"]) for c in CODES}
        product["population_flags"] = {c: people[c]["flags"] for c in CODES if people[c]["flags"]}

    by_year = {}
    for product in products:
        by_year.setdefault(product["year"], []).append(product["key"])
    years_text = ", ".join(f"{year} for {len(keys)}" for year, keys in sorted(by_year.items(), reverse=True))
    flagged = {}
    for year in survey_years:
        for country, cell in population[str(year)].items():
            if cell["flags"]:
                flagged.setdefault(country, set()).update(cell["flags"])
    for product in products:
        for country, flag in product["flags"].items():
            flagged.setdefault(country, set()).update(flag)
    for country, flag in abroad["flags"].items():
        flagged.setdefault(country, set()).update(flag)
    flagged = {c: "".join(sorted(f)) for c, f in flagged.items()}

    names = ", ".join(EU27[c][0] for c in sorted(flagged, key=lambda c: EU27[c][0]))
    checks = [
        {"ok": True, "text": "Each product: latest survey year with all 27 countries", "detail": f"Survey years: {years_text}. A gap is never read as zero."},
        {"ok": True, "text": f"Buying abroad: {abroad_year}, the latest year for all 27"},
        {"ok": True, "text": f"Population 16–74 matched to each survey year ({', '.join(map(str, survey_years))})"},
        {"ok": True, "text": f"Eurostat flags shown ({names})" if flagged else "No Eurostat flags on the numbers shown",
         "detail": flag_summary(flagged)},
    ]
    return {
        "products": products,
        "abroad": abroad,
        "population": population,
        "updated": updated,
        "table_page": TABLE_PAGE,
        "checks": checks,
    }
