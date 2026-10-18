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

Selection (select()), in code:
- analyst mode: every key moment.
- fan mode: the Analyst's essential moments, plus supporting moments that
  involve the favourite team or the focus player.
- focus_player: only moments whose players list names that player (this
  narrows either mode).
- favourite_team: that team's moments first, then the rest; each group keeps
  the story order.

A moment involves a team when it is that team's moment (moment["team"]) or
names one of its players (so a save involves the goalkeeper's team and the
shooter's team). A moment involves a player when its players list names them.

The story order is match order. analysis.json's story_arc should be the same
order, but the frozen file has m02 before m01 (its own check flags this), so
the order is taken from key_moments.json and only the arc's roles are used.
"""

import re
from dataclasses import asdict, dataclass

from key_moments import TEAMS

MODES = ("analyst", "fan")
VOICES = ("studio", "stadium")
LANGUAGES = ("en", "ar")
FAVOURITE_TEAMS = TEAMS + ("none",)
NONE = "none"
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


def select(profile: Profile, moments: list, priority: dict, players: dict) -> list:
    """The ids of the moments this profile gets, in the order they are shown.

    moments: key_moments.json's moments (match order). priority: analysis.json's
    moment_priority. players: player_summaries.json's players."""
    essential = set(priority["essential"])
    fav, focus = profile.favourite_team, profile.focus_player

    def wanted(m):
        if focus != NONE and not involves_player(m, focus):
            return False
        if profile.mode == "analyst" or m["id"] in essential:
            return True
        return (fav != NONE and involves_team(m, fav, players)) or (focus != NONE and involves_player(m, focus))

    chosen = [m for m in moments if wanted(m)]
    if fav != NONE:
        chosen = [m for m in chosen if m["team"] == fav] + [m for m in chosen if m["team"] != fav]
    return [m["id"] for m in chosen]


def selection_problems(profile: Profile, ids: list, moments: list, priority: dict, players: dict) -> list:
    """What is wrong with a saved selection for this profile (empty if it is right)."""
    by_id = {m["id"]: m for m in moments}
    problems = [f'"{i}" is not a moment id' for i in ids if i not in by_id]
    if profile.focus_player != NONE:
        problems += [f"{i} does not involve the focus player {profile.focus_player}"
                     for i in ids if i in by_id and not involves_player(by_id[i], profile.focus_player)]
    expected = select(profile, moments, priority, players)
    if not problems and ids != expected:
        problems.append(f"selection is {', '.join(ids)}; this profile selects {', '.join(expected)}")
    return problems
