# xT Match Assistant

Replays a match as if live: code computes the threat numbers, AI agents explain, personalise and narrate each moment, and every sentence is checked against the data. The event-by-event design means the same pipeline could be adapted to a live data feed.

Built for the Microsoft "Inside the Game: Developer Hackathon". All data is synthetic. The teams, players and match are invented.

- **Live demo:** [ADD DEPLOYED URL]
- **Demo video (under 2 minutes):** [ADD VIDEO URL]

---

## What it does

xT Match Assistant turns a stream of synthetic football events into explainable match intelligence, written narratives and automated recaps.

1. A script generates a fictional fixture, **London Red v London Blue** (2-1 to Red after trailing from the 61st to the 74th minute): 694 events with clock times, players, pitch coordinates and outcomes. Six story moments are planted so there is something worth explaining.
2. A distance-based **Expected Threat (xT)** model values every zone of the pitch and scores every completed pass or carry by how much more dangerous it made the ball.
3. Plain-code rules pick **11 key moments** and store each as facts only (names, minutes, numbers).
4. Three AI agents work from those facts:
   - **Narrator** explains one moment at a time and says why it mattered.
   - **Analyst** reads all moments plus a code-computed match summary and chooses the story: headline, turning point, a role for each moment, and which moments are essential.
   - **Personalizer** adapts the story to a viewer profile: analyst or fan mode, a calm "Studio" or energetic "Stadium" voice, a favourite team, or a follow-this-player view.
5. A static web page replays the match on a controllable clock with a threat chart, timed commentary cards, a profile switcher and a recap. It also outputs timed, machine-readable overlay data.

## Architecture

```
Generator -> match.json -> xT model -> match_xt.csv -> Detector -> key_moments.json
                                                           |
                          +--------------------------------+------------------+
                          v                                                   v
               NARRATOR (per moment)                          ANALYST (whole match)
               -> narrations.json                             + match_summary.json
                          |                                   -> analysis.json
                          +-----------------+---------------------------------+
                                            v
        player_summary.py -> player_summaries.json (code-computed per-player facts)
                                            v
                  PERSONALIZER: profile = mode, voice, favourite team, focus player
                  - code selects the moments each viewer sees
                  - code writes the recap skeleton (result, goals in order, turning point)
                  - the model only adds wording and voice
                                            v
                  data/personalized/<profile>.json  (4 demo profiles)
                                            v
                  build_site.py -> web/ (static page + overlays.json)
```

The Narrator and Analyst run side by side and do not feed each other. The Personalizer combines them.

## Trust by design

The numbers come from code, the words come from the model, and every generated sentence is checked against the source facts.

- **Grounding check:** every name, number and minute in a generated text must appear in that moment's facts.
- **Style check:** blocks invented detail (how a shot was hit, crowd, weather), cause-and-effect wording the data cannot support, and pronouns (the data has no player gender).
- **Term check:** football terms such as "transition" or "final third" are accepted only when code has computed the matching fact.
- **Polish check:** catches repeated words, missing full stops and clumsy phrases.
- **Recap anchors:** recap sentences built by code must appear word for word, in order.
- **Retry, then flag:** a failed check triggers up to two retries, then the moment is marked failed.
- **Human proofread:** final texts are proofread by hand. The `--verify` modes re-run all checks on the saved text without calling a model.

## Football terms used, and how they are defined

Pitch coordinates run 0 to 100 on both axes, and both teams attack toward x = 100.

| Term | Definition |
|---|---|
| Defensive / middle / final third | x below 33.3 / 33.3 to 66.7 / 66.7 or above |
| Final-third entry | completed pass or carry from outside the final third into it |
| Penalty-area entry | completed pass or carry from outside the box into it |
| Progressive action | completed pass or carry that gets a set distance closer to goal (thresholds are this project's own choice, documented in `docs/data-format.md`) |
| Transition (counter-attack) | a move that starts with a won tackle or interception in the team's own half and ends in a shot within 15 seconds |
| xT | how likely possession in a zone is to lead to a goal soon; the best zone is about 0.30. It is not shot probability. |
| Shot-location value | the zone value where a shot was taken (not xG; there is no shot model) |

The xT grid is a hand-built distance formula (value halves every 8 units from goal, sideways distance counts 70%), not trained on real matches.

## Microsoft and Azure technologies

- **Microsoft Foundry:** a chat model (gpt-5-mini, West Europe) deployed in a Foundry project and called from Python by all three agents.
- **GitHub:** public repository. 
- **Azure Static Web Apps (or the host you used):** hosts the page. [EDIT to match your deployment]

## Run it yourself

Requires Python 3.12.

```
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1            # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

Run the data pipeline (no model calls):

```
python src/generate_match.py          # writes data/match.json and match.csv
python src/validate_match.py          # checks the data against docs/
python src/xt_model.py                # writes data/match_xt.csv
python src/key_moments.py             # writes data/key_moments.json
python src/match_summary.py           # writes data/match_summary.json
python src/player_summary.py          # writes data/player_summaries.json
```

Check saved agent outputs without calling any model:

```
python src/verify_narrations.py
python src/run_analyst.py --verify
python src/run_personalizer.py --verify
python -m pytest -q
```

Build and view the page:

```
python src/build_site.py              # refuses to build if any saved text fails a check
cd web
python -m http.server 8000            # then open http://localhost:8000
```

Opening `index.html` by double-click will not work, because browsers block loading the data files that way.

### Re-running the agents (needs a Foundry deployment)

Create a `.env` file in the repo root (it is git-ignored, never commit it):

```
FOUNDRY_ENDPOINT=...
FOUNDRY_DEPLOYMENT=...
FOUNDRY_API_KEY=...
```

> **Warning:** the saved narrations, analysis and personalized outputs have been proofread by hand. Running an agent runner without `--verify` (and especially with `--force`) regenerates text and can overwrite those edits. Use `--verify` unless you mean to regenerate.

The generated match data is frozen. Re-running the generator should give identical files (checked byte for byte), but all story checks were done on the committed version.

## Repository layout

| Path | Contents |
|---|---|
| `src/` | generator, validator, xT model, detector, three agents, checks, site builder |
| `data/` | frozen match data, key moments, narrations, analysis, personalized outputs |
| `web/` | static page, styles, script, and compact JSON data (no keys, no build step) |
| `tests/` | automated tests |
| `docs/` | data format, teams, match story, definitions |

## Limits (stated openly)

- **Replay, not live inference.** The page replays a precomputed analysis. No model is called while the match plays.
- **Going live would need work.** The pipeline processes events one at a time, so it could be adapted to a live feed: xT scoring and per-moment narration work as events arrive. Match-wide rules (momentum spells, counter rankings, the final recap) would need running versions, and live latency and cost are untested.
- **No off-ball data.** There are no player positions between touches, so no pressing, formation, speed or pass-difficulty analysis, and no possession percentage.
- **Checks confirm values, not meaning.** A number can pass because it exists in the facts even when attached to the wrong thing, which is why final texts are proofread by a person.
- **Synthetic and simple.** One invented match, a hand-built xT map, and English only. [EDIT if Arabic is added]
- **Direct model calls.** The agents are specialised roles calling a Foundry-deployed model from Python, not agents registered in the Foundry agent service. [EDIT if you move them]

## Ideas for next steps

- Foundry agent registration with keyless sign-in
- Arabic output with a back-translation check
- Running (live) versions of the match-wide rules
- A pass map for each key moment
- A `recovery_value` column for won tackles and interceptions

## Data and licensing notes

All teams, players and events are fictional and generated by this project. No real match data, footage or third-party data sets are included.

## Hackathon

Built for the Microsoft "Inside the Game: Developer Hackathon". Not affiliated with or endorsed by any football league or club.