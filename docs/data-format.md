# Match data format

This is the shape of `data/match.json`, the file that `src/generate_match.py` will write (Day 3) and that `src/xt_model.py` will read (Day 4).

## The pitch

- Both axes run from **0 to 100**. This is the same as Opta's layout, so mplsoccer can draw it with `Pitch(pitch_type="opta")`.
- **Every event is stored from the acting team's point of view, and that team always attacks toward x = 100.** London Red and London Blue both shoot at x = 100 in their own events.
- `x = 0` is the team's own goal line and `x = 100` is the goal line they attack.
- `y = 0` is the touchline on the attacker's **right**, and `y = 100` is the one on their **left**. The goal is centred on `y = 50`.
- The goal mouth is roughly `y = 45` to `y = 55` at `x = 100`. The penalty box is roughly `x ≥ 83`, `21 ≤ y ≤ 79`.

```
 y=100 ┌───────────────────────────────────────────┐  (attacker's left)
       │                                           │
       │                                     ┌─────┤
       │                                     │  box│
 y=50  │ own goal                            │     ║ goal they attack
       │ x=0                                 │     │ x=100
       │                                     └─────┤
       │                                           │
 y=0   └───────────────────────────────────────────┘  (attacker's right)
        ─────────────── direction of attack ──────▶
```

To draw both teams on one pitch (for example, Red attacking left to right and Blue attacking right to left), flip the other team's events: `x' = 100 − x`, `y' = 100 − y`.

## Event fields

| Field | Type | Meaning |
|---|---|---|
| `event_id` | int | Running number, starts at 1, goes up by 1 in match order. |
| `possession_id` | int | Groups the events of one attacking move. A new id starts each time the ball changes team, and at every restart (kick-off, set piece). |
| `period` | int | `1` = first half, `2` = second half. |
| `minute` | int | Match clock minute. The first half runs from `0`, and the second half starts at `45`. Stoppage time keeps counting, so first-half 45+2 is `period: 1, minute: 47`, which is different from `period: 2, minute: 47`. |
| `second` | int | `0`–`59`. |
| `team` | string | `london_red` or `london_blue`. The team of the player who made the event. |
| `player` | string | The player's full name, exactly as written in [teams.md](teams.md). |
| `shirt_number` | int | The player's shirt number from [teams.md](teams.md). Together with `team`, this is the reliable way to identify a player. Use the name for display only. |
| `type` | string | One of `pass`, `carry`, `shot`, `tackle`, `interception`, `foul`, `clearance`. |
| `start_x`, `start_y` | number | Where the event started, 0–100, from the acting team's point of view. |
| `end_x`, `end_y` | number | Where the ball ended up. For `tackle`, `interception` and `foul` this is the same as the start. |
| `outcome` | string | Depends on `type`. See the next table. |
| `is_assist` | bool | `true` only on the pass that set up a goal. `false` everywhere else. |

Numbers may have one decimal place (for example `57.5`).

## Allowed outcomes for each type

| Type | Allowed `outcome` values | Notes |
|---|---|---|
| `pass` | `complete`, `incomplete` | `incomplete` = intercepted, or out of play. Only a `complete` pass can have `is_assist: true`. |
| `carry` | `complete`, `lost` | Player runs with the ball. `lost` = dispossessed during the carry. |
| `shot` | `goal`, `saved`, `off_target`, `blocked` | For `goal` and `off_target`, the end point is where the ball crossed the goal line (`end_x = 100`). For `saved` and `blocked`, it is where the ball was stopped. Saves have no event of their own: a `saved` shot is credited to the other team's goalkeeper. |
| `tackle` | `won`, `lost` | `won` = the tackler's team now has the ball. A won tackle starts a new possession for the tackler's team. |
| `interception` | `won` | Always wins the ball. Starts a new possession for the intercepting team. |
| `foul` | `free_kick`, `yellow_card`, `red_card` | Recorded for the team that **committed** the foul, at the spot of the foul, from that team's point of view. |
| `clearance` | `won`, `lost` | `won` = the clearing team, or nobody, has the ball next. `lost` = the opponent picks it up. |

## Rules the generator must follow

1. Events are in time order (`period`, then `minute`, then `second`), and `event_id` follows that order.
2. A goal always comes straight after its assist pass, if there was one, and both are in the same `possession_id`. Some goals have no assist (a solo run, a rebound).
3. A pass's end point is the next event's start point when the same team keeps the ball.
4. The number of `shot` events with `outcome: goal` for each team must match the final score in [match-story.md](match-story.md).
5. Every `player` and `shirt_number` pair must match the right `team` in [teams.md](teams.md).
6. Set pieces (corners, free kicks, kick-offs, goal kicks) have no event type of their own. They just start a new `possession_id`.

## File shape

```json
{
  "match": {
    "home_team": "london_red",
    "away_team": "london_blue",
    "final_score": { "london_red": 2, "london_blue": 1 },
    "seed": 42
  },
  "events": [ { "event_id": 1, "...": "..." } ]
}
```

## Example: one attacking move in 5 events

London Blue's goal (second half, 61'), a turnover in midfield followed by a quick break down the left.

| # | Time | Player (No.) | Type | From → To | Outcome |
|---|---|---|---|---|---|
| 1 | 61:04 | Sam Okoro (4) | tackle | (44, 46) | won |
| 2 | 61:07 | Sam Okoro (4) | pass | (44, 46) → (58, 70) | complete |
| 3 | 61:10 | Dario Quill (11) | carry | (58, 70) → (74, 76) | complete |
| 4 | 61:13 | Dario Quill (11) | pass | (74, 76) → (88, 52) | complete, `is_assist` |
| 5 | 61:14 | Niko Vane (9) | shot | (88, 52) → (100, 50) | goal |

In words: Okoro wins the ball just short of halfway, Quill runs with it up the left wing, crosses into the box, and Vane scores in the middle of the goal.

The same move as JSON (the event and possession ids are examples):

```json
[
  { "event_id": 312, "possession_id": 141, "period": 2, "minute": 61, "second": 4,  "team": "london_blue", "player": "Sam Okoro",   "shirt_number": 4,  "type": "tackle", "start_x": 44, "start_y": 46, "end_x": 44,  "end_y": 46, "outcome": "won",      "is_assist": false },
  { "event_id": 313, "possession_id": 141, "period": 2, "minute": 61, "second": 7,  "team": "london_blue", "player": "Sam Okoro",   "shirt_number": 4,  "type": "pass",   "start_x": 44, "start_y": 46, "end_x": 58,  "end_y": 70, "outcome": "complete", "is_assist": false },
  { "event_id": 314, "possession_id": 141, "period": 2, "minute": 61, "second": 10, "team": "london_blue", "player": "Dario Quill", "shirt_number": 11, "type": "carry",  "start_x": 58, "start_y": 70, "end_x": 74,  "end_y": 76, "outcome": "complete", "is_assist": false },
  { "event_id": 315, "possession_id": 141, "period": 2, "minute": 61, "second": 13, "team": "london_blue", "player": "Dario Quill", "shirt_number": 11, "type": "pass",   "start_x": 74, "start_y": 76, "end_x": 88,  "end_y": 52, "outcome": "complete", "is_assist": true  },
  { "event_id": 316, "possession_id": 141, "period": 2, "minute": 61, "second": 14, "team": "london_blue", "player": "Niko Vane",   "shirt_number": 9,  "type": "shot",   "start_x": 88, "start_y": 52, "end_x": 100, "end_y": 50, "outcome": "goal",     "is_assist": false }
]
```

## Expected Threat (xT)

`src/xt_model.py` reads `data/match.json` and writes `data/match_xt.csv`: the same columns, plus these:

| Column | Type | Meaning |
|---|---|---|
| `zone_start`, `zone_end` | string | Zone of the start and end point, e.g. `c10r4` (see below). |
| `xt_added` | number | How much the event changed its team's chance of scoring soon (see the table below). |
| `shot_zone_value` | number or blank | Shots only: the value of the zone the shot was taken from, a measure of how good the chance was. Blank for other types. |
| `possession_seconds` | int | The same on every event of a possession: seconds from its first event to its shot, or to its last event if there was no shot. Use it for tempo, e.g. the fastest moves from a team's own half (`start_x` < 50 on the first event) to a shot. |

**Zones.** The pitch is split into 12 columns along `x` (each 8.33 wide) and 8 rows along `y` (each 12.5 wide), in the acting team's frame. A zone is written `c{column}r{row}`: `c0` is at the team's own goal line, `c11` is next to the goal they attack, and `r0` is the attacker's right touchline. Points on `x = 100` or `y = 100` fall in the last zone. For example, `(88, 52)` is in `c10r4`.

**Zone values.** Each zone's value is roughly "how likely is a goal soon if we have the ball here". The values are hand-built, with no outside data: the value halves for every 8 units the zone's centre is from the middle of the goal (100, 50). Sideways distance counts 70%, so the wide zones by the byline still have some value. The best zone is scaled to 0.30. The values go from about 0.005 in the centre circle to 0.08 at the edge of the box and 0.30 in front of goal.

**xT added per event.**

| Event | `xt_added` |
|---|---|
| `pass` / `carry`, `complete` | value(end zone) − value(start zone) |
| `pass` `incomplete`, `carry` `lost` | − value(start zone): the team gave away what it had |
| `shot` | 0: its danger is in `shot_zone_value` instead, so goals don't swamp the totals |
| `tackle`, `interception`, `foul`, `clearance` | 0 (kept for context) |

Example: Quill's assist at 61' goes from `c8r6` (0.021) to `c10r4` (0.161), so `xt_added` = +0.139. Vane's goal straight after has `xt_added` = 0 and `shot_zone_value` = 0.161.

## Key moments

`src/key_moments.py` reads `data/match_xt.csv` and writes `data/key_moments.json`: the final score and about 10–12 moments in match order. Moments are facts only, with no prose, so the Narrator can explain them without inventing anything.

```json
{
  "final_score": { "london_red": 2, "london_blue": 1 },
  "moments": [
    { "id": "m10", "category": "goal", "tags": ["counter"], "period": 2, "minute": 74, "second": 22,
      "team": "london_red", "players": ["Rafael Tovey", "Theo Brannick"],
      "facts": { "action_type": "pass", "build_up": "London Red won the ball back in the defensive third and scored 12 seconds later, ...", "score_effect": "levelled the match at 1-1", "possession_seconds": 12, "possession_start_x": 17.0, "counter_rank": 2, "team_score": 1, "opponent_score": 1, "...": "..." } }
  ]
}
```

| Field | Meaning |
|---|---|
| `id` | `m01`, `m02`, … in match order. |
| `category` | One per moment (see the next table). |
| `tags` | A list, often empty. `counter` = the moment's possession starts in the team's own half (`start_x` < 50 on its first event), ends in a shot and takes 15 seconds or less. |
| `period`, `minute`, `second` | When it happened. A momentum shift is timed at the start of its first block. |
| `team` | The team the moment belongs to. For a `save`, that's the goalkeeper's team. |
| `players` | Names, most important first: scorer then assist, goalkeeper then shooter, passer then receiver, or a momentum shift's top 3 threat creators. |
| `facts` | Plain numbers, e.g. `xt_added`, `shot_zone_value`, `possession_seconds`, plus the code-derived words below (`action_type`, `score_effect`, `build_up`, `counter_label`). `team_score` and `opponent_score` are the score just after the moment (for a momentum shift: when its first block starts). |
| `facts.score_effect` | Goals only. What the goal did to the score, from the scoring team's side: `put London Blue 1-0 up` (first goal), `put London Red 2-1 ahead` (from level), `levelled the match at 1-1`, `extended <team>'s lead to 2-0`, `pulled <team> back to 1-2`. |
| `facts.build_up` | Shot moments and threat swings, when the events support it. One complete sentence that names the attacking team (for a save: the shooting team), e.g. `London Blue won the ball back in midfield and scored 10 seconds later, after 2 passes and a carry from midfield into the attacking third.` It says how the possession reached the key action (the shot, or the swing's pass or carry: `played this pass`, `made this carry`, with the passes before it called `earlier`), built only from what the events record: **start** `<team> won the ball back in <third>` when the possession's first event is the team's own won `tackle` or `interception`, or `<team>'s move started after a <other team> foul` when the event just before the possession is the other team's foul; **middle** the number of completed passes, a forward carry of at least 10 pitch units (described by thirds: the defensive third, midfield, the attacking third), and `a one-two` (A passes, B passes, A is next on the ball). A duration (`and scored 10 seconds later`) appears only after a won ball, the only start with a recorded time. Not derivable, so never included: throw-ins, corners, goal kicks and other restarts (they have no events), and pass length or style. Momentum shifts have none. |
| `facts.counter_label` | Goals with the `counter` tag only: `the fastest of the match's two counter-attacks`, `the second-fastest of the match's two counter-attacks`. |
| `facts.action_type` | `pass` or `carry`: the type of the moment's key action. For a `biggest_threat_swing` that is the swing itself; for a shot moment it is the key pass (the last pass before the shot, so always `pass`, and present only when `key_pass_xt_added` is). Momentum shifts have no key action and no `action_type`. |

| Category | Rule |
|---|---|
| `goal` | Every goal, always included. A goal with the `counter` tag also has `counter_rank` (1 = the fastest `counter` move in the match, by `possession_seconds`) and `counters_in_match` (how many moves meet the `counter` rule). |
| `save` | A saved shot from a big chance (`shot_zone_value` ≥ 0.15). |
| `big_chance_missed` | An off-target or blocked shot from a big chance. |
| `momentum_shift` | One team creates more threat than the other in at least 3 five-minute blocks in a row, after the other team was on top in the block before, and beats the other team's threat over those blocks by at least 0.25. Threat = `xt_added` of completed passes and carries only. |
| `biggest_threat_swing` | The completed passes and carries with the most `xt_added`. |

**Selection.** Goals first. Then the other categories in the order of the table, best first, with at most 3 moments per category and at most one moment per 60 seconds.

## Analysis terms

The Analyst may use football performance-analysis words only where code can compute the fact behind them. Every event is in the acting team's frame, attacking toward x = 100 on the 0–100 pitch. The code is in `src/match_summary.py`, the wording rules in `src/style_rules.py` (`TERMS`, `BANNED_TERMS`) and the check in `src/term_check.py`.

| Term | Definition | Derivable? |
|---|---|---|
| defensive / middle / final third | `x < 33.3` / `33.3 ≤ x < 66.7` / `x ≥ 66.7` (exactly 100/3 and 200/3, the same edges as `build_up`'s "the defensive third", "midfield", "the attacking third"). | Yes |
| final-third entry | A **completed** pass or carry that starts outside the final third and ends in it. | Yes |
| penalty-area entry | A **completed** pass or carry that starts outside the penalty area (`x ≥ 83`, `21 ≤ y ≤ 79`) and ends in it. | Yes |
| progressive action | A **completed** pass or carry that moves the ball closer to the middle of the goal (100, 50), measured in metres on a 105 × 68 m pitch, by at least **30 m** if it starts and ends in the team's own half (`x < 50`), **15 m** from its own half into the other half, or **10 m** within the other half. **These thresholds are this model's own definition**, in the style of common industry ones but not taken from any data provider, so the counts are not comparable with published "progressive pass" stats. | Yes, by this definition |
| possessions lost in the final third | An `incomplete` pass or `lost` carry that **starts** in the final third: the team gave the ball away there. (Not called "turnover", which can also mean winning the ball; that word is blocked.) | Yes |
| transition (counter-attack) | A moment with the `counter` tag: its possession starts in the team's own half, ends in a shot and takes 15 seconds or less. | Yes, for tagged moments only |
| build-up phase | Only in the narrow sense of one possession's `build_up` fact: how that move reached its key action. | Partly: there is no team-level "phase of play", and restarts (goal kicks, throw-ins) have no events, so the build-up from the back can't be measured across the match |
| threat created | `xt_added` of completed passes and carries (the same threat as the momentum shifts). | Yes |
| shot-location value | `shot_zone_value`: the xT of the zone a shot was taken from. Used **instead of xG**. | Yes |

Never used: "turnover" (ambiguous, see above), xG (there is no shot model, only zone values: say "shot-location value"), pressing (no pressure events), PPDA (left out on purpose, although tackles, interceptions and fouls could approximate it), formations, team shape, compactness and width (no player positions off the ball), and possession percentage (not computed).

**Term backing** is checked **sentence by sentence**. A term is accepted only if its fact belongs to what that sentence describes. A sentence describes a moment when it names it: by one of its minutes as an ordinal ("the 61st minute"), a player's full name, one of its decimal (xT) numbers, or a fact phrase it quotes (`build_up`, `counter_label`, `score_effect`). It describes a summary stat when it gives that stat's number (scores like "2-1" and minutes like "61st" don't count as stat numbers). For a phase note, the candidates are the facts it cites; for the headline, everything in the input; the turning point's reason is always about its own moment. So "transition" in a sentence about the 70th minute fails even if the same note also cites m07.

| Term | Needs |
|---|---|
| final-third entries | a cited `final_third_entries` |
| final third, attacking third | a cited `final_third_entries` or `possessions_lost_in_final_third`, or a moment whose `build_up` mentions the attacking third |
| middle third / defensive third | a moment whose `build_up` mentions midfield / the defensive third |
| penalty-area entries, penalty area, the box | a cited `penalty_area_entries` |
| progressive pass / carry / action | a cited `progressive_actions` |
| possessions lost in the final third | a cited `possessions_lost_in_final_third` |
| transition, counter-attack | a moment with the `counter` tag |
| build-up phase | a moment with a `build_up` |
| threat created | a cited `threat_created`, or a moment with `xt_added`, `key_pass_xt_added` or `team_threat` |
| shot-location value | a moment with `shot_zone_value` |

## Match summary

`src/match_summary.py` reads `data/match_xt.csv` and `data/key_moments.json` and writes `data/match_summary.json`: whole-match facts for the Analyst, with no prose.

| Field | Meaning |
|---|---|
| `teams` | Team id → display name. |
| `final_score` | Goals per team. |
| `result_line` | The result in words, built from the goal timeline: `London Red won 2-1 after trailing from the 61st minute to the 74th`. A draw is `<team> and <team> drew 1-1`; a winner that never trailed gets no "after trailing" part. |
| `goals` | In order: `moment_id`, `period`, `minute`, `second`, `team`, `scorer`, `score_after`. |
| `leads` | Each spell one team was ahead: `team`, `from_*` (`period`, `minute`, `second`) and `ends_at`. A lead ended by a goal (`ends_at: goal`) also has `to_*` and `seconds`, counting stoppage time (a lead across half-time adds the first half up to its last event, then from 45:00). A lead that lasts to the end (`ends_at: full_time`) has **no end time and no length**: the final whistle isn't recorded, and the last event is not the whistle. |
| `minutes_led` | Total per team, to 1 decimal, from leads ended by a goal. `null` for a team whose lead lasted to full time (its length is unknown). |
| `first_half_summary` | Per team: `threat_created`, `shots` and `goals` in the first half. |
| `by_half` | `first_half` and `second_half`, per team: `threat_created`, `final_third_entries`, `penalty_area_entries`, `progressive_actions`, `possessions_lost_in_final_third`, `shots`, `saves` (shots by the other team that this team's goalkeeper saved). Definitions above. |
| `momentum_runs` | One per `momentum_shift` moment: `moment_id`, `team` and `goals_in_run`, the ids of the goals from the start of its first block to the end of its `last_minute` (in `end_period`). |
| `moment_ids` | The key-moment ids in match order. |

## Analysis

`src/run_analyst.py` sends the key moments (as the Narrator sees them: no raw coordinates or possession clock) and the match summary to the Analyst and writes `data/analysis.json`. It never reads `data/narrations.json`.

| Field | Meaning |
|---|---|
| `match_headline` | One sentence that gives the final score (winner's goals first, e.g. `2-1`) and names the winning team (both teams for a draw). |
| `story_arc` | `[{moment_id, role}]` in match order, each moment at most once. `role`: `opening` (at most one, first), `build_up`, `turning_point` (exactly one), `response`, `decider` (at most one, a goal), `other`. |
| `turning_point` | `{moment_id, reason}`: the arc's turning point, and one sentence that quotes at least one xT number from that moment. It must be a moment that changed the **score state** (a goal from level to a lead, or from a lead to level) or the **threat balance** (a `momentum_shift`). The Analyst is told to prefer the first goal that changed the score state toward the result. |
| `phase_notes` | 3–5 `{text, cites}`. `cites` are paths into the input, e.g. `m09.team_threat` or `summary.by_half.second_half.london_red.final_third_entries`. Every number and minute in `text` must be in a cited fact. At least one note cites `summary.first_half_summary`, and `result_line` is quoted word for word in the headline or a note. |
| `moment_priority` | `{essential, supporting}`: no id in both; every goal and the turning point essential; every essential moment in `story_arc`. |

**Connectors.** The headline and phase notes can't use causal or temporal connectors ("preceded", "led to", "sparked", "because", "before", "after", "ahead of", "caused"): the checks confirm facts, not that one thing caused or came before another. The list is `CONNECTORS` in `src/style_rules.py`. A fact phrase quoted **in full** (such as `result_line`'s "after trailing") is exempt; a partial quote is not. The turning point's reason may use them, because it explains why.

The file also keeps `status`, `checks`, `retries`, every attempt and `input_hash` (the cache key). `python src/run_analyst.py --verify` re-checks it with no model calls.

## Player summaries

`src/player_summary.py` reads `data/match_xt.csv` and `data/key_moments.json` and writes `data/player_summaries.json`: `{"players": {name: facts}}` for every player who appears in a key moment or took a shot, by team (London Red first) then shirt number. Facts only.

| Field | Meaning |
|---|---|
| `team` | Team id. |
| `passes_completed`, `passes_attempted` | Pass events, and the complete ones. |
| `xt_added` | `xt_added` of the player's completed passes and carries (threat created), to 4 decimals. |
| `final_third_entries` | Completed passes and carries from outside the final third into it. |
| `shots` | Shots taken. |
| `saves` | Goalkeepers only: the other team's saved shots (saves have no event of their own). |
| `moment_ids` | Key moments whose `players` list names the player, in match order. |

## Personalized recaps

`src/run_personalizer.py` writes `data/personalized/<profile_key>.json`, one file per reader profile. The code is in `src/profiles.py` (profile, selection), `src/voices.py` and `src/personalizer.py` (instructions, checks). It reads the frozen files above and never changes them.

**Profile.** `{mode: analyst|fan, voice: studio|stadium, language: en|ar, favourite_team: london_red|london_blue|none, focus_player: <name>|none}`, validated in code (`focus_player` must be in `player_summaries.json`). The key is the five values joined by `-`, with the player as a slug: `fan-stadium-en-none-cass_dunmore`. Arabic is not built yet.

**Selection** (code, no model calls), always in match order (the story order; `story_arc` is in match order).
- `focus_player`, either mode: every moment whose `players` list names that player, and only those, with no cap.
- `analyst`: every moment.
- `fan`: every goal and the Analyst's turning point; with a favourite team, also up to 3 other moments that involve it, ranked by `xt_added`, highest first, at most 7 in all. Only `biggest_threat_swing` moments have `xt_added`; the others rank after them, in match order.
- `favourite_team`: no reordering. Each saved moment has `involves_favourite`. A moment involves a team when it is that team's moment or names one of its players.

**Per moment**, one model call with the moment's narration, its facts (`narrator.moment_input` without the clock's `second`) and the reader; it returns `headline` and `lines`.

**Recap.** Code writes the facts as a skeleton (`personalizer.recap_skeleton`), in match order: `result_line` (with a favourite team: "London Blue and London Red met, and <result_line>."), one sentence per goal from `score_effect` ("Niko Vane's goal in the 61st minute put London Blue 1-0 up."), the turning point (analyst mode adds its key pass and shot xT), and for a focus player one sentence of `player_summaries.json` stats (analyst mode adds final-third entries and xT). The model only rewords it, returning `lines`; the Stadium voice may add up to 3 bursts of at most 3 words with no facts ("Goal!").

**Checks**, all in code, with up to 2 retries: grounding, style (`BLOCKED`, plus `PERSONALIZER_BLOCKED` always and `FAN_BLOCKED` in fan mode; `CONNECTORS` and `PERSONALIZER_CONNECTORS` in the recap and in analyst-mode moments), polish and term backing, as for the Narrator and Analyst. Plus:
- every text: line, sentence, word and exclamation limits per mode and voice; no line break inside a line; a distance in metres only in a sentence with a shot verb (`SHOT_VERBS`: scored, missed, denied, saved, stopped, shot, and their present tense).
- moments: `build_up` word for word if used; the focus player named; numbers against the narration: analyst mode at least as many, fan mode fewer and no xT number (any value of an xT fact), so a fan version always has fewer numbers than the analyst one.
- recap: grounded only in the skeleton (nothing added); each skeleton sentence's anchor (`result_line`, each `score_effect`, "turning point", the stats phrase) word for word and in skeleton order (nothing dropped or reordered), with its names, minute and stats phrases in the same sentence; the final score winner first; the favourite team named first; at most `MAX_NUMBERS` numbers per sentence.

| Field | Meaning |
|---|---|
| `profile`, `profile_key` | The profile and its key (the file name). |
| `selection` | The moment ids, in match order. |
| `player` | The focus player's facts, or `null`. |
| `moments` | Per moment: `id`, `involves_favourite`, `status`, `output` (`headline`, `lines`: an array, one display line each), `checks`, `retries`, `attempts`, `input_hash`. |
| `recap` | The same, with `output.lines`. |

`python src/run_personalizer.py --verify` re-checks every file with no model calls.
