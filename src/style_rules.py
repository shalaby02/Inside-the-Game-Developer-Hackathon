"""Shared wording rules for every agent that writes about the match.

One place for both halves of each rule:
- PROMPT_RULES: the rules as text, for an agent's instructions.
- BLOCKED, fact_rules(), DURATION, MAX_NUMBERS: the same rules as patterns,
  enforced by src/style_check.py (no model calls).

Edit here and both the prompt and the check change together. Patterns are
regular expressions matched case-insensitively on whole words.
"""

ALLOWED_OUTCOME_VERBS = ("scored", "saved", "missed", "passed", "carried", "denied", "stopped")

MAX_NUMBERS = 5  # per text field; agents are asked for about four

# (pattern, reason shown to the model on a retry)
BLOCKED = [
    # How a save looked: the facts only say it was saved.
    (r"pushe[sd] away|turn(?:s|ed)? away|tip(?:s|ped)?|parr(?:y|ies|ied)|smother(?:s|ed)?|"
     r"palm(?:s|ed)?|claw(?:s|ed)?|div(?:e|es|ed|ing)|fingertips?|full stretch|"
     r"beat(?:s)? away|reflex(?:es)?|acrobatic", "describes how the save was made"),
    # How a shot looked: the facts only say scored or missed.
    (r"volley(?:s|ed)?|header|headed|low (?:shot|attempt|drive|effort)|curl(?:s|ed|ing)?|"
     r"chip(?:s|ped)?|drill(?:s|ed)|lash(?:es|ed)|blast(?:s|ed)|smash(?:es|ed)|"
     r"rifle[sd]|thump(?:s|ed)|slot(?:s|ted)|tap(?:s|ped)? in|tap-in|powered|"
     r"wide|over the bar|(?:top|bottom|far|near) (?:corner|post)|first-time|"
     r"left foot|right foot|left-footed|right-footed", "describes how the shot was taken"),
    # Outcome verbs outside ALLOWED_OUTCOME_VERBS.
    (r"fir(?:e|es|ed|ing)|nets|netted|netting|finish(?:es|ed|ing)?|strikes|struck|"
     r"squander(?:s|ed|ing)|wast(?:es|ed|ing)|convert(?:s|ed|ing)|buried|teed up|tees up",
     "outcome verb outside " + ", ".join(ALLOWED_OUTCOME_VERBS)),
    # The score is only known at the moment itself.
    (r"keep(?:s|ing)?|kept|remain(?:s|ed)?|stay(?:s|ed)?|held|"
     r"winner|winning goal|decider|decisive|clincher", "claims what the score did later"),
    (r"overturn\w*|turn(?:s|ed)? the (?:game|match|tide)|comeback",
     "claims what happened later in the match"),
    # Position wording worked out from coordinates.
    (r"central(?:ly)?|tight angle|angled", "position wording not in the facts"),
    # Comparisons with the rest of the match; counter_label carries the only one allowed.
    (r"best|biggest|clearest|greatest|most dangerous|so far|at that point",
     "compares with the rest of the match"),
    # Always name the team.
    (r"they|them|their|theirs|themselves|the opponents?|the hosts|the visitors|"
     r"the home (?:side|team)|the away (?:side|team)|the other (?:side|team)",
     "name the team instead (for example London Red)"),
    # Field names leaking into the text.
    (r"[a-z]+(?:_[a-z]+)+", "field name in the text"),
]

# A duration: a number (or number word) with a time unit, e.g. "10 seconds",
# "10-second", "ten seconds", "5-minute". It is allowed only when the exact
# same words appear in a fact phrase such as build_up ("scored 10 seconds
# later"); anything else, such as "10-second move", is blocked.
DURATION_WORDS = (r"one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|"
                  r"fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty")
DURATION = (rf"(?:\d+(?:\.\d+)?|{DURATION_WORDS})[\s-]+(?:second|sec|minute|min)s?",
            'duration outside the build_up phrase (no "10-second move", "10 seconds" or "ten seconds")')

SHOT_CATEGORIES = {"goal", "save", "big_chance_missed"}


def fact_rules(facts: dict) -> list:
    """Blocked phrases that depend on this moment's facts (top level or under "facts")."""
    inner = facts.get("facts") or {}
    action = inner.get("action_type", facts.get("action_type"))
    rules = []
    if action != "carry":
        rules.append((r"carr(?:y|ies|ied|ying)", "the action was not a carry (see action_type)"))
    if action == "carry":
        rules.append((r"pass(?:es|ed|ing)?", "the action was a carry, not a pass (see action_type)"))
    if facts.get("category") not in SHOT_CATEGORIES:
        rules.append((r"chances?|opportunit(?:y|ies)", "only a shot is a chance"))
    return rules


PROMPT_RULES = f"""\
- Outcome verbs: only {", ".join(ALLOWED_OUTCOME_VERBS)}. Use passed or carried only as action_type says, and neither if there is no action_type.
- Never describe how something looked: no volleys, headers, low, curled or chipped shots, shots going wide, diving, parrying or pushing-away saves, and no positions such as "central".
- Durations: only inside the build_up phrase, word for word (for example "won the ball back in midfield and scored 10 seconds later"). Never write any other duration: no "10-second move", "10-second possession", "10 seconds", "ten seconds" or "5-minute blocks". For a spell of play, give its first and last minute as ordinals: "from the 70th minute to the 93rd minute".
- Always name the team ("London Red"); never "they", "them", "their", "the opponent", "the hosts" or "the visitors".
- Scores are known only at the moment itself. Never say a score stayed, held, was kept or finished that way, and never call a goal a winner or decisive.
- Only a shot is a chance. Do not call a pass, carry or momentum shift a chance or an opportunity.
- Do not compare the moment with the rest of the match ("the best", "the clearest so far"); counter_label is the only comparison you may use.
- Do not mention ids or field names (such as shot_zone_value or xt_added); say "xT" for threat values.
- Use about 4 numbers, never more than {MAX_NUMBERS} in one field."""


# ------------------------------------------------------------ analysis terms
#
# Football performance-analysis wording for agents that write about the whole
# match (the Analyst). These are separate from BLOCKED so the Narrator's rules,
# and its cache, stay as they are. src/term_check.py enforces both lists; the
# definitions behind each term are in docs/data-format.md ("Analysis terms").

# Terms the facts can't support at all: never allowed.
BANNED_TERMS = [
    (r"xg|expected goals?", 'not computed; say "shot-location value" (shot_zone_value)'),
    (r"press(?:es|ed|ing)?|counter-?press(?:es|ed|ing)?|ppda|high press",
     "pressing is not derivable from the events"),
    (r"formations?|\d-\d-\d(?:-\d)?|back (?:three|four|five)|low block|mid-block|high line",
     "formations and team shape are not in the data"),
    (r"compact(?:ness)?", "compactness is not derivable from the events"),
    (r"width|stretch(?:es|ed|ing)? the pitch", "width is not derivable from the events"),
    (r"possession (?:percentage|share|stats?)|share of possession|\d+(?:\.\d+)?\s*%|per ?cent|"
     r"(?:more|most|less|dominated|controlled) possession|(?:more|most) of the ball",
     "possession percentage is not computed"),
    # Ambiguous: it can mean winning the ball or losing it.
    (r"turnovers?", 'say "possessions lost in the final third" (possessions_lost_in_final_third)'),
]

# Causal and temporal connectors, blocked in the headline and phase notes:
# the checks can confirm facts, not that one thing caused or came before another.
# A connector inside a fact phrase quoted word for word (such as result_line's
# "after trailing") is not blocked. Edit this list to change the rule.
# (word shown in the prompt, pattern, reason)
CONNECTORS = [
    ("preceded", r"preced(?:e|es|ed|ing)", "claims an order of events"),
    ("led to", r"(?:led|lead|leads|leading) to", "claims a cause"),
    ("sparked", r"spark(?:s|ed|ing)?", "claims a cause"),
    ("because", r"because(?: of)?", "claims a cause"),
    ("before", r"before", "claims an order of events"),
    ("after", r"after(?:wards)?", "claims an order of events"),
    ("ahead of", r"ahead of", "claims an order of events"),
    ("caused", r"caus(?:e|es|ed|ing)", "claims a cause"),
]

# Terms that need a fact behind them: (label, pattern, backing, what it needs).
# src/term_check.py decides what counts as that backing for the text's subject
# (the moment it describes, or the facts a phase note cites).
TERMS = [
    ("final-third entry", r"final[- ]third entr(?:y|ies)", "final_third_entries",
     "a final_third_entries fact"),
    ("final third", r"final[- ]third|attacking third", "final_third",
     "a final-third fact (final_third_entries, possessions_lost_in_final_third, or a build_up in the attacking third)"),
    ("middle third", r"middle third", "middle_third", "a build_up through midfield"),
    ("defensive third", r"defensive third", "defensive_third", "a build_up from the defensive third"),
    ("penalty-area entry", r"(?:penalty[- ]area|box) entr(?:y|ies)", "penalty_area_entries",
     "a penalty_area_entries fact"),
    ("penalty area", r"penalty area|penalty box|(?:the|18-yard) box", "penalty_area",
     "a penalty_area_entries fact"),
    ("progressive action", r"progressive (?:pass(?:es)?|carr(?:y|ies)|actions?|play)", "progressive_actions",
     "a progressive_actions fact"),
    ("possessions lost in the final third",
     r"(?:possessions?|the ball) lost in the final third|lost (?:possession|the ball) in the final third",
     "possessions_lost", "a possessions_lost_in_final_third fact"),
    ("transition", r"transitions?|counter[- ]attack(?:s|ing)?|counters?|on the break|breakaway", "counter",
     "a moment with the counter tag"),
    ("build-up phase", r"build-up(?: phase| play)?|build up phase", "build_up", "a moment with a build_up fact"),
    ("threat created", r"threat created|created (?:\w+ )?threat", "threat",
     "a threat fact (threat_created, xt_added, key_pass_xt_added or team_threat)"),
    ("shot-location value", r"shot-location values?", "shot_location", "a moment with a shot_zone_value"),
]

ANALYST_PROMPT_RULES = """\
- Analysis terms. Use each one only when the fact behind it is cited in the same phase note (for the turning point: is in that moment; for the headline: is anywhere in the input):
""" + "\n".join(f'  - "{label}": needs {need}' for label, _, _, need in TERMS) + """
- The backing is checked sentence by sentence: the sentence that uses a term must itself name what the term is about, by a minute ("the 61st minute"), a player's full name, an xT number of that moment, or the number of the cited stat.
- "transition" and "counter-attack" mean only the moments tagged counter. "build-up phase" means only a moment's build_up.
- Never use: xG or expected goals (say "shot-location value"), pressing or PPDA, formations or team shape, compactness, width, possession percentages, or "turnover" (say "possessions lost in the final third").
- In match_headline and phase_notes, no causal or temporal connectors: """ + ", ".join(
    f'"{word}"' for word, _, _ in CONNECTORS) + """ and the like. State facts side by side instead. Quoting a fact phrase such as result_line word for word is fine."""
