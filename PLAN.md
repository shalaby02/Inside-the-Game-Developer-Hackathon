# Project Plan — Inside the Game

**Time budget:** ~45 minutes a day for 14 days (about 10.5 hours in total).
**Rule for every day:** finish the "Done when" item, commit, push. If you run out of time, cut scope. Don't skip the commit.

---

## The big idea in one picture

```
 generate_match.py         xt_model.py              Agents (LLM)
 (plain code)              (plain code)
┌──────────────┐   events  ┌──────────────┐  numbers ┌──────────┐  key moments ┌──────────┐  story ┌──────────────┐
│ Synthetic    │ ────────▶ │ Expected     │ ───────▶ │ Analyst  │ ───────────▶ │ Narrator │ ─────▶ │ Personalizer │ ─▶ recap
│ match data   │  (JSON)   │ Threat (xT)  │          │          │              │          │        │ mode + lang  │
└──────────────┘           └──────────────┘          └──────────┘              └──────────┘        └──────────────┘
```

- **Plain code does the maths.** The generator and the xT model are normal Python. They are fast, free and always give the same answer.
- **Agents do the words.** The agents never calculate stats. They only explain numbers that the code gives them. This stops the AI from making up facts.
- **Build offline first, add Microsoft Foundry later.** Days 1–7 work on your laptop with no cloud. If Azure setup goes wrong, you still have a working project.

### What is Expected Threat (xT)?
Split the pitch into a grid (12 × 8 boxes). Each box gets a number: "how likely is a goal soon if you have the ball here?" Near the opponent's goal = high, near your own goal = low.
When a player passes or dribbles the ball from box A to box B, the **xT added** = value(B) − value(A).
Big positive numbers = dangerous moves. That is how we find "key moments".

### The three agents
| Agent | Gets | Produces |
|---|---|---|
| **Analyst** | xT numbers, top actions, team totals | 3–5 key moments with a short factual reason each |
| **Narrator** | Analyst's key moments + final score | A match recap story in plain English |
| **Personalizer** | Narrator's recap + `mode` + `language` | Final recap: *analyst* (tactical, uses xT) or *casual fan* (fun, no jargon), in English or a 2nd language |

---

## Proposed folder structure

```
Inside-the-Game-Developer-Hackathon/
├── README.md              ← what the project is, how to run it, demo link
├── PLAN.md                ← this file
├── requirements.txt       ← list of Python packages
├── .env.example           ← template for secrets (the real .env is never committed)
├── .gitignore
│
├── src/
│   ├── generate_match.py  ← makes the synthetic match (plain code)
│   ├── xt_model.py        ← xT grid + "xT added" for each action (plain code)
│   ├── analysis.py        ← turns xT into summaries: top moments, team totals
│   ├── agents/
│   │   ├── analyst.py
│   │   ├── narrator.py
│   │   ├── personalizer.py
│   │   └── prompts/       ← the instructions for each agent, as .txt files
│   ├── pipeline.py        ← runs everything in order
│   └── app.py             ← simple demo screen (Streamlit) — optional
│
├── data/
│   └── match.json         ← output of the generator
├── outputs/               ← example recaps and charts (committed, so judges can see them)
├── tests/                 ← a few small checks
└── docs/
    ├── architecture.png   ← diagram for the README
    └── demo-script.md     ← what you will say in the 2-minute video
```

Small on purpose: about 8 Python files in total.

---

## What to install and set up, in order

| # | What | Why | Notes |
|---|---|---|---|
| 1 | **Python 3.12** ✅ | Runs the project | You also have 3.15, which is very new. Some packages (especially Azure ones) may not support it yet. Both are installed side by side, and plain `py` picks 3.15, so always create the venv with `py -3.12 -m venv .venv`. |
| 2 | **Git** ✅ | Version control | Already installed. |
| 3 | **VS Code** ✅ + **Python extension** | Editor | VS Code is installed. Add the "Python" extension by Microsoft. |
| 4 | **GitHub account** + make this repo **public** | Hackathon requirement | Check it's public in Settings → General. |
| 5 | **Virtual environment** (`.venv`) | Keeps this project's packages separate | One command, we'll do it on Day 1. |
| 6 | **Python packages (local)**: `numpy`, `pandas`, `matplotlib`, `mplsoccer`, `python-dotenv`, `pytest`, `streamlit` | Maths, charts, pitch drawings, secrets, tests, demo screen | Installed from `requirements.txt` on Day 1. |
| 7 | **Azure account** | Needed for Microsoft Foundry | Use hackathon credits, Azure for Students, or a free account. Do this before Day 8 because approval can take a while. |
| 8 | **Azure CLI** (`az`) + `az login` | Lets your code sign in to Azure safely, with no keys in the code | Not installed yet. |
| 9 | **Microsoft Foundry project** + **one deployed chat model** | The "brain" for the agents | Created in the Foundry web portal on Day 8. A small, cheap model is enough. |
| 10 | **Azure Python packages**: `azure-ai-projects`, `azure-identity` (or Microsoft Agent Framework, if the hackathon recommends it) | Code talks to Foundry | We'll confirm the right SDK on Day 8 against the hackathon's rules. |
| 11 | **Screen recorder** | 2-minute demo | Clipchamp comes with Windows 11, and it can also edit. |

---

## Day-by-day plan

### Week 1 — Everything works offline (no cloud)

**Day 1 — Setup** ✅
- Install Python 3.12 and the VS Code Python extension.
- Create the folder structure, `.gitignore`, `.venv`, `requirements.txt`. Install the packages.
- Done when: `python -c "import pandas, mplsoccer"` runs with no error and the skeleton is pushed.

**Day 2 — Design the match data** ✅
- Decide what one event looks like, e.g. `{minute, team, player, type: pass|carry|shot, start_x, start_y, end_x, end_y, outcome}`.
- Pick 2 fictional teams, 11 players each, and a final score.
- Write it down in `docs/data-format.md`.
- Done when: you can describe one full attacking move as 4–5 events on paper.

**Day 3 — Match generator** ✅
- `generate_match.py` creates around 300–600 events using a fixed random seed, so you get the same match every time.
- Plant 4–6 "story" moments on purpose: a goal, a big missed chance, a fast counter-attack, a late equaliser.
- Done when: `data/match.json` exists and the goals in it match your chosen score.

**Day 4 — xT model** ✅
- `xt_model.py`: build a 12 × 8 grid where value grows closer to the goal (a simple formula is fine). Write a function that gives the xT added for each pass/carry.
- Done when: a pass from midfield into the box gives a clearly positive number, and a back-pass gives a negative one.

**Day 5 — Analysis + one chart**
- `analysis.py`: top 10 actions by xT added, xT per team, xT per player, and xT over time (by 5-minute blocks).
- Draw one picture: a pitch with the top 5 actions as arrows (mplsoccer), saved to `outputs/`.
- Done when: the planted story moments show up in the top 10. If they don't, adjust the generator.

**Day 6 — Agent "stubs" + a few tests**
- Write the 3 agents as plain functions with fake, template-based output (no AI yet). Decide the input and output of each one.
- Add 3–4 tests in `tests/` (e.g. "xT grid has 96 values", "generator is repeatable").
- Done when: `pytest` passes.

**Day 7 — Full offline pipeline + buffer**
- `pipeline.py` runs: generate → xT → analysis → Analyst → Narrator → Personalizer and prints a recap.
- Use the rest of the time to catch up.
- Done when: one command prints a (boring, template) recap from start to finish.

### Week 2 — Real agents, demo, polish

**Day 8 — Microsoft Foundry setup**
- Create the Foundry project, deploy one chat model, run `az login`, put the endpoint in `.env`.
- Send a "hello" message from Python.
- Done when: Python prints a reply from your Foundry model. Check `.env` is **not** in git.

**Day 9 — Analyst agent (real)**
- Write the Analyst's instructions in `prompts/analyst.txt`. Give it the analysis numbers and ask for 3–5 key moments as JSON.
- Done when: it picks sensible moments and every number it mentions exists in the data.

**Day 10 — Narrator agent (real)**
- The Narrator turns the key moments into a recap of about 150 words.
- Done when: the recap reads well and doesn't invent goals or players.

**Day 11 — Personalizer agent (real)**
- 2 modes × 2 languages = 4 versions. Save all 4 to `outputs/`.
- Done when: the 4 recaps are clearly different and the 2nd language reads naturally (ask a native speaker if you can).

**Day 12 — Demo screen**
- `app.py` with Streamlit: show the pitch chart and the key moments, with two dropdowns (mode, language) and a "Generate recap" button.
- If this takes too long, skip it and demo in the terminal. That's fine.
- Done when: you can click through the whole story in under 2 minutes.

**Day 13 — README and clean-up**
- README: what it does, architecture diagram, how to run, screenshots, example outputs, limitations.
- Check: no secrets in the repo, a fresh clone + `pip install -r requirements.txt` works.
- Done when: a stranger could run it using only the README.

**Day 14 — Record the demo and submit**
- Follow `docs/demo-script.md`: problem (15s) → the match and xT chart (30s) → agents working (45s) → the 4 recaps (20s) → wrap-up (10s).
- Record, trim to under 2:00, upload, add the link to the README, submit.
- Done when: it's submitted. 🎉

---

## If you fall behind, cut in this order
1. Streamlit screen (Day 12) → demo in the terminal instead.
2. Second language → keep English only, mention it as "next step".
3. Tests → keep just 1–2.

Never cut: the working pipeline, the README, the demo video.

---

## Optional extras (only if there's time)

**`recovery_value`**: credit for winning the ball back. Don't build this yet.
- A separate column in `data/match_xt.csv`, not part of `xt_added`.
- For `tackle` and `interception` events with outcome `won`: the xT value of the zone where the ball was won, from the winning team's point of view.
- All other events get 0.
- Frames: tackle and interception rows are already stored from the winning team's point of view, so use their `start_x`, `start_y` as they are. Flip (`100 − x`, `100 − y`) only if you take the spot from the other team's event instead, for example the end point of the pass that was intercepted, which is in the passer's frame.
