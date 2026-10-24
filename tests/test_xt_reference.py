"""Checks src/xt_reference.py, docs/xt-grid.svg and the README xT block. No model calls."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import xt_model  # noqa: E402
import xt_reference as xr  # noqa: E402

REF = xr.reference()


def test_values_are_the_model_grid():
    assert REF["values"] == xt_model.GRID
    assert (len(REF["values"]), len(REF["values"][0])) == (xt_model.COLS, xt_model.ROWS)


def test_best_zones_are_about_030():
    for c, r in REF["best_zones"]:
        assert xt_model.GRID[c][r] == xt_model.TOP_VALUE == 0.30


def test_example_is_the_26th_minute_pass_from_the_data():
    ex = REF["example"]
    assert (ex["minute"], ex["type"]) == (26, "pass")
    assert ex["from_value"] == xt_model.value(*ex["start"])
    assert ex["to_value"] == xt_model.value(*ex["end"])
    assert round(ex["to_value"] - ex["from_value"], 4) == ex["xt_added"]
    moments = json.loads((ROOT / "data" / "key_moments.json").read_text(encoding="utf-8"))["moments"]
    assert next(m for m in moments if m["id"] == ex["moment_id"])["facts"]["xt_added"] == ex["xt_added"]


def test_scale_covers_every_value_in_order():
    mins = [s["min"] for s in REF["scale"]]
    assert mins == sorted(mins) and mins[0] == 0
    assert {xr.step(v) for col in xt_model.GRID for v in col} == set(range(len(xr.SCALE)))


def test_svg_is_up_to_date():
    assert (ROOT / "docs" / "xt-grid.svg").read_text(encoding="utf-8") == xr.svg(REF), \
        "run python src/xt_reference.py"


def test_readme_block_is_up_to_date():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert xr.readme_block(REF) in text, "run python src/xt_reference.py"
    assert xr.CAPTION in text


def test_svg_has_a_text_alternative():
    s = xr.svg(REF)
    assert "<title" in s and "<desc" in s and xr.alt_text(REF) in s
