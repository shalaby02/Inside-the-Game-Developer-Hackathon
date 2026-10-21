"""Checks src/build_site.py and the saved web/data/ files. No model calls."""

import hashlib
import json
import subprocess
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


# ------------------------------------------------------------ pass map

def event_rows():
    cols = BUILT["events.json"]["columns"]
    return [dict(zip(cols, r)) for r in BUILT["events.json"]["rows"]]


def test_events_carry_what_the_pass_map_needs():
    assert {"event_id", "possession_id", "x", "y", "end_x", "end_y", "xt_added"} <= set(BUILT["events.json"]["columns"])


def test_every_moment_has_a_map_or_a_stated_reason():
    events = event_rows()
    for m in BUILT["key_moments.json"]["moments"]:
        mp = m["map"]
        if m["category"] == "momentum_shift":
            assert mp == {"reason": bs.SPELL_MAP_REASON}, m["id"]
            continue
        assert "reason" not in mp, m["id"]
        move = [e for e in events if e["possession_id"] == mp["possession_id"]]
        key = [e for e in move if e["event_id"] == mp["key_event_id"]]
        assert len(key) == 1, m["id"]
        assert key[0]["team"] == mp["team"]
        assert (key[0]["period"], key[0]["minute"], key[0]["second"]) == (m["period"], m["minute"], m["second"])
        drawn = [e for e in move if e["team"] == mp["team"] and e["type"] in ("pass", "carry", "shot")]
        assert drawn, m["id"]
        if m["category"] in bs.SHOT_CATEGORIES:
            assert key[0]["type"] == "shot"
        else:
            assert key[0]["type"] in ("pass", "carry") and key[0]["team"] == m["team"]


def test_spells_are_the_only_moments_without_a_map():
    no_map = sorted(m["id"] for m in BUILT["key_moments.json"]["moments"] if "reason" in m["map"])
    assert no_map == sorted(m["id"] for m in BUILT["key_moments.json"]["moments"]
                            if m["category"] == "momentum_shift")


def test_map_events_are_in_time_order():
    events = event_rows()
    for m in BUILT["key_moments.json"]["moments"]:
        if "reason" in m["map"]:
            continue
        move = [e for e in events if e["possession_id"] == m["map"]["possession_id"]]
        assert [e["t"] for e in move] == sorted(e["t"] for e in move), m["id"]
        assert [e["event_id"] for e in move] == sorted(e["event_id"] for e in move), m["id"]


def test_every_profile_names_its_voice():
    for p in BUILT["profiles.json"]["profiles"]:
        assert p["voice_label"] == bs.VOICE_LABELS[p["profile"]["voice"]]


FROZEN = [ROOT / "data", ROOT / "src" / "generate_match.py"]


def frozen_hashes():
    files = [f for path in FROZEN for f in ([path] if path.is_file() else sorted(path.rglob("*"))) if f.is_file()]
    return {str(f.relative_to(ROOT)): hashlib.sha256(f.read_bytes()).hexdigest() for f in files}


def test_building_the_site_changes_no_frozen_file(tmp_path, monkeypatch):
    before = frozen_hashes()
    monkeypatch.setattr(bs, "OUT_DIR", tmp_path)
    assert bs.main() == 0
    assert frozen_hashes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(BUILT)


def test_frozen_files_match_the_last_commit():
    """data/ and the generator are frozen: no uncommitted change to them."""
    try:
        out = subprocess.run(["git", "status", "--porcelain", "--", "data", "src/generate_match.py"],
                             cwd=ROOT, capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("git is not available")
    assert out == ""
