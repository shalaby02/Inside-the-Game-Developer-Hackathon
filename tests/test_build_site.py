"""Checks src/build_site.py and the saved web/data/ files. No model calls."""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import build_site as bs  # noqa: E402
from match_summary import build as build_summary  # noqa: E402

WEB_DATA = ROOT / "web" / "data"
CHECKS = bs.run_checks()
BUILT = bs.build(CHECKS)
SAVED = {p.name: p for p in sorted(WEB_DATA.glob("*.json"))}
MOMENT_IDS = {m["id"] for m in BUILT["key_moments.json"]["moments"]}


def test_saved_text_passes_every_check():
    assert CHECKS["passed"], CHECKS["failures"]


def test_saved_files_are_the_built_files():
    assert sorted(SAVED) == sorted(BUILT)
    for name, content in BUILT.items():
        assert SAVED[name].read_text(encoding="utf-8") == bs.dumps(content), f"{name} is out of date"


@pytest.mark.parametrize("name", sorted(BUILT))
def test_every_file_is_valid_json(name):
    json.loads(SAVED[name].read_text(encoding="utf-8"))


def referenced_ids(files):
    """(where, id) for every moment id the page's files refer to."""
    out = [("narrations", i) for i in files["narrations.json"]]
    a = files["analysis.json"]
    out += [("analysis.story_arc", s["moment_id"]) for s in a["story_arc"]]
    out += [("analysis.turning_point", a["turning_point"]["moment_id"])]
    out += [("analysis.moment_priority", i) for ids in a["moment_priority"].values() for i in ids]
    out += [("match.goals", g["moment_id"]) for g in files["match.json"]["goals"]]
    out += [(f"player {n}", i) for n, p in files["player_summaries.json"]["players"].items() for i in p["moment_ids"]]
    for p in files["profiles.json"]["profiles"]:
        out += [(f"{p['key']}.selection", i) for i in p["selection"]]
        out += [(f"{p['key']}.moments", m["id"]) for m in p["moments"]]
    out += [(f"overlay {o['profile_key']}", o["moment_id"]) for o in files["overlays.json"]["overlays"]]
    return out


def test_every_referenced_moment_exists():
    files = {name: json.loads(path.read_text(encoding="utf-8")) for name, path in SAVED.items()}
    ids = {m["id"] for m in files["key_moments.json"]["moments"]}
    missing = [(where, i) for where, i in referenced_ids(files) if i not in ids]
    assert not missing


def test_every_moment_has_a_narration():
    assert set(BUILT["narrations.json"]) == MOMENT_IDS


def test_four_profiles_with_plain_names():
    labels = [p["label"] for p in BUILT["profiles.json"]["profiles"]]
    assert labels == ["Analyst", "Red fan", "Blue fan", "Follow Cass Dunmore"]


def test_overlays_cover_every_profile_moment_with_the_required_fields():
    overlays = BUILT["overlays.json"]["overlays"]
    expected = {(p["key"], m["id"]) for p in BUILT["profiles.json"]["profiles"] for m in p["moments"]}
    assert {(o["profile_key"], o["moment_id"]) for o in overlays} == expected
    length = BUILT["match.json"]["timeline"]["length_seconds"]
    for o in overlays:
        assert {"start_seconds", "duration_seconds", "type", "headline", "lines", "profile_key"} <= set(o)
        assert 0 <= o["start_seconds"] <= length
        assert bs.OVERLAY_MIN_SECONDS <= o["duration_seconds"] <= bs.OVERLAY_MAX_SECONDS
        assert not o["headline"].endswith(".")
        assert o["lines"] and all(isinstance(line, str) and line for line in o["lines"])


def test_overlay_text_is_the_saved_profile_text():
    profiles = {p["key"]: {m["id"]: m for m in p["moments"]} for p in BUILT["profiles.json"]["profiles"]}
    for o in BUILT["overlays.json"]["overlays"]:
        saved = profiles[o["profile_key"]][o["moment_id"]]
        assert o["headline"] == bs.display_headline(saved["headline"])
        assert o["lines"] == saved["lines"]


def test_display_headline_strips_one_trailing_full_stop():
    assert bs.display_headline("Niko Vane scores.") == "Niko Vane scores"
    assert bs.display_headline("Niko Vane scores") == "Niko Vane scores"
    assert bs.display_headline("Wait...") == "Wait..."


def test_threat_blocks_add_up_to_the_match_summary():
    summary = build_summary()["by_half"]
    blocks = BUILT["threat.json"]["blocks"]
    for half, period in (("first_half", 1), ("second_half", 2)):
        for team in ("london_red", "london_blue"):
            total = sum(b[team] for b in blocks if b["period"] == period)
            assert total == pytest.approx(summary[half][team]["threat_created"], abs=1e-3)


def test_threat_blocks_tile_the_timeline():
    blocks = BUILT["threat.json"]["blocks"]
    assert blocks[0]["t_start"] == 0
    assert blocks[-1]["t_end"] == BUILT["match.json"]["timeline"]["length_seconds"]
    assert all(a["t_end"] == b["t_start"] for a, b in zip(blocks, blocks[1:]))


def test_events_are_in_timeline_order_and_moments_match_their_time():
    rows = BUILT["events.json"]["rows"]
    t = [r[0] for r in rows]
    assert t == sorted(t)
    timeline = BUILT["match.json"]["timeline"]["periods"]
    for m in BUILT["key_moments.json"]["moments"]:
        assert m["t"] == bs.timeline_seconds(timeline, m["period"], m["minute"], m["second"])
        assert m["reveal_t"] >= m["t"]


def test_momentum_shifts_are_revealed_when_their_spell_ends():
    for m in BUILT["key_moments.json"]["moments"]:
        if m["category"] == "momentum_shift":
            assert m["reveal_t"] > m["t"]
        else:
            assert m["reveal_t"] == m["t"]


def test_arabic_is_offered_only_when_a_profile_has_it():
    langs = {x["code"]: x["available"] for x in BUILT["meta.json"]["languages"]}
    has_ar = any(p["profile"]["language"] == "ar" for p in BUILT["profiles.json"]["profiles"])
    assert langs["ar"] is has_ar and langs["en"] is True
