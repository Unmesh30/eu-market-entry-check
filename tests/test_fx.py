from datetime import date

import pytest

from pipeline import fx
from pipeline.countries import currencies
from pipeline.errors import DataError


def latest_rates(world):
    days = fx.parse_ecb(world.ecb())
    return days[max(days)]


def test_values_use_euro_cross_rates(world, today):
    result = fx.pull(world.fetch, today, currencies())
    rates = latest_rates(world)
    assert result["per_amount"]["EUR"]["USD"]["now"] == pytest.approx(100_000 * rates["USD"])
    assert result["per_amount"]["PLN"]["USD"]["now"] == pytest.approx(100_000 * rates["USD"] / rates["PLN"])
    assert result["per_amount"]["SEK"]["GBP"]["now"] == pytest.approx(100_000 * rates["GBP"] / rates["SEK"])


def test_range_is_high_minus_low_over_low(world, today):
    result = fx.pull(world.fetch, today, currencies())
    usd = result["per_amount"]["EUR"]["USD"]
    assert usd["range_pct"] == pytest.approx((usd["high"] - usd["low"]) / usd["low"] * 100)
    assert usd["low"] <= usd["now"] <= usd["high"]


def test_every_non_euro_currency_is_covered(world, today):
    result = fx.pull(world.fetch, today, currencies())
    assert sorted(result["per_amount"]) == ["CZK", "DKK", "EUR", "HUF", "PLN", "RON", "SEK"]
    assert "all 6 non-euro currencies" in result["checks"][0]["text"]


def test_a_stale_feed_is_an_error(world):
    with pytest.raises(DataError, match="days old"):
        fx.pull(world.fetch, date(2026, 12, 15), currencies())


def test_a_missing_currency_is_an_error(world, today):
    world.ecb_drop.add("HUF")
    with pytest.raises(DataError, match="HUF"):
        fx.pull(world.fetch, today, currencies())


def test_an_impossible_daily_move_is_an_error(world, today):
    world.ecb_jump = True
    with pytest.raises(DataError, match="PLN moved more than 10%"):
        fx.pull(world.fetch, today, currencies())
