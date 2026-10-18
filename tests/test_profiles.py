"""Checks profile validation and moment selection (src/profiles.py). No model calls."""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from profiles import Profile, ProfileError, select, selection_problems  # noqa: E402

MOMENTS = json.loads((ROOT / "data" / "key_moments.json").read_text())["moments"]
PRIORITY = json.loads((ROOT / "data" / "analysis.json").read_text())["analysis"]["moment_priority"]
PLAYERS = json.loads((ROOT / "data" / "player_summaries.json").read_text())["players"]
ALL = [m["id"] for m in MOMENTS]


def profile(text):
    return Profile.parse(text, players=PLAYERS)


def chosen(text):
    return select(profile(text), MOMENTS, PRIORITY, PLAYERS)


@pytest.mark.parametrize("data, error", [
    ({"mode": "pundit", "voice": "studio", "language": "en"}, "mode"),
    ({"mode": "fan", "voice": "radio", "language": "en"}, "voice"),
    ({"mode": "fan", "voice": "studio", "language": "fr"}, "language"),
    ({"mode": "fan", "voice": "studio", "language": "en", "favourite_team": "London Red"}, "favourite_team"),
    ({"mode": "fan", "voice": "studio", "language": "en", "focus_player": "Cass Dunmor"}, "focus_player"),
    ({"mode": "fan", "voice": "studio", "language": "en", "focus_player": "Owen Strand"}, "focus_player"),
    ({"mode": "fan", "voice": "studio"}, "missing"),
    ({"mode": "fan", "voice": "studio", "language": "en", "colour": "red"}, "unknown"),
])
def test_invalid_profiles_are_rejected(data, error):
    with pytest.raises(ProfileError, match=error):
        Profile.from_dict(data, players=PLAYERS)


def test_profile_key():
    assert profile("analyst/studio/en/none").key() == "analyst-studio-en-none-none"
    assert profile("fan/stadium/en/none/Cass Dunmore").key() == "fan-stadium-en-none-cass_dunmore"
    assert profile("fan/studio/ar/london_red").key() == "fan-studio-ar-london_red-none"


def test_analyst_gets_every_moment_in_story_order():
    assert chosen("analyst/studio/en/none") == ALL


def test_fan_with_no_favourite_gets_only_essential_moments():
    assert chosen("fan/studio/en/none") == ["m07", "m10", "m11"]


def test_fan_favourite_team_moments_first_then_the_rest_in_story_order():
    ids = chosen("fan/stadium/en/london_blue")
    assert ids == ["m01", "m07", "m08", "m10", "m11"]  # m08 names London Blue's shooter
    red = chosen("fan/studio/en/london_red")
    by_id = {m["id"]: m for m in MOMENTS}
    teams = [by_id[i]["team"] for i in red]
    assert teams == sorted(teams, key=lambda t: t != "london_red")
    assert [i for i in red if by_id[i]["team"] == "london_red"] == [i for i in ALL if i in red and by_id[i]["team"] == "london_red"]


def test_focus_player_only_moments_involving_them():
    ids = chosen("fan/stadium/en/none/Cass Dunmore")
    assert ids == ["m01", "m03", "m04", "m05", "m06", "m09", "m11"]
    assert chosen("analyst/studio/en/none/Cass Dunmore") == ids


def test_selection_with_a_moment_not_involving_the_focus_player_fails():
    p = profile("fan/stadium/en/none/Cass Dunmore")
    good = select(p, MOMENTS, PRIORITY, PLAYERS)
    assert selection_problems(p, good, MOMENTS, PRIORITY, PLAYERS) == []
    problems = selection_problems(p, good + ["m07"], MOMENTS, PRIORITY, PLAYERS)
    assert problems == ["m07 does not involve the focus player Cass Dunmore"]
