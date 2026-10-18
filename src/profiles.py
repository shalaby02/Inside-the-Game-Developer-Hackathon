"""Reader profiles and moment selection for the Personalizer. No model calls.

A profile is {mode, voice, language, favourite_team, focus_player}:
- mode: "analyst" (all moments, football terminology and xT numbers, as in
  the Analyst) or "fan" (fewer moments, no xT numbers, "danger" instead of
  "xT", shorter text).
- voice: "studio" or "stadium" (see src/voices.py).
- language: "en" or "ar".
- favourite_team: "london_red", "london_blue" or "none".
- focus_player: a player's full name from data/player_summaries.json, or "none".

Profile.key() names the profile's output file and is part of every cache key.

Selection (select()), in code, always in match order (the story order:
analysis.json's story_arc is in match order):
- focus_player (either mode): every moment whose players list names that
  player, and only those, with no cap.
- analyst mode: every key moment.
- fan mode: every goal and the Analyst's turning point, plus, with a
  favourite team, up to FAN_MAX_SUPPORTING other moments that involve it,
  ranked by xt_added (highest first), at most FAN_MAX_MOMENTS in all. Only
  threat swings have an xt_added fact; moments without one rank after those
  with one, in match order.
- favourite_team: no reordering. involves_favourite() flags the moments that
  involve it, and the recap names that team first.

A moment involves a team when it is that team's moment (moment["team"]) or
names one of its players (so a save involves the goalkeeper's team and the
shooter's team). A moment involves a player when its players list names them.
"""

import re
from dataclasses import asdict, dataclass

from key_moments import TEAMS

MODES = ("analyst", "fan")
VOICES = ("studio", "stadium")
LANGUAGES = ("en", "ar")
FAVOURITE_TEAMS = TEAMS + ("none",)
NONE = "none"
FAN_MAX_MOMENTS = 7
FAN_MAX_SUPPORTING = 3
FIELDS = ("mode", "voice", "language", "favourite_team", "focus_player")


class ProfileError(ValueError):
    pass


@dataclass(frozen=True)
class Profile:
    mode: str
    voice: str
    language: str
    favourite_team: str = NONE
    focus_player: str = NONE

    @classmethod
    def from_dict(cls, data: dict, players=None) -> "Profile":
        """A validated profile. players: the names focus_player may take
        (data/player_summaries.json); None skips that one check."""
        if not isinstance(data, dict):
            raise ProfileError("a profile must be an object")
        unknown = sorted(set(data) - set(FIELDS))
        if unknown:
            raise ProfileError(f"unknown profile field(s): {', '.join(unknown)}")
        missing = [f for f in ("mode", "voice", "language") if f not in data]
        if missing:
            raise ProfileError(f"missing profile field(s): {', '.join(missing)}")
        profile = cls(**data)
        profile.validate(players)
        return profile

    @classmethod
    def parse(cls, text: str, players=None) -> "Profile":
        """From "mode/voice/language/favourite_team[/focus player]", e.g.
        "fan/stadium/en/none/Cass Dunmore"."""
        parts = text.split("/")
        if not 3 <= len(parts) <= 5:
            raise ProfileError(f'expected "mode/voice/language/favourite_team[/focus_player]", got "{text}"')
        return cls.from_dict(dict(zip(FIELDS, parts)), players)

    def validate(self, players=None) -> None:
        for name, value, allowed in (("mode", self.mode, MODES), ("voice", self.voice, VOICES),
                                     ("language", self.language, LANGUAGES),
                                     ("favourite_team", self.favourite_team, FAVOURITE_TEAMS)):
            if value not in allowed:
                raise ProfileError(f'{name} must be one of {", ".join(allowed)}, got {value!r}')
        if not isinstance(self.focus_player, str) or not self.focus_player.strip():
            raise ProfileError("focus_player must be a player's name or \"none\"")
        if players is not None and self.focus_player != NONE and self.focus_player not in players:
            raise ProfileError(f"focus_player {self.focus_player!r} is not in data/player_summaries.json")

    def key(self) -> str:
        """e.g. "fan-stadium-en-none-cass_dunmore"."""
        player = re.sub(r"[^a-z0-9]+", "_", self.focus_player.lower()).strip("_")
        return "-".join([self.mode, self.voice, self.language, self.favourite_team, player])

    def to_dict(self) -> dict:
        return asdict(self)


def team_of(player: str, players: dict) -> str:
    return players[player]["team"]


def involves_team(moment: dict, team: str, players: dict) -> bool:
    return moment["team"] == team or any(
        p in players and team_of(p, players) == team for p in moment["players"])


def involves_player(moment: dict, player: str) -> bool:
    return player in moment["players"]


def involves_favourite(profile: Profile, moment: dict, players: dict) -> bool:
    return profile.favourite_team != NONE and involves_team(moment, profile.favourite_team, players)


def select(profile: Profile, moments: list, analysis: dict, players: dict) -> list:
    """The ids of the moments this profile gets, in match order.

    moments: key_moments.json's moments (match order). analysis: analysis.json's
    analysis (its turning_point). players: player_summaries.json's players."""
    if profile.focus_player != NONE:
        return [m["id"] for m in moments if involves_player(m, profile.focus_player)]
    if profile.mode == "analyst":
        return [m["id"] for m in moments]

    turning = analysis["turning_point"]["moment_id"]
    core = [m for m in moments if m["category"] == "goal" or m["id"] == turning]
    others = [m for m in moments if m not in core and involves_favourite(profile, m, players)]
    # Highest xt_added first; moments without one after, in match order (sorted() is stable).
    others.sort(key=lambda m: (m["facts"].get("xt_added") is None, -m["facts"].get("xt_added", 0)))
    room = max(0, min(FAN_MAX_SUPPORTING, FAN_MAX_MOMENTS - len(core)))
    chosen = {m["id"] for m in core + others[:room]}
    return [m["id"] for m in moments if m["id"] in chosen]


def selection_problems(profile: Profile, ids: list, moments: list, analysis: dict, players: dict) -> list:
    """What is wrong with a saved selection for this profile (empty if it is right)."""
    by_id = {m["id"]: m for m in moments}
    problems = [f'"{i}" is not a moment id' for i in ids if i not in by_id]
    if profile.focus_player != NONE:
        problems += [f"{i} does not involve the focus player {profile.focus_player}"
                     for i in ids if i in by_id and not involves_player(by_id[i], profile.focus_player)]
    if profile.mode == "fan" and profile.focus_player == NONE and len(ids) > FAN_MAX_MOMENTS:
        problems.append(f"fan mode has {len(ids)} moments, at most {FAN_MAX_MOMENTS}")
    expected = select(profile, moments, analysis, players)
    if not problems and ids != expected:
        problems.append(f"selection is {', '.join(ids)}; this profile selects {', '.join(expected)}")
    return problems
