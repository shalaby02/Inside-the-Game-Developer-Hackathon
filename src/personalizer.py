"""Personalizer agent: rewrites the checked narrations and the match result
for one reader profile (src/profiles.py).

Same pattern as src/narrator.py and src/analyst.py: instructions, an output
schema and the Narrator's MODEL_PARAMS, one direct Chat Completions call to
the deployed Foundry model. Code chooses the moments (profiles.select) and
supplies every fact; the model only words them.

Two kinds of call, both returning lines (an array, one display line each):
- one per selected moment: it gets that moment's narration (headline and
  explanation), its facts (narrator.moment_input) and the reader, and
  returns {headline, lines}.
- one recap per profile: code builds its factual skeleton (recap_skeleton:
  result_line, one sentence per goal from score_effect, the turning point,
  and the focus player's stats), and the model only rewords it for voice
  and mode, returning {lines}. It can't add, drop or reorder facts.

Every answer is checked in code, no model calls:
- format: line, sentence and word limits per mode and voice
  (src/voices.py); build_up word for word if used; a distance in metres
  only in a sentence with a shot verb. Moments: the focus player named;
  numbers against the narration (analyst at least as many, fan fewer and no
  xT number). Recap: each skeleton sentence present, its anchor phrase word
  for word and in skeleton order, with its names and minute in the same
  sentence; the final score; the favourite team named first.
- grounding (src/grounding.py): names, numbers and minutes only from that
  moment's facts and narration; the recap only from its skeleton.
- style (src/style_check.py with src/style_rules.py): BLOCKED and the
  moment's fact rules, plus PERSONALIZER_BLOCKED (always), FAN_BLOCKED in fan
  mode, and CONNECTORS with PERSONALIZER_CONNECTORS in the recap and in
  analyst-mode moments.
- polish (src/polish_check.py) and term backing (src/term_check.py; per
  sentence in the recap, as in the Analyst).
On a failure the model gets the failures and tries again, up to MAX_RETRIES
times; after that the item is marked failed and kept for inspection only.

Arabic (language "ar") is not built yet: build_* raise NotImplementedError.
"""

import json
import re
from decimal import Decimal

import grounding
import polish_check
import style_check
import term_check
from analyst import CONNECTOR_RULES, TERM_WORDS, XT_FACTS, sentence_subject
from key_moments import TEAM_NAMES, other
from match_summary import ordinal
from narrator import FIELD_NOTES, MODEL_PARAMS, _borrows, moment_input, sentences
from profiles import NONE, Profile
from style_rules import (DISTANCE, FAN_BLOCKED, MAX_NUMBERS, PERSONALIZER_BLOCKED, PERSONALIZER_CONNECTORS,
                         PROMPT_RULES, SHOT_VERBS, TERMS, CONNECTORS)
from voices import INTERJECTIONS, VOICES

MAX_RETRIES = 2
MAX_WORDS = {"analyst": 60, "fan": 35}          # one moment's text
MAX_HEADLINE_WORDS = 16
RECAP_WORDS = {"analyst": 130, "fan": 100}
MAX_BURST_WORDS = 3   # a Stadium burst such as "What a save!": no facts, so not a skeleton sentence
CHECK_KEYS = ("format_problems", "grounding", "style", "polish", "terms")
# Capitalised words that are not names: analysis terms and the Stadium voice's interjections.
EXTRA_NAMES = TERM_WORDS + INTERJECTIONS
QUOTED_FACTS = ("build_up", "counter_label", "score_effect")
ALL_CONNECTOR_RULES = CONNECTOR_RULES + [(p, f'"{w}" {why}; state the facts side by side')
                                         for w, p, why in PERSONALIZER_CONNECTORS]

_NUM = re.compile(r"(?<![\d.])\d+(?:\.\d+)?")
_COUNTED = re.compile(r"\d+(?:\.\d+)?(?:-\d+(?:\.\d+)?)?")  # as style_check counts: "1-0" is one number
_WORDS = re.compile(r"[\w'’.-]+")
_DISTANCE = re.compile(rf"(?<![\w.]){DISTANCE}(?![\w-])", re.I)
_SHOT_VERB = re.compile(rf"(?<![\w-])(?:{SHOT_VERBS})(?![\w-])", re.I)

_LINES = {"type": "array", "items": {"type": "string"}}


def _schema(name, properties):
    return {"type": "json_schema", "json_schema": {"name": name, "strict": True, "schema": {
        "type": "object", "properties": properties, "required": list(properties),
        "additionalProperties": False}}}


MOMENT_SCHEMA = _schema("personalized_moment", {"headline": {"type": "string"}, "lines": _LINES})
RECAP_SCHEMA = _schema("personalized_recap", {"lines": _LINES})


def text_of(output) -> str:
    """The lines as one string, for the checks and for display."""
    return " ".join(line.strip() for line in output["lines"])


# ------------------------------------------------------------ instructions

def mode_rules(mode: str, max_words: int) -> str:
    if mode == "analyst":
        return """\
Mode: analyst. The reader wants the football detail.
- Use football analysis terms where the facts back them, and quote xT numbers exactly as given.
- For one moment: keep at least as many numbers as the narration (headline and explanation together); spread them over headline and lines.
- Analysis terms need their fact: """ + "; ".join(f'"{label}" needs {need}' for label, _, _, need in TERMS) + f""".
- lines: at most {max_words} words in all."""
    return f"""\
Mode: fan. The reader is a casual fan. These rules replace the number and xT rules above.
- No xT at all: never write "xT", "expected threat" or any xT number (shot_zone_value, xt_added, zone_start_value, zone_end_value, key_pass_xt_added, team_threat, opponent_threat, top_player_threat and the like). Say "danger" instead: "a dangerous spot", "London Red piled on the danger".
- Use fewer numbers than the narration. Minutes, the score and distances in metres are fine. You may leave numbers out; never add one.
- No analyst jargon: no final-third entries, penalty-area entries, progressive actions, shot-location value or build-up phase.
- lines: short, at most {max_words} words in all."""


NEUTRAL = """\
- Stay neutral, whoever the reader supports: never take a side, never write "we", "our", "us" or "I", and never call anything lucky, unlucky, cruel or deserved.
- Never say how the match ended unless it is in the input: no "wins it", "seals it", "secures", "winner".
- Never write "he", "she", "his" or "her": the facts give no player's gender. Repeat the name instead.
- Never say one thing sparked or caused another."""

DISTANCE_RULE = ("- A distance in metres belongs to a shot: write it only in a sentence that says scored, missed, "
                 "denied, saved, stopped or shot (never \"passed to Cass Dunmore from 6.4 metres\").")

LINES_RULE = ("- lines: an array of display lines, each a complete line that ends with \".\", \"!\" or \"?\". "
              "Never put a line break inside a line.")


def connector_rule() -> str:
    words = ", ".join(f'"{w}"' for w, _, _ in CONNECTORS + PERSONALIZER_CONNECTORS)
    return (f"- No causal or temporal connectors such as {words}: state facts side by side. Quoting a fact "
            "phrase (build_up, result_line) in full is fine.")


def voice_rules(voice: str) -> str:
    v = VOICES[voice]
    return (f"{v['traits']}\n- At most {v['max_sentences']} sentences in a moment, each at most "
            f"{v['max_sentence_words']} words, not counting a fact phrase quoted word for word.")


def moment_instructions(profile: Profile) -> str:
    return f"""\
You are the Personalizer for a football match recap. You rewrite one key moment for one reader.

xT (expected threat) is how likely a team is to score soon from where it has the ball; "xT added" is how much a pass or carry raised it.

You get one JSON object:
- reader: mode, voice and focus_player (null when there is none).
- moment: the moment's facts, computed in code.
- narration: the Narrator's checked headline and explanation of the same moment.

Write:
- headline: one short line, at most {MAX_HEADLINE_WORDS} words, in sentence case (capitalise only the first word and names).
- lines: the moment, retold for this reader in the voice below.
{LINES_RULE}

Facts:
- Use only the names, numbers, minutes and terms in moment and narration. Never add a fact, number, name, or a detail of how something looked. Leaving facts out is fine.
- Quote numbers exactly as given, digit for digit. No rounding, conversions or arithmetic.
- Say a minute as the ordinal of the minute field, such as "the 61st minute". A score may be written like "1-0", using team_score and opponent_score.
- If you use the build_up sentence, copy it word for word as one of your sentences.
- If focus_player is set, tell the moment through that player, by full name, as far as the facts allow.
{DISTANCE_RULE}
{NEUTRAL}
{connector_rule() if profile.mode == "analyst" else ""}
{PROMPT_RULES}

{FIELD_NOTES}

{mode_rules(profile.mode, MAX_WORDS[profile.mode])}

{voice_rules(profile.voice)}

Return only the JSON object."""


def recap_instructions(profile: Profile) -> str:
    stadium = profile.voice == "stadium"
    return f"""\
You are the Personalizer for a football match recap. You reword a recap that code has already written, for one reader.

You get one JSON object:
- reader: mode, voice, favourite_team and focus_player (null when there is none).
- skeleton: the recap's sentences, in order. They hold every fact the recap may use.
- word_for_word: phrases you must copy exactly, each inside the sentence that has it.

Write lines: the skeleton reworded in the voice below.
{LINES_RULE}
- Keep every skeleton sentence, in the same order. Keep each one's names, minutes, numbers and word_for_word phrases in that one sentence.
- Add nothing: no fact, name, number, minute or detail that is not in the skeleton. Drop nothing. Do not reorder.
- You may change the words around the facts, and split a long sentence into short lines.{' You may add up to 3 short bursts of at most 3 words with no facts, such as "Goal!" or "What a save!".' if stadium else ''}
- Keep the first sentence first: when favourite_team is set, it already names favourite_team first.
{connector_rule()}
{DISTANCE_RULE}
{NEUTRAL}
- One point per sentence, with at most {MAX_NUMBERS} numbers in any one sentence (minutes and scores count).

{mode_rules(profile.mode, RECAP_WORDS[profile.mode])}

{voice_rules(profile.voice)}

Return only the JSON object."""


# ------------------------------------------------------------ inputs

def _require_english(profile: Profile) -> None:
    if profile.language != "en":
        raise NotImplementedError("Arabic output is not built yet (Part B)")


def reader(profile: Profile, recap: bool = False) -> dict:
    out = {"mode": profile.mode, "voice": profile.voice}
    if recap:
        out["favourite_team"] = TEAM_NAMES.get(profile.favourite_team)
    out["focus_player"] = None if profile.focus_player == NONE else profile.focus_player
    return out


def build_moment_input(moment: dict, narration: dict, profile: Profile) -> dict:
    """What the model sees for one moment, and what the checks run against."""
    _require_english(profile)
    # Without the clock's second: no text uses it, and grounding matches numbers
    # by value, so "from 14 metres" would pass on m07's second (14).
    facts = {k: v for k, v in moment_input(moment).items() if k != "second"}
    return {"reader": reader(profile), "moment": facts,
            "narration": {"headline": narration["headline"], "explanation": narration["explanation"]}}


def player_card(profile: Profile, players: dict):
    """The focus player's player_summaries facts, as the reader may see them:
    team as its display name, moment_ids left out, and no xT in fan mode."""
    if profile.focus_player == NONE:
        return None
    facts = {k: v for k, v in players[profile.focus_player].items() if k != "moment_ids"}
    facts["team"] = TEAM_NAMES[facts["team"]]
    if profile.mode == "fan":
        facts.pop("xt_added")
    return {"name": profile.focus_player, **facts}


def _count(n, word):
    return f"{n} {word}" + ("" if n == 1 else "s")


def recap_skeleton(profile: Profile, analysis: dict, summary: dict, moments: list, players: dict) -> list:
    """The recap's facts as sentences, built in code, in match order.

    Each sentence is {"text", "anchor", "needs", "minutes", "moment_ids"}:
    anchor is the phrase that must appear word for word, in skeleton order;
    needs are the names and minutes that must be in the same sentence as it.
    Sentences: result_line (with the favourite team named first when there is
    one), one per goal from score_effect, the turning point, and the focus
    player's stats."""
    by_id = {m["id"]: m for m in moments}
    result = summary["result_line"]
    fav = profile.favourite_team
    if fav != NONE:
        opening = f"{TEAM_NAMES[fav]} and {TEAM_NAMES[other(fav)]} met, and {result}."
    else:
        opening = f"{result}."
    out = [{"text": opening, "anchor": result, "needs": [TEAM_NAMES[fav]] if fav != NONE else [], "minutes": [],
            "moment_ids": []}]

    for g in summary["goals"]:
        effect = by_id[g["moment_id"]]["facts"]["score_effect"]
        minute = f"{ordinal(g['minute'])} minute"
        out.append({"text": f"{g['scorer']}'s goal in the {minute} {effect}.", "anchor": effect,
                    "needs": [g["scorer"], minute], "minutes": [g["minute"]], "moment_ids": [g["moment_id"]]})

    tp = by_id[analysis["turning_point"]["moment_id"]]
    f = tp["facts"]
    if tp["category"] == "goal":
        scorer, minute = tp["players"][0], f"{ordinal(tp['minute'])} minute"
        text = f"The turning point was {scorer}'s goal in the {minute}"
        if profile.mode == "analyst":
            text += (f": its key pass added {f['key_pass_xt_added']} xT and the shot came from a spot with xT "
                     f"{f['shot_zone_value']}")
        needs, minutes = [scorer, minute], [tp["minute"]]
    else:  # momentum_shift
        team = TEAM_NAMES[tp["team"]]
        start, last = f"{ordinal(f['start_minute'])} minute", f"{ordinal(f['last_minute'])} minute"
        text = f"The turning point was {team}'s spell from the {start} to the {last}"
        if profile.mode == "analyst":
            text += f": {team} added {f['team_threat']} xT, {TEAM_NAMES[other(tp['team'])]} {f['opponent_threat']}"
        needs, minutes = [team, start], [f["start_minute"], f["last_minute"]]
    out.append({"text": text + ".", "anchor": "turning point", "needs": needs, "minutes": minutes,
                "moment_ids": [tp["id"]]})

    card = player_card(profile, players)
    if card:
        passes = f"completed {card['passes_completed']} of {card['passes_attempted']} passes"
        parts = [passes]
        if profile.mode == "analyst":
            parts.append(f"made {_count(card['final_third_entries'], 'final-third entry').replace('entrys', 'entries')}")
        parts.append(f"took {_count(card['shots'], 'shot')}")
        if "saves" in card:
            parts.append(f"made {_count(card['saves'], 'save')}")
        if profile.mode == "analyst":
            parts.append(f"added {card['xt_added']} xT")
        text = f"{card['name']} " + ", ".join(parts[:-1]) + f" and {parts[-1]}."
        out.append({"text": text, "anchor": passes, "needs": [card["name"]] + parts, "minutes": [],
                    "moment_ids": []})
    return out


def build_recap_input(profile: Profile, analysis: dict, summary: dict, moments: list, players: dict) -> dict:
    """What the model sees for the recap."""
    _require_english(profile)
    skeleton = recap_skeleton(profile, analysis, summary, moments, players)
    return {"reader": reader(profile, recap=True), "skeleton": [s["text"] for s in skeleton],
            "word_for_word": [s["anchor"] for s in skeleton if s["anchor"] != "turning point"]}


def recap_context(profile: Profile, analysis: dict, summary: dict, moments: list, players: dict) -> dict:
    """What the recap checks run against: the skeleton, the full facts of its
    moments (term backing, and the xT numbers fan mode must not use), the
    focus player's card and the final score."""
    skeleton = recap_skeleton(profile, analysis, summary, moments, players)
    by_id = {m["id"]: m for m in moments}
    ids = [i for s in skeleton for i in s["moment_ids"]]
    return {"skeleton": skeleton, "moments": [{"id": i, **moment_input(by_id[i])} for i in dict.fromkeys(ids)],
            "card": player_card(profile, players), "final_score": summary["final_score"],
            "favourite_team": profile.favourite_team, "focus_player": profile.focus_player}


# ------------------------------------------------------------ checks

def _dec(x) -> Decimal:
    return abs(Decimal(str(x)).normalize())


def xt_values(moment_facts: list, card=None) -> set:
    values = {_dec(v) for m in moment_facts for k, v in m["facts"].items() if k in XT_FACTS}
    if card and "xt_added" in card:
        values.add(_dec(card["xt_added"]))
    return values


def xt_numbers(text: str, values: set) -> list:
    return [n for n in _NUM.findall(text) if _dec(n) in values]


def count_numbers(*texts) -> int:
    return sum(len(_COUNTED.findall(t)) for t in texts)


def word_count(text: str) -> int:
    return len(_WORDS.findall(text))


def is_burst(sentence: str) -> bool:
    """A short Stadium burst with no facts: "Goal!", "What a save!"."""
    return word_count(sentence) <= MAX_BURST_WORDS and not re.search(r"\d", sentence) and not any(
        name in sentence for name in TEAM_NAMES.values())


def distance_problems(where: str, text: str) -> list:
    return [f'{where}: "{s}" gives a distance in metres without a shot verb (scored, missed, denied, saved, '
            f'stopped, shot); a distance belongs to the shot' for s in sentences(text)
            if _DISTANCE.search(s) and not _SHOT_VERB.search(s)]


def voice_problems(where: str, text: str, voice: str, phrases: list, max_sentences=None) -> list:
    v = VOICES[voice]
    problems = []
    if text.count("!") > v["max_exclamations"]:
        problems.append(f"{where}: {text.count('!')} exclamation marks, the {voice} voice allows "
                        f"{v['max_exclamations']}")
    parts = sentences(text)
    if max_sentences is not None and len(parts) > max_sentences:
        problems.append(f"{where} has {len(parts)} sentences, the {voice} voice allows at most {max_sentences}")
    for s in parts:
        # Words of a fact phrase quoted in full (build_up, counter_label, result_line, ...)
        # don't count: they must be word for word. Longest first, each word counted once.
        rest = s
        for p in sorted(set(phrases), key=len, reverse=True):
            rest = rest.replace(p, " ")
        n = word_count(rest)
        if n > v["max_sentence_words"]:
            problems.append(f'{where}: "{s}" has {n} words of its own, the {voice} voice allows '
                            f'{v["max_sentence_words"]} per sentence')
    return problems


def lines_problems(output, string_fields=()) -> list:
    """The output's shape: string_fields are non-empty strings, lines a non-empty
    list of non-empty lines, each ending with . ! or ? and without a line break."""
    if not isinstance(output, dict):
        return ["response is not a JSON object"]
    problems = [f"{f} is missing or empty" for f in string_fields
                if not isinstance(output.get(f), str) or not output[f].strip()]
    lines = output.get("lines")
    if not isinstance(lines, list) or not lines or not all(isinstance(x, str) and x.strip() for x in lines):
        return problems + ["lines must be a non-empty list of non-empty strings"]
    for i, line in enumerate(lines):
        if "\n" in line or "\r" in line:
            problems.append(f"lines[{i}] has a line break inside it; make it separate lines")
        if not re.search(r"[.!?][\"”’')]*\s*$", line):
            problems.append(f'lines[{i}] "...{line.strip()[-20:]}" must end with ".", "!" or "?"')
    return problems


def moment_format_problems(head: str, text: str, inputs: dict, profile: Profile) -> list:
    facts, narration = inputs["moment"], inputs["narration"]
    phrases = [facts["facts"][k] for k in QUOTED_FACTS if k in facts["facts"]]
    problems = voice_problems("text", text, profile.voice, phrases, VOICES[profile.voice]["max_sentences"])
    problems += voice_problems("headline", head, profile.voice, phrases)
    problems += distance_problems("headline", head) + distance_problems("text", text)
    if word_count(text) > MAX_WORDS[profile.mode]:
        problems.append(f"text has {word_count(text)} words, {profile.mode} mode allows {MAX_WORDS[profile.mode]}")
    if word_count(head) > MAX_HEADLINE_WORDS:
        problems.append(f"headline has {word_count(head)} words, at most {MAX_HEADLINE_WORDS}")
    build_up = facts["facts"].get("build_up")
    if build_up and _borrows(text, build_up) and build_up not in text:
        problems.append(f'use the build_up sentence word for word: "{build_up}"')
    if profile.focus_player != NONE and profile.focus_player not in head + " " + text:
        problems.append(f"name the focus player {profile.focus_player}")
    # Both modes are measured against the narration, so a fan version always has
    # fewer numbers than the analyst version of the same moment.
    mine, theirs = count_numbers(head, text), count_numbers(narration["headline"], narration["explanation"])
    if profile.mode == "analyst" and mine < theirs:
        problems.append(f"analyst mode: keep at least as many numbers as the narration ({mine}, the narration "
                        f"has {theirs})")
    if profile.mode == "fan":
        for n in xt_numbers(head + " " + text, xt_values([facts])):
            problems.append(f'fan mode: "{n}" is an xT number; say "danger" instead')
        if mine >= theirs:
            problems.append(f"fan mode: use fewer numbers than the narration ({mine}, the narration has {theirs})")
    return problems


def _finish(result: dict, problems: list) -> dict:
    result["format_problems"] = problems
    result["passed"] = not problems and all(result[k] and result[k]["passed"]
                                            for k in ("grounding", "style", "polish", "terms"))
    return result


def _empty(problems):
    return {"format_problems": problems, "grounding": None, "style": None, "polish": None, "terms": None,
            "passed": False}


def run_moment_checks(output, inputs: dict, profile: Profile) -> dict:
    """Every check on one personalized moment, no model calls."""
    problems = lines_problems(output, ("headline",))
    if problems:
        return _empty(problems)
    head, text = output["headline"], text_of(output)
    fields = {"headline": head, "text": text}
    facts = inputs["moment"]
    rules = PERSONALIZER_BLOCKED + (FAN_BLOCKED if profile.mode == "fan" else ALL_CONNECTOR_RULES)
    subj = term_check.subject([facts])
    result = {
        "grounding": grounding.check(fields, [facts, inputs["narration"]], extra_names=EXTRA_NAMES).to_dict(),
        "style": style_check.check(fields, facts, extra_rules=rules).to_dict(),
        "polish": polish_check.check(fields, sentence_fields=("text",)).to_dict(),
        "terms": term_check.check([(k, v, subj) for k, v in fields.items()]).to_dict(),
    }
    return _finish(result, moment_format_problems(head, text, inputs, profile))


def first_team_named(text: str):
    found = [(text.find(name), team) for team, name in TEAM_NAMES.items() if name in text]
    return min(found)[1] if found else None


def skeleton_problems(text: str, skeleton: list) -> list:
    """Every skeleton sentence is in the recap, in order: its anchor word for
    word, after the previous one, with its names and minute in the same
    sentence. Nothing else may carry facts (grounding checks that)."""
    problems, pos = [], 0
    parts = sentences(text)
    for k, s in enumerate(skeleton, 1):
        anchor = s["anchor"]
        at = text.find(anchor, pos)
        if at < 0:
            problems.append(f'skeleton sentence {k} is {"out of order" if anchor in text else "missing"}: '
                            f'keep "{anchor}" word for word, in skeleton order ("{s["text"]}")')
            continue
        pos = at + len(anchor)
        holder = next((p for p in parts if anchor in p), "")
        for need in s["needs"]:
            if need not in holder:
                problems.append(f'skeleton sentence {k}: "{need}" must be in the same sentence as "{anchor}"')
    return problems


def recap_format_problems(text: str, context: dict, profile: Profile) -> list:
    skeleton = context["skeleton"]
    parts = sentences(text)
    bursts = [p for p in parts if is_burst(p)]
    max_bursts = VOICES[profile.voice]["max_exclamations"]
    problems = skeleton_problems(text, skeleton)
    if len(bursts) > max_bursts:
        problems.append(f"{len(bursts)} short bursts ({'; '.join(bursts)}), the {profile.voice} voice allows "
                        f"{max_bursts}")
    if len(parts) - len(bursts) > 2 * len(skeleton):
        problems.append(f"recap has {len(parts) - len(bursts)} sentences for {len(skeleton)} skeleton sentences")
    if word_count(text) > RECAP_WORDS[profile.mode]:
        problems.append(f"recap has {word_count(text)} words, {profile.mode} mode allows {RECAP_WORDS[profile.mode]}")
    problems += voice_problems("recap", text, profile.voice, [s["anchor"] for s in skeleton])
    problems += distance_problems("recap", text)

    final = context["final_score"]
    winner, loser = sorted(final, key=final.get, reverse=True)
    if not re.search(rf"(?<![\d.]){final[winner]}\s*[-–]\s*{final[loser]}(?![\d.])", text):
        problems.append(f"recap must give the final score {final[winner]}-{final[loser]}, winner's goals first")
    fav = context["favourite_team"]
    if fav != NONE and first_team_named(text) != fav:
        problems.append(f"the first team named must be the favourite team {TEAM_NAMES[fav]}")
    if profile.mode == "fan":
        for x in xt_numbers(text, xt_values(context["moments"], context["card"])):
            problems.append(f'fan mode: "{x}" is an xT number; say "danger" instead')
    return problems


def run_recap_checks(output, inputs: dict, context: dict, profile: Profile) -> dict:
    """Every check on one recap, no model calls."""
    problems = lines_problems(output)
    if problems:
        return _empty(problems)
    text = text_of(output)
    skeleton = context["skeleton"]
    # Grounding only against the skeleton: no fact beyond it.
    facts = {"sentences": [s["text"] for s in skeleton], "minute": [m for s in skeleton for m in s["minutes"]]}
    card = context["card"] or {}
    candidates = (context["moments"], [(k, v) for k, v in card.items()
                                      if isinstance(v, (int, float)) and not isinstance(v, bool)])
    rules = ALL_CONNECTOR_RULES + PERSONALIZER_BLOCKED + (FAN_BLOCKED if profile.mode == "fan" else [])
    result = {
        "grounding": grounding.check(text, facts, extra_names=EXTRA_NAMES).to_dict(),
        # One field per sentence, so the shared MAX_NUMBERS applies per sentence, as the
        # Analyst applies it per phase note (at most 2 sentences).
        "style": style_check.check({f"recap[{k}]": s for k, s in enumerate(sentences(text))} or {"recap": text},
                                   {"phrases": [s["anchor"] for s in skeleton] + facts["sentences"]},
                                   moment_rules=False, extra_rules=rules).to_dict(),
        "polish": polish_check.check({"recap": text}, sentence_fields=("recap",)).to_dict(),
        "terms": term_check.check([("recap", s, sentence_subject(s, candidates))
                                   for s in sentences(text)]).to_dict(),
    }
    return _finish(result, recap_format_problems(text, context, profile))


def flagged(checks: dict) -> list:
    """Every flagged item of a run_*_checks() result as one line of text."""
    lines = [f"format: {p}" for p in checks["format_problems"]]
    for kind in ("grounding", "style", "polish", "terms"):
        if checks[kind]:
            lines += [f'{kind}: {o["type"]} "{o["value"]}": {o["reason"]}' for o in checks[kind]["offending"]]
    return lines


# ------------------------------------------------------------ the model call

def call_model(client, deployment: str, messages: list, schema: dict):
    """One model call. Returns (output or None, problem or None, raw reply text or None)."""
    response = client.chat.completions.create(model=deployment, messages=messages, response_format=schema,
                                              **MODEL_PARAMS)
    choice = response.choices[0]
    content = choice.message.content
    if not content:
        return None, f"empty reply (finish_reason={choice.finish_reason})", None
    try:
        return json.loads(content), None, content
    except json.JSONDecodeError:
        return None, "reply is not valid JSON", content


def generate(client, deployment: str, instructions: str, inputs: dict, schema: dict, check) -> dict:
    """Ask, check, and retry with the failures, up to MAX_RETRIES times.

    check(output) -> run_*_checks() result. Returns {"status": "ok" | "failed",
    "output", "checks", "retries", "attempts"}. A failed output must not be used."""
    messages = [{"role": "system", "content": instructions},
                {"role": "user", "content": json.dumps(inputs, ensure_ascii=False)}]
    attempts = []
    for attempt in range(1 + MAX_RETRIES):
        output, problem, raw = call_model(client, deployment, messages, schema)
        checks = check(output)
        if problem:
            checks = _empty([problem])
        attempts.append({"attempt": attempt + 1, "output": output, **{k: checks[k] for k in CHECK_KEYS}})
        if checks["passed"]:
            break
        if raw is not None:
            messages.append({"role": "assistant", "content": raw})
        messages.append({"role": "user", "content": (
            "Your answer broke the rules:\n- " + "\n- ".join(flagged(checks)) +
            "\nRewrite it following every rule. Use only names, numbers and minutes exactly as they appear "
            "in the input, and leave out anything you cannot support from it.")})
    last = attempts[-1]
    return {"status": "ok" if checks["passed"] else "failed", "output": last["output"],
            "checks": {k: last[k] for k in CHECK_KEYS}, "retries": len(attempts) - 1, "attempts": attempts}


def personalize_moment(client, deployment: str, moment: dict, narration: dict, profile: Profile) -> dict:
    inputs = build_moment_input(moment, narration, profile)
    return {"id": moment["id"], **generate(client, deployment, moment_instructions(profile), inputs, MOMENT_SCHEMA,
                                           lambda out: run_moment_checks(out, inputs, profile))}


def personalize_recap(client, deployment: str, profile: Profile, analysis, summary, moments, players) -> dict:
    inputs = build_recap_input(profile, analysis, summary, moments, players)
    context = recap_context(profile, analysis, summary, moments, players)
    return generate(client, deployment, recap_instructions(profile), inputs, RECAP_SCHEMA,
                    lambda out: run_recap_checks(out, inputs, context, profile))
