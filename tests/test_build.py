import json
import re
from datetime import datetime, timezone

import pytest

from pipeline import build

NOW = datetime(2026, 11, 20, 16, 40, tzinfo=timezone.utc)
LATER = datetime(2026, 11, 21, 16, 40, tzinfo=timezone.utc)


def embedded_data(page):
    match = re.search(r"const DATA = (\{.*?\});\n", page, re.S)
    assert match, "the page has no data"
    return json.loads(match.group(1))


def test_full_build(world):
    data = build.collect(world.fetch, NOW)
    assert data["warnings"] == []
    assert data["generated_at"] == "2026-11-20T16:40Z"
    assert set(data["sources"]) == {"eurostat", "vat", "fx"}
    assert all(block["fresh"] for block in data["sources"].values())
    page = build.render(data)
    assert "__DATA__" not in page and "/*CALC*/" not in page
    assert "function compareRoutes" in page
    assert embedded_data(page)["sources"]["vat"]["rates"]["ES"]["rate"] == 21.0


def test_a_failed_source_keeps_its_last_good_data(world):
    first = build.collect(world.fetch, NOW)
    world.fail.add("ecb")
    second = build.collect(world.fetch, LATER, previous=first)
    assert second["sources"]["fx"]["fresh"] is False
    assert second["sources"]["fx"]["pulled_at"] == "2026-11-20T16:40Z"
    assert second["sources"]["fx"]["per_amount"] == first["sources"]["fx"]["per_amount"]
    assert second["sources"]["vat"]["fresh"] is True
    assert len(second["warnings"]) == 1
    assert "exchange-rate update failed" in second["warnings"][0]


def test_first_run_without_data_cannot_fall_back(world):
    world.fail.add("tedb")
    with pytest.raises(RuntimeError):
        build.collect(world.fetch, NOW)


def test_data_cannot_break_out_of_the_script_tag(world):
    data = build.collect(world.fetch, NOW)
    data["warnings"].append("</script><script>alert(1)</script>")
    page = build.render(data)
    assert "</script><script>alert(1)" not in page
    assert embedded_data(page)["warnings"][-1] == "</script><script>alert(1)</script>"


def test_main_writes_the_page_and_the_data(world, tmp_path, monkeypatch):
    output = tmp_path / "github_output"
    world.ecb_latest = datetime.now(timezone.utc).date()  # main() runs on today's date
    monkeypatch.setattr(build, "http_fetch", world.fetch)
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    build.main(["--data", str(tmp_path / "data" / "latest.json"), "--out", str(tmp_path / "site")])
    assert (tmp_path / "site" / "index.html").exists()
    assert (tmp_path / "site" / ".nojekyll").exists()
    assert (tmp_path / "site" / "preview.png").exists() == (build.ROOT / "docs" / "preview.png").exists()
    saved = json.loads((tmp_path / "data" / "latest.json").read_text())
    assert saved["sources"]["fx"]["latest"] <= datetime.now(timezone.utc).date().isoformat()
    assert output.read_text() == "warnings=0\n"
