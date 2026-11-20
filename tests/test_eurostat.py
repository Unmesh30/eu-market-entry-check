import pytest

from pipeline import eurostat
from pipeline.errors import DataError

from conftest import jsonstat


def small_table(cells, status=None, geos=("DE", "FR"), years=("2024", "2025")):
    dims = [("freq", ["A"]), ("indic_is", ["I_BUY3"]), ("geo", list(geos)), ("time", list(years))]
    return jsonstat(dims, {("A", "I_BUY3", g, t): v for (g, t), v in cells.items()},
                    {("A", "I_BUY3", g, t): f for (g, t), f in (status or {}).items()})


def test_decode_reads_values_and_flags():
    doc = small_table({("DE", "2025"): 70.41, ("FR", "2025"): 75.2}, status={("FR", "2025"): "p"})
    table = eurostat.by_country_year(doc)
    assert table[("DE", 2025)] == (70.41, "")
    assert table[("FR", 2025)] == (75.2, "p")


def test_a_gap_is_never_read_as_zero():
    doc = small_table({("DE", "2025"): 70.0, ("FR", "2024"): 60.0, ("DE", "2024"): 66.0})
    table = eurostat.by_country_year(doc)
    assert ("FR", 2025) not in table
    # 2025 is missing France, so the latest year that covers both countries is 2024.
    assert eurostat.latest_full_year(table, ["DE", "FR"]) == 2024


def test_no_complete_year_gives_none():
    table = eurostat.by_country_year(small_table({("DE", "2025"): 70.0}))
    assert eurostat.latest_full_year(table, ["DE", "FR"]) is None


def test_unexpected_extra_codes_are_rejected():
    dims = [("indic_is", ["I_BUY3", "I_BLT12"]), ("geo", ["DE"]), ("time", ["2025"])]
    doc = jsonstat(dims, {("I_BUY3", "DE", "2025"): 1.0, ("I_BLT12", "DE", "2025"): 2.0})
    with pytest.raises(DataError):
        eurostat.by_country_year(doc)


def test_answer_without_a_dataset_is_rejected():
    with pytest.raises(DataError):
        eurostat.decode({"error": {"status": 413, "label": "too big"}})


def test_each_product_uses_its_latest_complete_year(world, today):
    result = eurostat.pull(world.fetch, today)
    years = {p["key"]: p["year"] for p in result["products"]}
    assert years["all"] == 2025
    assert years["software"] == 2025
    assert years["apps"] == 2025  # 2024 is one country short, 2025 is complete
    assert years["clothes"] == 2024  # physical goods were last asked in 2024
    assert result["abroad"]["year"] == 2023


def test_buyers_are_share_times_population_of_the_same_year(world, today):
    result = eurostat.pull(world.fetch, today)
    clothes = next(p for p in result["products"] if p["key"] == "clothes")
    population = sum(world.population("DE", f"Y{age}", 2024) for age in range(16, 75))
    assert result["population"]["2024"]["DE"]["value"] == population
    assert clothes["buyers"]["DE"] == round(clothes["share"]["DE"] / 100 * population)


def test_population_flags_travel_with_the_numbers(world, today):
    result = eurostat.pull(world.fetch, today)
    everything = next(p for p in result["products"] if p["key"] == "all")  # 2025: France p, Romania e
    clothes = next(p for p in result["products"] if p["key"] == "clothes")  # 2024: no flags
    assert everything["population_flags"] == {"FR": "p", "RO": "e"}
    assert clothes["population_flags"] == {}
    assert any("France provisional" in c["text"] and "Romania estimated" in c["text"] for c in result["checks"])


def test_incomplete_population_is_an_error(world, today):
    world.drop_population_age = "Y40"
    with pytest.raises(DataError, match="incomplete"):
        eurostat.pull(world.fetch, today)


def test_queries_ask_for_all_27_countries(world, today):
    eurostat.pull(world.fetch, today)
    assert all(call.count("geo=") == 27 for call in world.calls if "eurostat" in call)
