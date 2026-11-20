"""The 27 EU member states, with the codes and currencies the sources use."""

# Eurostat and the EU tax database both use "EL" for Greece.
EU27 = {
    "AT": ("Austria", "EUR"),
    "BE": ("Belgium", "EUR"),
    "BG": ("Bulgaria", "EUR"),  # euro since 1 January 2026
    "CY": ("Cyprus", "EUR"),
    "CZ": ("Czechia", "CZK"),
    "DE": ("Germany", "EUR"),
    "DK": ("Denmark", "DKK"),
    "EE": ("Estonia", "EUR"),
    "EL": ("Greece", "EUR"),
    "ES": ("Spain", "EUR"),
    "FI": ("Finland", "EUR"),
    "FR": ("France", "EUR"),
    "HR": ("Croatia", "EUR"),
    "HU": ("Hungary", "HUF"),
    "IE": ("Ireland", "EUR"),
    "IT": ("Italy", "EUR"),
    "LT": ("Lithuania", "EUR"),
    "LU": ("Luxembourg", "EUR"),
    "LV": ("Latvia", "EUR"),
    "MT": ("Malta", "EUR"),
    "NL": ("Netherlands", "EUR"),
    "PL": ("Poland", "PLN"),
    "PT": ("Portugal", "EUR"),
    "RO": ("Romania", "RON"),
    "SE": ("Sweden", "SEK"),
    "SI": ("Slovenia", "EUR"),
    "SK": ("Slovakia", "EUR"),
}

CODES = sorted(EU27)

# The open VAT list (ibericode/vat-rates) uses the ISO code "GR" for Greece.
OPEN_VAT_LIST_CODE = {"EL": "GR"}

CURRENCY_NAMES = {
    "EUR": "euro",
    "CZK": "Czech koruna",
    "DKK": "Danish krone",
    "HUF": "Hungarian forint",
    "PLN": "Polish złoty",
    "RON": "Romanian leu",
    "SEK": "Swedish krona",
}


def currencies():
    """Every local currency used by an EU country, euro included."""
    return sorted({currency for _, currency in EU27.values()})
