"""Personalizer agent: rewrites the checked narrations and the Analyst's story
for one reader profile (src/profiles.py).

Same pattern as src/narrator.py and src/analyst.py: instructions, an output
schema and the Narrator's MODEL_PARAMS, one direct Chat Completions call to
the deployed Foundry model. Code chooses the moments (profiles.select) and
supplies every fact; the model only words them.

Two kinds of call:
- one per selected moment: it gets that moment's narration (headline and
  explanation), its facts (narrator.moment_input) and the reader, and
  returns {headline, text}.
- one recap per profile: 3-5 sentences from analysis.json (match_headline,
  story_arc roles, turning_point) and match_summary.json's result_line, plus
  the focus player's player_summaries facts when there is one.

Every answer is checked in code, no model calls:
- format: sentence and word limits per mode and voice (src/voices.py),
  build_up word for word if used. Fan mode: no xT number and fewer numbers
  than the narration. Recap: the final score and winning team, the
  favourite team named first, the focus player named.
- grounding (src/grounding.py): names, numbers and minutes only from that
  moment's facts and narration (the recap: from its own input).
- style (src/style_check.py with src/style_rules.py): BLOCKED and the
  moment's fact rules, plus PERSONALIZER_BLOCKED (always neutral), FAN_BLOCKED in fan
  mode, and the Analyst's CONNECTORS in the recap.
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
from analyst import CONNECTOR_RULES, PEOPLE_KEYS, TERM_WORDS, XT_FACTS, sentence_subject
from key_moments import TEAM_NAMES
from narrator import FIELD_NOTES, MODEL_PARAMS, _borrows, moment_input, sentences
from profiles import NONE, Profile
from style_rules import CONNECTORS, FAN_BLOCKED, MAX_NUMBERS, PERSONALIZER_BLOCKED, PROMPT_RULES, TERMS
from voices import INTERJECTIONS, VOICES

MAX_RETRIES = 2
MAX_WORDS = {"analyst": 60, "fan": 35}          # one moment's text
MAX_HEADLINE_WORDS = 16
RECAP_SENTENCES = (3, 5)
RECAP_WORDS = {"analyst": 120, "fan": 90}
CHECK_KEYS = ("format_problems", "grounding", "style", "polish", "terms")
# Capitalised words that are not names: analysis terms and the Stadium voice's interjections.
EXTRA_NAMES = TERM_WORDS + INTERJECTIONS
QUOTED_FACTS = ("build_up", "counter_label", "score_effect")
STORY_FACTS = ("score_effect", "counter_label", "start_minute", "last_minute", "run_end")

_NUM = re.compile(r"(?<![\d.])\d+(?:\.\d+)?")
_COUNTED = re.compile(r"\d+(?:\.\d+)?(?:-\d+(?:\.\d+)?)?")  # as style_check counts: "1-0" is one number
_WORDS = re.compile(r"[\w'’.-]+")


def _schema(name, fields):
    return {"type": "json_schema", "json_schema": {"name": name, "strict": True, "schema": {
        "type": "object", "properties": {f: {"type": "string"} for f in fields},
        "required": list(fields), "additionalProperties": False}}}


MOMENT_SCHEMA = _schema("personalized_moment", ("headline", "text"))
RECAP_SCHEMA = _schema("personalized_recap", ("text",))


# ------------------------------------------------------------ instructions

def mode_rules(mode: str, max_words: int) -> str:
    if mode == "analyst":
        return """\
Mode: analyst. The reader wants the football detail.
- Use football analysis terms where the facts back them, and quote xT numbers exactly as given.
- For one moment: keep at least as many numbers as the narration (headline and explanation together); spread them over headline and text.
- Analysis terms need their fact: """ + "; ".join(f'"{label}" needs {need}' for label, _, _, need in TERMS) + f""".
- text: at most {max_words} words."""
    return f"""\
Mode: fan. The reader is a casual fan. These rules replace the number and xT rules above.
- No xT at all: never write "xT", "expected threat" or any xT number (shot_zone_value, xt_added, zone_start_value, zone_end_value, key_pass_xt_added, team_threat, opponent_threat, top_player_threat and the like). Say "danger" instead: "a dangerous spot", "London Red piled on the danger".
- Use fewer numbers than the narration. Minutes, the score and distances in metres are fine. You may leave numbers out; never add one.
- No analyst jargon: no final-third entries, penalty-area entries, progressive actions, shot-location value or build-up phase.
- text: short, at most {max_words} words."""

NEUTRAL = """\
- Stay neutral, whoever the reader supports: never take a side, never write "we", "our", "us" or "I", and never call anything lucky, unlucky, cruel or deserved.
- Never say how the match ended unless it is in the input: no "wins it", "seals it", "secures", "winner".
- Never write "he", "she", "his" or "her": the facts give no player's gender. Repeat the name instead."""


def voice_rules(voice: str) -> str:
    v = VOICES[voice]
    return (f"{v['traits']}\n- At most {v['max_sentences']} sentences in text"
            f" (recap: its own limit), each at most {v['max_sentence_words']} words,"
            f" except a fact sentence such as build_up quoted word for word.")


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
- text: the moment, retold for this reader in the voice below.

Facts:
- Use only the names, numbers, minutes and terms in moment and narration. Never add a fact, number, name, or a detail of how something looked. Leaving facts out is fine.
- Quote numbers exactly as given, digit for digit. No rounding, conversions or arithmetic.
- Say a minute as the ordinal of the minute field, such as "the 61st minute". A score may be written like "1-0", using team_score and opponent_score.
- If you use the build_up sentence, copy it word for word as one of your sentences.
- If focus_player is set, tell the moment through that player, by full name, as far as the facts allow.
{NEUTRAL}
{PROMPT_RULES}

{FIELD_NOTES}

{mode_rules(profile.mode, MAX_WORDS[profile.mode])}

{voice_rules(profile.voice)}

Return only the JSON object."""


def recap_instructions(profile: Profile) -> str:
    connectors = ", ".join(f'"{w}"' for w, _, _ in CONNECTORS)
    lo, hi = RECAP_SENTENCES
    return f"""\
You are the Personalizer for a football match recap. You write the match recap for one reader.

You get one JSON object:
- reader: mode, voice, favourite_team and focus_player (null when there is none).
- match_headline and result_line: the result in words, checked in code.
- turning_point: the moment where the Analyst says the match turned (in analyst mode, with the Analyst's reason).
- story: the moments this reader follows, in match order, each with its role in the Analyst's story arc.
- focus_player (only when set): that player's match facts.

Write text: a recap of {lo} to {hi} sentences. Every ".", "!" or "?" ends a sentence and counts, short lines such as "Goal!" included.
- Give the final score as result_line does, winner's goals first ("2-1"), and name the winning team.
- If favourite_team is set, the first team you name must be favourite_team. Tell it from a neutral view all the same.
- If focus_player is set, name them by full name and use their facts.
- Use only the names, numbers and minutes in the input, exactly as given. No totals, differences or percentages of your own.
- Say a minute as an ordinal ("the 61st minute"); a spell as "from the 70th minute to the 93rd minute".
- One point per sentence, with at most {MAX_NUMBERS} numbers in any one sentence (minutes and scores count).
- No causal or temporal connectors such as {connectors}: state facts side by side. Quoting a fact phrase such as result_line in full is fine.
{NEUTRAL}
{PROMPT_RULES}

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


def story_entry(moment: dict, role: str) -> dict:
    """One moment for the recap: who, when and what it did, without the xT numbers."""
    mi = moment_input(moment)
    out = {"role": role, "category": mi["category"], "tags": mi["tags"], "minute": mi["minute"],
           "team": mi["team"], "opponent": mi["opponent"]}
    out.update({k: mi[k] for k in PEOPLE_KEYS if k in mi})
    out.update({k: mi["facts"][k] for k in STORY_FACTS if k in mi["facts"]})
    return out


def recap_moment_ids(moments: list, selected: list, analysis: dict) -> list:
    """The selected moments plus every essential one (the goals, the turning
    point): the result can't be told without them. In match order."""
    wanted = set(selected) | set(analysis["moment_priority"]["essential"]) | {analysis["turning_point"]["moment_id"]}
    return [m["id"] for m in moments if m["id"] in wanted]


def build_recap_input(profile: Profile, analysis: dict, summary: dict, moments: list, selected: list,
                      players: dict) -> dict:
    _require_english(profile)
    by_id = {m["id"]: m for m in moments}
    roles = {a["moment_id"]: a["role"] for a in analysis["story_arc"]}
    tp = analysis["turning_point"]
    turning = story_entry(by_id[tp["moment_id"]], "turning_point")
    if profile.mode == "analyst":  # the reason quotes xT numbers, which fan mode never uses
        turning["reason"] = tp["reason"]
    out = {"reader": reader(profile, recap=True), "match_headline": analysis["match_headline"],
           "result_line": summary["result_line"], "turning_point": turning,
           "story": [story_entry(by_id[i], roles.get(i, "other"))
                     for i in recap_moment_ids(moments, selected, analysis)]}
    card = player_card(profile, players)
    if card:
        out["focus_player"] = card
    return out


def recap_context(profile: Profile, analysis: dict, summary: dict, moments: list, selected: list) -> dict:
    """What the recap checks need besides its input: the full facts of its
    moments (for term backing and the xT numbers fan mode must not use) and
    the final score."""
    by_id = {m["id"]: m for m in moments}
    ids = recap_moment_ids(moments, selected, analysis)
    return {"moments": [{"id": i, **moment_input(by_id[i])} for i in ids],
            "final_score": summary["final_score"], "favourite_team": profile.favourite_team,
            "focus_player": profile.focus_player}


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


def _shape(output, fields) -> list:
    if not isinstance(output, dict):
        return ["response is not a JSON object"]
    return [f"{f} is missing or empty" for f in fields
            if not isinstance(output.get(f), str) or not output[f].strip()]


def moment_format_problems(output: dict, inputs: dict, profile: Profile) -> list:
    facts, narration = inputs["moment"], inputs["narration"]
    head, text = output["headline"], output["text"]
    phrases = [facts["facts"][k] for k in QUOTED_FACTS if k in facts["facts"]]
    problems = voice_problems("text", text, profile.voice, phrases, VOICES[profile.voice]["max_sentences"])
    problems += voice_problems("headline", head, profile.voice, phrases)
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
    problems = _shape(output, ("headline", "text"))
    if problems:
        return _empty(problems)
    output = {"headline": output["headline"], "text": output["text"]}
    facts = inputs["moment"]
    rules = PERSONALIZER_BLOCKED + (FAN_BLOCKED if profile.mode == "fan" else [])
    subj = term_check.subject([facts])
    result = {
        "grounding": grounding.check(output, [facts, inputs["narration"]], extra_names=EXTRA_NAMES).to_dict(),
        "style": style_check.check(output, facts, extra_rules=rules).to_dict(),
        "polish": polish_check.check(output, sentence_fields=("text",)).to_dict(),
        "terms": term_check.check([(k, output[k], subj) for k in ("headline", "text")]).to_dict(),
    }
    return _finish(result, moment_format_problems(output, inputs, profile))


def first_team_named(text: str):
    found = [(text.find(name), team) for team, name in TEAM_NAMES.items() if name in text]
    return min(found)[1] if found else None


def recap_format_problems(text: str, inputs: dict, context: dict, profile: Profile) -> list:
    lo, hi = RECAP_SENTENCES
    n = len(sentences(text))
    problems = [] if lo <= n <= hi else [f"recap has {n} sentences, it needs {lo} to {hi}"]
    if word_count(text) > RECAP_WORDS[profile.mode]:
        problems.append(f"recap has {word_count(text)} words, {profile.mode} mode allows {RECAP_WORDS[profile.mode]}")
    phrases = [inputs["result_line"], inputs["match_headline"]] + [
        s[k] for s in inputs["story"] for k in QUOTED_FACTS if k in s]
    problems += voice_problems("recap", text, profile.voice, phrases)

    final = context["final_score"]
    winner, loser = sorted(final, key=final.get, reverse=True)
    if not re.search(rf"(?<![\d.]){final[winner]}\s*[-–]\s*{final[loser]}(?![\d.])", text):
        problems.append(f"recap must give the final score {final[winner]}-{final[loser]}, winner's goals first")
    for t in ([winner, loser] if final[winner] == final[loser] else [winner]):
        if TEAM_NAMES[t] not in text:
            problems.append(f"recap must name the winning team {TEAM_NAMES[t]}")
    fav = context["favourite_team"]
    if fav != NONE and first_team_named(text) != fav:
        problems.append(f"the first team named must be the favourite team {TEAM_NAMES[fav]}")
    if context["focus_player"] != NONE and context["focus_player"] not in text:
        problems.append(f"name the focus player {context['focus_player']}")
    if profile.mode == "fan":
        for x in xt_numbers(text, xt_values(context["moments"], inputs.get("focus_player"))):
            problems.append(f'fan mode: "{x}" is an xT number; say "danger" instead')
    return problems


def run_recap_checks(output, inputs: dict, context: dict, profile: Profile) -> dict:
    """Every check on one recap, no model calls."""
    problems = _shape(output, ("text",))
    if problems:
        return _empty(problems)
    text = output["text"]
    facts = {k: v for k, v in inputs.items() if k != "reader"}
    card = inputs.get("focus_player") or {}
    candidates = (context["moments"], [(k, v) for k, v in card.items()
                                      if isinstance(v, (int, float)) and not isinstance(v, bool)])
    rules = CONNECTOR_RULES + PERSONALIZER_BLOCKED + (FAN_BLOCKED if profile.mode == "fan" else [])
    result = {
        "grounding": grounding.check(text, inputs, extra_names=EXTRA_NAMES).to_dict(),
        # One field per sentence, so the shared MAX_NUMBERS applies per sentence, as the
        # Analyst applies it per phase note (at most 2 sentences); per recap it would
        # allow 5 numbers in 5 sentences, minutes and the score included.
        "style": style_check.check({f"recap[{k}]": s for k, s in enumerate(sentences(text))} or {"recap": text},
                                   facts, moment_rules=False, extra_rules=rules).to_dict(),
        "polish": polish_check.check({"recap": text}, sentence_fields=("recap",)).to_dict(),
        "terms": term_check.check([("recap", s, sentence_subject(s, candidates))
                                   for s in sentences(text)]).to_dict(),
    }
    return _finish(result, recap_format_problems(text, inputs, context, profile))


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


def personalize_recap(client, deployment: str, profile: Profile, analysis, summary, moments, selected,
                      players) -> dict:
    inputs = build_recap_input(profile, analysis, summary, moments, selected, players)
    context = recap_context(profile, analysis, summary, moments, selected)
    return generate(client, deployment, recap_instructions(profile), inputs, RECAP_SCHEMA,
                    lambda out: run_recap_checks(out, inputs, context, profile))
