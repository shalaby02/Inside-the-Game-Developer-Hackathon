# Match story

The match the generator will produce, written down first so the data has a story to find.

## Final score

**London Red 2 – 1 London Blue**: a comeback win for Red.

Red have most of the first half but it ends 0–0. Blue go ahead against the run of play just after the hour. Red's goalkeeper keeps them in it, then Red equalise on a fast counter-attack and win it in the last minute.

## Goals

| Time | Team | Scorer | Assist | How |
|---|---|---|---|---|
| 2nd half, 61' | London Blue | Niko Vane (9) | Dario Quill (11) | Midfield tackle, then a break down the left (moment 2, the 5-event example in [data-format.md](data-format.md)) |
| 2nd half, 74' | London Red | Rafael Tovey (10) | Theo Brannick (7) | Fast counter-attack from Red's own box (moment 5) |
| 2nd half, 89' | London Red | Cass Dunmore (9) | Theo Brannick (7) | Cross from the right, finished in the box (moment 6) |

## Planted story moments

These are put in on purpose. On Day 5 they should show up in the analysis. If they don't, adjust the generator.

Moments 1, 2, 3, 5 and 6 are scripted event by event in `src/generate_match.py`. Moment 4 is not scripted: it comes from the generator's phase settings (`PHASES`), which change how each team plays from 70' on. So moment 4 shows up as a trend over time, not as single events.

**How "threat" is measured in this doc:** a team's xT in a time block is the sum of `xt_added` over its **completed passes and carries only**. Turnovers (incomplete passes, lost carries) are left out here. They have negative `xt_added`, and a team that attacks a lot also loses the ball near the box a lot, so including them hides who was on top. With turnovers included, the 75–80 block is Red −0.018 against Blue −0.020. With completed passes and carries only, it's Red +0.155 against Blue +0.028.

### 1. The big miss (1st half, 38', London Red)
At 0–0, Luca Merriden plays a through ball and Cass Dunmore is clean through, takes one touch, and shoots wide from about 6 metres out.
- **In the data:** a Merriden `pass` with a big xT gain from (56, 44) to (92, 50), a short Dunmore `carry` from (92, 50) to (94, 48), then Dunmore's `shot` from (94, 48) with `outcome: off_target`. The carry is there because a pass must end where the next touch starts (rule 3 in [data-format.md](data-format.md)). (94, 48) is about 6.4 m from the middle of the goal on a 105 × 68 m pitch.
- **Why it matters:** Red's best first-half spell gets them nothing. It also sets up Dunmore's redemption in moment 6.

### 2. Blue go ahead (2nd half, 61', London Blue)
Against the run of play, Sam Okoro wins the ball in midfield, Dario Quill breaks down the left and crosses, and Niko Vane scores.

| Time | Player (No.) | Type | From → To | Outcome |
|---|---|---|---|---|
| 61:04 | Sam Okoro (4) | tackle | (44, 46) | won |
| 61:07 | Sam Okoro (4) | pass | (44, 46) → (58, 70) | complete |
| 61:10 | Dario Quill (11) | carry | (58, 70) → (74, 76) | complete |
| 61:13 | Dario Quill (11) | pass | (74, 76) → (88, 52) | complete, `is_assist` |
| 61:14 | Niko Vane (9) | shot | (88, 52) → (100, 50) | goal |

- **In the data:** the exact 5 events from the example in [data-format.md](data-format.md). Before this, Red have more xT in most first-half blocks, so Blue's goal comes against the run of play.
- **Why it matters:** it puts Red behind and makes the rest of the match a comeback.

### 3. The goalkeeper save (2nd half, 67', London Blue shot)
At 0–1, Kai Renwick slips Niko Vane through one-on-one, and Red goalkeeper Ellis Harwick (1) makes a low save.
- **In the data:** a Renwick `pass` ending around (90, 55), then Vane's `shot` from (91, 55) to about (99, 52) with `outcome: saved`. There is no separate save event: a `saved` shot by Blue is credited to Harwick.
- **Why it matters:** if it goes in, it's 0–2 and the comeback never happens.

### 4. Momentum swing (70' to the end, London Red)
After the save, Red push higher and Blue drop deeper.
- **In the data:** Red have more xT than Blue in every 5-minute block from 70' to the end of the match (including stoppage time, 90'+), after Blue had more xT than Red in the 60–65 and 65–70 blocks. In the last 10 minutes (83' onward), most of Blue's events are `clearance`s at low `x`.
- **Not scripted:** this comes from the phase settings in the generator, not from planted events (see the note at the top of this section).
- **Why it matters:** this is the "xT over time" chart's headline: Red take control well before the scoreline shows it.

### 5. Fast counter-attack (2nd half, 74', London Red, equaliser)
A Blue attack breaks down in Red's box, and Red go the length of the pitch in about 12 seconds.

| Time | Player (No.) | Type | From → To | Outcome |
|---|---|---|---|---|
| 74:10 | Rory Calloway (5) | interception | (17, 38) | won |
| 74:12 | Rory Calloway (5) | pass | (17, 38) → (35, 30) | complete |
| 74:14 | Luca Merriden (8) | pass | (35, 30) → (62, 22) | complete |
| 74:16 | Theo Brannick (7) | carry | (62, 22) → (80, 30) | complete |
| 74:21 | Theo Brannick (7) | pass | (80, 30) → (90, 47) | complete, `is_assist` |
| 74:22 | Rafael Tovey (10) | shot | (90, 47) → (100, 46) | goal |

- **In the data:** `possession_seconds` = 12 in `data/match_xt.csv`. Red go from x = 17 to a shot at x = 90 in 12 seconds, which is one of the two fastest moves from a team's own half to a shot. The other is Blue's 61' goal, in 10 seconds from x = 44.
- **Why it matters:** it's a **tempo** moment, not an xT one. Most of its passes start far from goal, where zone values are tiny, so no single action ranks high for xT except Brannick's final ball. What stands out is the speed: the length of the pitch in about 12 seconds, which shows the counter-attack style clearly.

### 6. Late winner (2nd half, 89', London Red)
Theo Brannick gets free on the right and crosses, and Cass Dunmore, who missed at 38', scores the winner.
- **In the data:** a Brannick `carry` to about (85, 12), then a `pass` from (85, 12) to (94, 52) with `is_assist: true`, then Dunmore's `shot` from (94, 52) to (100, 47) with `outcome: goal`.
- **Why it matters:** it finishes the comeback and closes the Dunmore story the recap can be built around.
