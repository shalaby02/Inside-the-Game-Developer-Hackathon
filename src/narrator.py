"""Narrator agent: turns one key moment into a short TV-analyst explanation.

The agent is defined here in code: INSTRUCTIONS (its system prompt),
OUTPUT_SCHEMA (the JSON it must return) and MODEL_PARAMS (the request
settings). It is a direct Chat Completions call to the deployed Foundry model
(same endpoint and API key as src/hello_foundry.py), not a Foundry Agent
Service agent: the Agent Service needs Entra ID sign-in (az login) and the
azure-ai-projects SDK, and this agent needs no tools or conversation history.

Every narration is checked four ways: format (JSON shape, at most 2
sentences, the save headline pattern, the team named in every momentum-shift
sentence, build_up used word for word, counter_label on counter goals),
src/grounding.py (names, numbers, minutes), src/style_check.py (the shared
wording rules in src/style_rules.py) and src/polish_check.py (writing slips). On a failure the model gets
the offending items and tries again, up to MAX_RETRIES times; after that the
moment is marked failed and its last narration is kept for inspection only.

Use:  from narrator import narrate;  narrate(client, deployment, moment)
"""

import json
import re

import grounding
import polish_check
import style_check
from key_moments import TEAM_NAMES
from style_rules import PROMPT_RULES

MAX_RETRIES = 2
MAX_SENTENCES = 2
FIRST_HALF_MINUTES = 45  # minute 45 and later in period 1 is stoppage time (docs/data-format.md)
MIN_QUOTE_WORDS = 4      # this many words in a row from build_up means it is being used

# gpt-5-mini is a reasoning model. Per Microsoft's reasoning-models page it
# rejects temperature, top_p, presence/frequency penalties and max_tokens on
# Chat Completions. The output cap is max_completion_tokens, which also
# counts the model's hidden reasoning tokens, so it is set well above the
# ~150 visible tokens a narration needs.
MODEL_PARAMS = {
    "reasoning_effort": "low",
    "max_completion_tokens": 4000,
}

# Who is who in moment["players"], by category (see src/key_moments.py).
ROLES = {
    "goal": ["scorer", "key_passer"],
    "big_chance_missed": ["shooter", "key_passer"],
    "save": ["goalkeeper", "shooter", "key_passer"],
    "biggest_threat_swing": ["player", "receiver"],
}

# Facts the model doesn't see: raw pitch positions and the possession clock.
# build_up describes the move instead, with a duration only where it has a
# concrete start.
HIDDEN_FACTS = {"possession_seconds", "possession_start_x", "shot_x", "shot_y",
                "start_x", "start_y", "end_x", "end_y"}

ANGLES = """\
Why it mattered, by category:
- goal: what it did to the score. Use score_effect, e.g. "<scorer>'s goal <score_effect>". For a counter goal, also say counter_label word for word, e.g. "..., <counter_label>".
- save: what it denied: the shooter, how close and dangerous the shot was, and how the move was built.
- big_chance_missed: the chance that went begging: how close and dangerous it was and how the key pass set it up.
- biggest_threat_swing: how much more dangerous the ball became: the xT of the spot it moved from and to, and the xT added.
- momentum_shift: which team took control and for how long. Name the team in every sentence, give the first and last minute as ordinals (or "until <run_end>" when run_end is given instead of last_minute), and compare both teams' xT by name."""

FIELD_NOTES = """\
Field meanings (definitions only; never quote this list):
- team: the side the moment belongs to. For a save, team is the goalkeeper's side and opponent is the shooting side.
- team_score, opponent_score: the score just after the moment, from team's side.
- team_score_at_start, opponent_score_at_start (momentum_shift only): the score when the run started; goals may have come during the run, so never present it as the score during or after the run.
- score_effect (goals): what the goal did to the score, ready to use as written.
- build_up: one complete sentence on how the attacking side's move reached the key action (for a save: the shooting side's move). If you use it, copy it word for word as one of your sentences; never rephrase, shorten or rebuild it.
- counter_label (counter goals): which counter-attack it was, ready to use as written.
- action_type: "pass" or "carry", the type of the key action. For a shot it is the key pass; for any other moment it is the action itself.
- key_passer: the player who made the last pass before the shot.
- shot_zone_value: xT of the spot the shot came from.
- distance_to_goal_m: distance from the shot to the goal, in metres.
- key_pass_xt_added: xT added by the key pass.
- xt_added: xT added by the action; zone_start_value, zone_end_value: xT of the spot the ball moved from and to.
- momentum_shift: start_minute to last_minute, a run of blocks where team added more xT than opponent; end_period is the period it ended in.
- run_end (momentum_shift ending in first-half stoppage time, given instead of last_minute): how to say when the run ended, e.g. "the end of the first half".
- team_threat, opponent_threat: total xT each side added during the run.
- opponent_blocks_ahead_before: how many blocks in a row opponent was on top just before the run; team_threat_before, opponent_threat_before: each side's xT over those blocks.
- top_player_threat: xT added during the run by the first of top_threat_creators."""

INSTRUCTIONS = f"""\
You are the Narrator for a football match recap: a TV analyst explaining one key moment to viewers.

xT (expected threat) is how likely a team is to score soon from where it has the ball. Every spot on the pitch has an xT value: the higher it is, the more dangerous the spot. "xT added" is how much a pass or carry raised it.

You get one moment as JSON. Write:
- headline: one short line in sentence case (capitalise only the first word and names). For a save, use exactly "<goalkeeper> saves <shooter>'s <distance_to_goal_m>-metre shot", with the distance written as given.
- explanation: at most 2 sentences, in a confident TV-analyst voice, that explain why the moment mattered, from the angle for its category below. Make one clear point backed by about 4 numbers; do not list numbers.
- numbers_used: every number in your headline and explanation, exactly as written there.

{ANGLES}

Strict rules:
- Use only the names, numbers and minutes in the moment JSON. Write player and team names exactly as given.
- Quote numbers exactly as given, digit for digit. No rounding, no conversions (no percentages, no metres to yards), no arithmetic, no new totals, differences or ratios. Write numbers as digits.
- Say a minute as the ordinal of the minute field, such as "the 61st minute"; never "90+3". A score may be written like "1-0", using team_score and opponent_score.
- Give distances in metres: "from 8.0 metres".
- Do not mention the crowd, weather, tactics, formations, managers, player history, other matches or anything else from outside the JSON. If something is not in the JSON, leave it out.
{PROMPT_RULES}

{FIELD_NOTES}

Return only the JSON object."""

OUTPUT_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "narration",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "headline": {"type": "string"},
                "explanation": {"type": "string"},
                "numbers_used": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["headline", "explanation", "numbers_used"],
            "additionalProperties": False,
        },
    },
}


def moment_input(moment: dict) -> dict:
    """The facts object the model sees, and that the checks run against.

    Everything comes from the moment itself: team ids become their display
    names, moment["players"] gets role labels, and HIDDEN_FACTS are dropped.
    """
    team = moment["team"]
    opponent = next(t for t in TEAM_NAMES if t != team)
    players = moment["players"]
    roles = ROLES.get(moment["category"])
    facts = {k: v for k, v in moment["facts"].items() if k not in HIDDEN_FACTS}
    if roles:
        people = dict(zip(roles, players))
    else:  # momentum_shift: the run's top threat creators, best first
        people = {"top_threat_creators": players}
        # Its score is the score when the run starts, not after it (goals can
        # come during the run), so the key names say so.
        for key in ("team_score", "opponent_score"):
            if key in facts:
                facts[f"{key}_at_start"] = facts.pop(key)
        # A run that ends in first-half stoppage time (period 1, minute 45 or
        # later) ends at "the end of the first half", not at "the 46th minute".
        if facts.get("end_period") == 1 and facts.get("last_minute", 0) >= FIRST_HALF_MINUTES:
            del facts["last_minute"]
            facts["run_end"] = "the end of the first half"
    return {
        "category": moment["category"],
        "tags": moment["tags"],
        "period": moment["period"],
        "minute": moment["minute"],
        "second": moment["second"],
        "team": TEAM_NAMES[team],
        "opponent": TEAM_NAMES[opponent],
        **people,
        "facts": facts,
    }


def sentences(text: str) -> list:
    # A sentence ends at . ! or ? followed by a space or the end ("0.3" is not an end).
    return [s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s]


def save_headline(facts: dict) -> str:
    return f"{facts['goalkeeper']} saves {facts['shooter']}'s {facts['facts']['distance_to_goal_m']}-metre shot"


def format_problems(narration, facts: dict = None) -> list:
    if not isinstance(narration, dict):
        return ["response is not a JSON object"]
    problems = []
    for key in ("headline", "explanation"):
        if not isinstance(narration.get(key), str) or not narration[key].strip():
            problems.append(f"{key} is missing or empty")
    if not isinstance(narration.get("numbers_used"), list):
        problems.append("numbers_used is not a list")
    if problems:
        return problems

    parts = sentences(narration["explanation"])
    if len(parts) > MAX_SENTENCES:
        problems.append(f"explanation has {len(parts)} sentences, at most {MAX_SENTENCES} allowed")
    if facts and facts["category"] == "save" and "shooter" in facts:
        expected = save_headline(facts)
        if narration["headline"].strip().rstrip(".").replace("’", "'") != expected:
            problems.append(f'save headline must be exactly "{expected}"')
    inner = (facts or {}).get("facts", {})
    build_up = inner.get("build_up")
    if build_up and _borrows(narration["explanation"], build_up) and build_up not in narration["explanation"]:
        problems.append(f'use the build_up sentence word for word: "{build_up}"')
    label = inner.get("counter_label")
    if label and label not in narration["headline"] + " " + narration["explanation"]:
        problems.append(f'say the counter_label word for word: "{label}"')
    if facts and facts["category"] == "momentum_shift":
        unnamed = [s for s in parts if facts["team"] not in s and facts["opponent"] not in s]
        if unnamed:
            problems.append(f'name the team in every sentence: "{unnamed[0]}"')
    return problems


def _borrows(text: str, phrase: str) -> bool:
    """text uses MIN_QUOTE_WORDS or more words in a row from phrase."""
    words = re.findall(r"[\w'’-]+", phrase.lower())
    text = " ".join(re.findall(r"[\w'’-]+", text.lower()))
    return any(" ".join(words[i:i + MIN_QUOTE_WORDS]) in text for i in range(len(words) - MIN_QUOTE_WORDS + 1))


def call_model(client, deployment: str, messages: list):
    """One model call. Returns (narration or None, problem or None, raw reply text or None)."""
    response = client.chat.completions.create(
        model=deployment,
        messages=messages,
        response_format=OUTPUT_SCHEMA,
        **MODEL_PARAMS,
    )
    choice = response.choices[0]
    content = choice.message.content
    if not content:
        return None, f"empty reply (finish_reason={choice.finish_reason})", None
    try:
        return json.loads(content), None, content
    except json.JSONDecodeError:
        return None, "reply is not valid JSON", content


def run_checks(narration, facts: dict) -> dict:
    """Every check on one narration, no model calls: format (including the
    build_up and counter_label rules), grounding, style and polish.
    Returns {"passed", "format_problems", "grounding", "style", "polish"}."""
    problems = format_problems(narration, facts)
    usable = isinstance(narration, dict)
    result = {
        "format_problems": problems,
        "grounding": grounding.check(narration, facts).to_dict() if usable else None,
        "style": style_check.check(narration, facts).to_dict() if usable else None,
        "polish": polish_check.check(narration).to_dict() if usable else None,
    }
    result["passed"] = not problems and all(result[k]["passed"] for k in ("grounding", "style", "polish"))
    return result


def flagged(checks: dict) -> list:
    """Every flagged item of run_checks() as one line of text."""
    lines = [f"format: {p}" for p in checks["format_problems"]]
    for kind in ("grounding", "style", "polish"):
        if checks[kind]:
            lines += [f'{kind}: {o["type"]} "{o["value"]}": {o["reason"]}' for o in checks[kind]["offending"]]
    return lines


def narrate(client, deployment: str, moment: dict) -> dict:
    """Narrate one moment, retrying on a format, grounding, style or polish failure.

    Returns {"id", "status": "ok" | "failed", "narration", "grounding",
    "style", "polish", "retries", "attempts": [...]}. A failed moment's narration must
    not be used.
    """
    facts = moment_input(moment)
    messages = [
        {"role": "system", "content": INSTRUCTIONS},
        {"role": "user", "content": json.dumps(facts, ensure_ascii=False)},
    ]
    attempts = []
    for attempt in range(1 + MAX_RETRIES):
        narration, problem, raw = call_model(client, deployment, messages)
        checks = run_checks(narration, facts)
        if problem:
            checks["format_problems"], checks["passed"] = [problem], False
        attempts.append({"attempt": attempt + 1, "narration": narration,
                         **{k: checks[k] for k in ("format_problems", "grounding", "style", "polish")}})
        if checks["passed"]:
            break

        # Tell the model exactly what failed and ask again.
        feedback = flagged(checks)
        if raw is not None:
            messages.append({"role": "assistant", "content": raw})
        messages.append({"role": "user", "content": (
            "Your answer broke the rules:\n- " + "\n- ".join(feedback) +
            "\nRewrite it following every rule. Use only names, numbers and minutes exactly as they appear "
            "in the moment JSON, and leave out anything you cannot support from it.")})

    last = attempts[-1]
    return {"id": moment["id"], "status": "ok" if checks["passed"] else "failed", "narration": last["narration"],
            "grounding": last["grounding"], "style": last["style"], "polish": last["polish"],
            "retries": len(attempts) - 1, "attempts": attempts}
