"""Runs the calculator code that ships in the page (site_src/calc.js) with Node."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

CALC = Path(__file__).resolve().parent.parent / "site_src" / "calc.js"
pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed")


def compare(**values):
    script = f"const {{ compareRoutes }} = require({json.dumps(str(CALC))}); console.log(JSON.stringify(compareRoutes({json.dumps(values)})));"
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout
    return json.loads(out)


EXAMPLE = {"sales": 2_000_000, "feePct": 5, "cardPct": 2, "setup": 15_000, "running": 30_000}


def test_example_values():
    result = compare(**EXAMPLE)
    # The fee costs 3% more than card fees alone: 30,000 / 3% = 1,000,000.
    assert result["mode"] == "compare"
    assert result["breakEven"] == pytest.approx(1_000_000)
    assert result["yearlySaving"] == pytest.approx(30_000)  # 2,000,000 x 3% - 30,000
    assert result["paybackMonths"] == pytest.approx(6)  # 15,000 / (30,000 / 12)


def test_ignoring_card_fees_would_understate_break_even():
    with_card_fees = compare(**EXAMPLE)["breakEven"]
    without = compare(**{**EXAMPLE, "cardPct": 0})["breakEven"]
    assert without == pytest.approx(600_000)
    assert with_card_fees > without


def test_below_break_even_never_pays_back():
    result = compare(**{**EXAMPLE, "sales": 500_000})
    assert result["yearlySaving"] == pytest.approx(-15_000)
    assert result["paybackMonths"] is None


def test_fee_no_higher_than_card_fees():
    assert compare(**{**EXAMPLE, "feePct": 2, "cardPct": 2})["mode"] == "own-never-cheaper"
    assert compare(**{**EXAMPLE, "feePct": 1.5, "cardPct": 2})["mode"] == "own-never-cheaper"


def test_no_setup_cost_pays_back_at_once():
    assert compare(**{**EXAMPLE, "setup": 0})["paybackMonths"] == 0


@pytest.mark.parametrize("field,value", [("sales", -1), ("feePct", 101), ("cardPct", -0.5), ("running", None)])
def test_bad_inputs_are_refused(field, value):
    result = compare(**{**EXAMPLE, field: value})
    assert result["ok"] is False
    assert field in result["invalid"]
