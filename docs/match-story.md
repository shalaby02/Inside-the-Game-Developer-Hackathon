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

### 1. The big miss (1st half, 38', London Red)
At 0–0, Luca Merriden plays a through ball and Cass Dunmore is clean through, but he shoots wide from about 8 metres out.
- **In the data:** a Merriden `pass` with a big xT gain that ends around (92, 50), then Dunmore's `shot` from about (94, 48) with `outcome: off_target`.
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

### 4. Momentum swing (70'–90', London Red)
After the save, Red push higher and Blue drop deeper.
- **In the data:** Red have clearly more xT than Blue in every 5-minute block from 70' to the end, after Blue had the most xT in the 60–65 and 65–70 blocks. In the last 10 minutes, most of Blue's events are `clearance`s at low `x`.
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

- **Why it matters:** it's the biggest single-possession xT gain in the match and shows the counter-attack style clearly.

### 6. Late winner (2nd half, 89', London Red)
Theo Brannick gets free on the right and crosses, and Cass Dunmore, who missed at 38', scores the winner.
- **In the data:** a Brannick `carry` to about (85, 12), then a `pass` from (85, 12) to (94, 52) with `is_assist: true`, then Dunmore's `shot` from (94, 52) to (100, 47) with `outcome: goal`.
- **Why it matters:** it finishes the comeback and closes the Dunmore story the recap can be built around.
