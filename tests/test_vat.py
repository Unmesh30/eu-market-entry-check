import json
from datetime import date

import pytest

from pipeline import vat
from pipeline.errors import DataError

from conftest import World


def rates_for(world, codes):
    return vat.standard_rates(vat.parse_tedb(world.tedb(vat.soap_request(codes, date(2026, 11, 20)))), codes)


def test_spain_main_rate_is_kept_apart_from_the_canary_islands(world):
    spain = rates_for(world, ["ES"])["ES"]
    assert spain["rate"] == 21.0
    assert spain["regional"] == [{
        "region": "Canary Islands", "rate": 7.0,
        "phrase": "for the Canary Islands", "note": "which are outside the EU VAT area",
    }]


def test_legal_references_do_not_hide_the_main_rate(world):
    rates = rates_for(world, ["BE", "CZ", "FR", "IE", "LU"])
    assert {code: entry["rate"] for code, entry in rates.items()} == {"BE": 21.0, "CZ": 21.0, "FR": 20.0, "IE": 23.0, "LU": 17.0}
    assert all(entry["regional"] == [] for entry in rates.values())


def test_a_labelled_entry_at_the_same_rate_is_not_shown(world):
    germany = rates_for(world, ["DE"])["DE"]  # "VAT - Import" at 19%, like the main rate
    assert germany["rate"] == 19.0
    assert germany["regional"] == []


def test_two_unlabelled_standard_rates_is_an_error():
    records = [
        {"country": "ES", "type": "STANDARD", "rate_type": "DEFAULT", "value": 21.0, "comment": ""},
        {"country": "ES", "type": "STANDARD", "rate_type": "DEFAULT", "value": 7.0, "comment": "<p>Art. 90</p>"},
    ]
    with pytest.raises(DataError, match="expected one main standard VAT rate"):
        vat.standard_rates(records, ["ES"])


def test_labels_are_read_from_the_database_comments():
    assert vat.label_of("VAT - Canary Islands - ") == "Canary Islands"
    assert vat.label_of("VAT - Import -") == "Import"
    assert vat.label_of("<p>Art. 47 of the VAT Act.</p>") == ""
    assert vat.label_of("") == ""


def test_soap_fault_is_an_error():
    fault = (b'<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"><soap:Body><soap:Fault>'
             b"<faultcode>soap:Server</faultcode><faultstring>TEDB-ERR-1</faultstring></soap:Fault></soap:Body></soap:Envelope>")
    with pytest.raises(DataError, match="TEDB-ERR-1"):
        vat.parse_tedb(fault)


def test_greece_is_found_under_gr_in_the_open_list(world):
    doc = json.loads(world.open_list())
    assert vat.open_list_rate(doc, "EL", date(2026, 11, 20)) == 24.0


def test_change_dates_ignore_periods_where_only_a_reduced_rate_changed(world):
    doc = json.loads(world.open_list())
    # Finland's latest period in the open list starts on 1 January 2026, but only a reduced rate changed then.
    assert vat.last_standard_change(doc, "FI", date(2026, 11, 20)) == {"date": "2024-09-01", "from": 24.0, "to": 25.5}
    assert vat.last_standard_change(doc, "CZ", date(2026, 11, 20)) is None


def test_pull_confirms_recent_changes_in_the_eu_database(world, today):
    result = vat.pull(world.fetch, today)
    rates = result["rates"]
    assert rates["RO"]["rate"] == 21.0
    assert rates["RO"]["change"] == {"date": "2025-08-01", "from": 19.0, "to": 21.0}
    assert rates["FI"]["change"] == {"date": "2024-09-01", "from": 24.0, "to": 25.5}
    assert rates["LU"]["change"] == {"date": "2024-01-01", "from": 16.0, "to": 17.0}
    assert rates["EL"]["change"] is None  # 2016 is outside the three-year window
    assert all(check["ok"] for check in result["checks"])


def test_disagreeing_sources_stop_the_update(world, today):
    world.open_list_overrides["DE"] = 20
    with pytest.raises(DataError, match="Germany 19% vs 20%"):
        vat.pull(world.fetch, today)


def test_an_unconfirmed_change_is_not_shown(world, today):
    world.tedb_overrides[("RO", "2025-07-31")] = 21.0  # the EU database disagrees about the old rate
    result = vat.pull(world.fetch, today)
    assert result["rates"]["RO"]["change"] is None
    assert any(not c["ok"] and "Romania" in c["text"] for c in result["checks"])


def test_rate_outside_the_legal_range_is_an_error(today):
    world = World()
    world.tedb_overrides[("DE", today.isoformat())] = 1.9  # a slipped decimal point
    with pytest.raises(DataError, match="outside"):
        vat.pull(world.fetch, today)
