// xT Match Assistant: replays the match from web/data/ (built by src/build_site.py).
// No build step, no external services. Optional URL parameters, handy for
// screenshots: ?t=<timeline seconds>&profile=<profile key>&recap=1

(() => {
  "use strict";

  const FILES = ["match", "events", "threat", "key_moments", "profiles", "overlays", "meta", "xt_grid"];
  const TYPE_LABELS = {
    goal: "Goal", save: "Save", big_chance_missed: "Big chance missed",
    momentum_shift: "Spell on top", biggest_threat_swing: "Threat swing",
  };
  const SPEEDS = [1, 10, 60];
  const STORE_KEY = "itg-profile";

  const $ = (id) => document.getElementById(id);
  const svgNS = "http://www.w3.org/2000/svg";
  const params = new URLSearchParams(location.search);

  const state = { t: 0, playing: false, speed: 60, profile: null, recapOpen: false, lastFrame: 0, shown: -1, mapId: null };
  let D; // loaded data

  // ------------------------------------------------------------ helpers

  function el(tag, attrs = {}, text) {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
    if (text !== undefined) n.textContent = text;
    return n;
  }

  function svg(tag, attrs = {}) {
    const n = document.createElementNS(svgNS, tag);
    for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
    return n;
  }

  // A headline as shown on screen: no trailing full stop.
  const displayHeadline = (h) => (h.endsWith(".") && !h.endsWith("..") ? h.slice(0, -1) : h);

  const pad = (n) => String(n).padStart(2, "0");

  function timelineSeconds(period, minute, second) {
    const p = D.match.timeline.periods.find((x) => x.period === period);
    return p.offset + (minute - p.start_minute) * 60 + second;
  }

  function periodAt(t) {
    const ps = D.match.timeline.periods;
    let p = ps[0];
    for (const x of ps) if (t >= x.offset) p = x;
    return p;
  }

  function clockText(t) {
    const p = periodAt(t);
    const secs = Math.round(p.start_minute * 60 + t - p.offset);
    return `${pad(Math.floor(secs / 60))}:${pad(secs % 60)}`;
  }

  function halfText(t) {
    if (t >= D.match.timeline.length_seconds) return "Full time";
    return periodAt(t).period === 1 ? "1st half" : "2nd half";
  }

  const teamName = (key) => D.match.teams[key];
  const fmt = (v) => (Math.abs(v) < 0.00005 ? "0.000" : v.toFixed(3));

  function storeGet() { try { return localStorage.getItem(STORE_KEY); } catch { return null; } }
  function storeSet(v) { try { localStorage.setItem(STORE_KEY, v); } catch { /* not available */ } }

  // ------------------------------------------------------------ data

  async function load() {
    const out = {};
    await Promise.all(FILES.map(async (f) => {
      const r = await fetch(`data/${f}.json`);
      if (!r.ok) throw new Error(`data/${f}.json: ${r.status}`);
      out[f] = await r.json();
    }));
    const cols = out.events.columns;
    const ix = Object.fromEntries(cols.map((c, i) => [c, i]));
    out.blocks = out.threat.blocks.map((b) => ({ ...b, events: [] }));
    for (const row of out.events.rows) {
      if (!["pass", "carry"].includes(row[ix.type]) || row[ix.outcome] !== "complete") continue;
      const t = row[ix.t];
      const b = out.blocks.find((x) => t >= x.t_start && t < x.t_end);
      if (b) b.events.push({ t, team: row[ix.team], xt: row[ix.xt_added] });
    }
    out.rows = out.events.rows.map((r) => Object.fromEntries(cols.map((c, i) => [c, r[i]])));
    out.possessions = {};
    for (const e of out.rows) (out.possessions[e.possession_id] ||= []).push(e);
    out.moments = Object.fromEntries(out.key_moments.moments.map((m) => [m.id, m]));
    D = out; // timelineSeconds() reads D
    out.goals = out.match.goals.map((g) => ({ ...g, t: timelineSeconds(g.period, g.minute, g.second) }));
    return out;
  }

  // Threat for one block as far as the clock has got.
  function blockValues(b, t) {
    if (t >= b.t_end) return { london_red: b.london_red, london_blue: b.london_blue, live: false };
    const v = { london_red: 0, london_blue: 0, live: true };
    for (const e of b.events) if (e.t <= t) v[e.team] += e.xt;
    return v;
  }

  const profile = () => D.profiles.profiles.find((p) => p.key === state.profile);
  const overlays = () => D.overlays.overlays.filter((o) => o.profile_key === state.profile)
    .sort((a, b) => a.start_seconds - b.start_seconds);

  // ------------------------------------------------------------ controls

  function setupControls() {
    const len = D.match.timeline.length_seconds;
    const scrub = $("scrubber");
    scrub.max = len;
    scrub.addEventListener("input", () => { seek(Number(scrub.value)); });
    $("play").addEventListener("click", togglePlay);
    for (const b of document.querySelectorAll(".seg")) {
      b.addEventListener("click", () => setSpeed(Number(b.dataset.speed)));
    }
    document.addEventListener("keydown", (e) => {
      if (e.key !== " " || e.altKey || e.ctrlKey || e.metaKey) return;
      if (e.target.closest("input, button, select, textarea, summary, a")) return;
      e.preventDefault();
      togglePlay();
    });
    $("recap-show").addEventListener("click", () => { state.recapOpen = true; renderRecap(); $("recap").focus(); });
  }

  function setSpeed(s) {
    state.speed = SPEEDS.includes(s) ? s : 60;
    for (const b of document.querySelectorAll(".seg")) {
      b.setAttribute("aria-pressed", String(Number(b.dataset.speed) === state.speed));
    }
  }

  function togglePlay() {
    const len = D.match.timeline.length_seconds;
    if (!state.playing && state.t >= len) seek(0);
    state.playing = !state.playing;
    state.lastFrame = performance.now();
    renderPlay();
    if (state.playing) requestAnimationFrame(tick);
  }

  function renderPlay() {
    const len = D.match.timeline.length_seconds;
    const label = state.playing ? "Pause" : state.t >= len ? "Replay" : "Play";
    $("play").setAttribute("aria-label", label);
    $("play-text").textContent = label;
    $("play-icon").textContent = state.playing ? "❚❚" : state.t >= len ? "↺" : "▶";
  }

  function tick(now) {
    if (!state.playing) return;
    const dt = Math.min(0.25, (now - state.lastFrame) / 1000);
    state.lastFrame = now;
    const len = D.match.timeline.length_seconds;
    const next = Math.min(len, state.t + dt * state.speed);
    seek(next);
    if (next >= len) {
      state.playing = false;
      renderPlay();
      return;
    }
    requestAnimationFrame(tick);
  }

  function seek(t) {
    state.t = Math.max(0, Math.min(D.match.timeline.length_seconds, t));
    renderClock();
    renderChart();
    renderFeed();
    renderRecap();
    if (!state.playing) renderPlay();
  }

  function renderClock() {
    const text = clockText(state.t);
    $("clock").textContent = text;
    $("half").textContent = halfText(state.t);
    const scrub = $("scrubber");
    if (Number(scrub.value) !== Math.floor(state.t)) scrub.value = Math.floor(state.t);
    scrub.setAttribute("aria-valuetext", `${text}, ${halfText(state.t)}`);
    const score = { london_red: 0, london_blue: 0 };
    for (const g of D.goals) if (g.t <= state.t) score[g.team] += 1;
    const s = `${score.london_red}–${score.london_blue}`;
    if ($("score").textContent !== s) $("score").textContent = s;
  }

  // ------------------------------------------------------------ profiles

  function setupProfiles() {
    const box = $("profiles");
    for (const p of D.profiles.profiles) {
      const label = el("label", { class: "choice" });
      const input = el("input", { type: "radio", name: "profile", value: p.key });
      input.addEventListener("change", () => setProfile(p.key));
      label.append(input, el("span", {}, p.label));
      box.append(label);
    }
    const langs = $("languages");
    for (const l of D.meta.languages.filter((x) => x.available)) {
      const label = el("label", { class: "choice" });
      const input = el("input", { type: "radio", name: "language", value: l.code });
      if (l.code === "en") input.checked = true;
      const span = el("span", {});
      span.append(el("span", l.code === "ar" ? { lang: "ar", dir: "rtl" } : {}, l.name));
      label.append(input, span);
      langs.append(label);
    }
    const wanted = params.get("profile") || storeGet();
    setProfile(D.profiles.profiles.some((p) => p.key === wanted) ? wanted : D.profiles.profiles[0].key);
  }

  function setProfile(key) {
    state.profile = key;
    storeSet(key);
    for (const i of document.querySelectorAll('input[name="profile"]')) i.checked = i.value === key;
    const name = `· ${profile().label}`;
    $("commentary-profile").textContent = name;
    $("recap-profile").textContent = name;
    $("voice").textContent = `Voice: ${profile().voice_label}`;
    state.shown = -1;
    renderChart();
    renderFeed();
    renderRecap();
    renderXt();
  }

  // ------------------------------------------------------------ chart

  let chart = null; // {svg, x, y, ...} rebuilt on resize

  function buildChart() {
    const box = $("chart");
    const W = Math.max(280, box.clientWidth);
    const H = W < 520 ? 210 : 250;
    const m = { l: 40, r: 10, t: 26, b: 26 };
    const len = D.match.timeline.length_seconds;
    const values = D.blocks.flatMap((b) => [b.london_red, b.london_blue]);
    const yMax = Math.max(0.6, Math.ceil(Math.max(...values) * 10) / 10);
    const yMin = Math.min(0, Math.floor(Math.min(...values) * 10) / 10);
    const x = (t) => m.l + (t / len) * (W - m.l - m.r);
    const y = (v) => m.t + ((yMax - v) / (yMax - yMin)) * (H - m.t - m.b);

    const s = svg("svg", { width: W, height: H, viewBox: `0 0 ${W} ${H}`, role: "img",
      "aria-label": "Threat created per 5-minute block by London Red and London Blue, so far" });

    // Grid and y axis
    for (let v = 0; v <= yMax + 1e-9; v += 0.2) {
      s.append(svg("line", { class: "gridline", x1: m.l, x2: W - m.r, y1: y(v), y2: y(v) }));
      const label = svg("text", { x: m.l - 6, y: y(v) + 4, "text-anchor": "end" });
      label.textContent = v.toFixed(1);
      s.append(label);
    }
    const yTitle = svg("text", { x: m.l - 6, y: 12, "text-anchor": "end" });
    yTitle.textContent = "xT";
    s.append(yTitle);

    // X axis: match minutes
    const ticks = [[1, 0], [1, 15], [1, 30], [2, 45], [2, 60], [2, 75], [2, 90]];
    for (const [p, min] of ticks) {
      const tx = x(timelineSeconds(p, min, 0));
      const label = svg("text", { x: tx, y: H - 8, "text-anchor": min === 0 ? "start" : "middle" });
      label.textContent = `${min}'`;
      s.append(label);
    }
    const ht = x(D.match.timeline.periods[1].offset);
    s.append(svg("line", { class: "ht", x1: ht, x2: ht, y1: m.t - 4, y2: H - m.b }));
    const htLabel = svg("text", { x: ht + 4, y: m.t + 10 });
    htLabel.textContent = "HT";
    s.append(htLabel);

    const bars = svg("g");
    const markers = svg("g");
    const hits = svg("g");
    const zero = svg("line", { class: "zero", x1: m.l, x2: W - m.r, y1: y(0), y2: y(0) });
    const clock = svg("line", { class: "clock-line", y1: m.t - 8, y2: H - m.b });
    s.append(bars, zero, markers, clock, hits);

    // One hit target per block, the full plot height, for the tooltip.
    D.blocks.forEach((b, i) => {
      const r = svg("rect", { class: "hit", x: x(b.t_start), y: m.t, width: Math.max(1, x(b.t_end) - x(b.t_start)),
        height: H - m.t - m.b, "data-i": i });
      r.addEventListener("pointerenter", (e) => showTip(i, e));
      r.addEventListener("pointermove", (e) => showTip(i, e));
      r.addEventListener("pointerleave", hideTip);
      hits.append(r);
    });

    box.querySelector("svg")?.remove();
    box.prepend(s);
    chart = { s, x, y, m, W, H, bars, markers, clock, hits };
  }

  // A column with a 4px rounded data end and a square baseline end.
  function barPath(x0, w, yBase, yVal) {
    const h = Math.abs(yBase - yVal);
    if (h < 0.5) return "";
    const r = Math.min(4, w / 2, h);
    if (yVal < yBase) { // positive: rounded top
      return `M${x0},${yBase}V${yVal + r}Q${x0},${yVal} ${x0 + r},${yVal}H${x0 + w - r}` +
        `Q${x0 + w},${yVal} ${x0 + w},${yVal + r}V${yBase}Z`;
    }
    return `M${x0},${yBase}V${yVal - r}Q${x0},${yVal} ${x0 + r},${yVal}H${x0 + w - r}` +
      `Q${x0 + w},${yVal} ${x0 + w},${yVal - r}V${yBase}Z`;
  }

  function renderChart() {
    if (!chart || !state.profile) return;
    const { x, y, m, bars, markers, clock } = chart;
    bars.replaceChildren();
    const rows = [];
    for (const b of D.blocks) {
      if (state.t < b.t_start) continue;
      const v = blockValues(b, state.t);
      rows.push({ b, v });
      const slot = x(b.t_end) - x(b.t_start);
      const gap = 2;
      const w = Math.max(2, Math.min(14, (slot - gap - 4) / 2));
      const x0 = x(b.t_start) + (slot - (2 * w + gap)) / 2;
      [["london_red", x0], ["london_blue", x0 + w + gap]].forEach(([team, bx]) => {
        const d = barPath(bx, w, y(0), y(v[team]));
        if (d) bars.append(svg("path", { d, class: `bar-${team.split("_")[1]}${v.live ? " live" : ""}` }));
      });
    }

    markers.replaceChildren();
    const laneY = m.t - 14;
    // Spells first, so the point markers sit on top of them.
    const shown = overlays().filter((o) => o.start_seconds <= state.t)
      .sort((p, q) => (D.moments[q.moment_id].category === "momentum_shift") - (D.moments[p.moment_id].category === "momentum_shift"));
    for (const o of shown) {
      const mo = D.moments[o.moment_id];
      const color = `var(--${mo.team.split("_")[1]})`;
      if (mo.category === "momentum_shift") {
        markers.append(svg("rect", { x: x(mo.t), y: laneY - 3, width: Math.max(4, x(mo.reveal_t) - x(mo.t)), height: 6,
          rx: 3, fill: color, opacity: 0.55 }));
      } else {
        const goal = mo.category === "goal";
        const c = svg("circle", { cx: x(mo.t), cy: laneY, r: goal ? 6 : 5,
          class: `marker${goal ? "" : " other"}`, ...(goal ? { fill: color } : { style: `stroke:${color}` }) });
        const title = svg("title");
        title.textContent = `${clockText(mo.t)} ${TYPE_LABELS[mo.category]}: ${o.headline}`;
        c.append(title);
        markers.append(c);
      }
    }

    const cx = x(state.t);
    clock.setAttribute("x1", cx);
    clock.setAttribute("x2", cx);
    renderTable(rows);
  }

  function blockLabel(b) {
    return b.label.includes("+") ? `${b.label}'` : `${b.label.replace("-", "–")}'`;
  }

  function renderTable(rows) {
    const body = $("threat-table").tBodies[0];
    const key = rows.map((r) => `${r.v.london_red.toFixed(4)},${r.v.london_blue.toFixed(4)}`).join("|");
    if (body.dataset.key === key) return;
    body.dataset.key = key;
    body.replaceChildren(...rows.map(({ b, v }) => {
      const tr = el("tr");
      tr.append(el("th", { scope: "row" }, blockLabel(b) + (v.live ? " (so far)" : "")),
        el("td", {}, fmt(v.london_red)), el("td", {}, fmt(v.london_blue)));
      return tr;
    }));
  }

  function showTip(i, e) {
    const b = D.blocks[i];
    const tip = $("tooltip");
    for (const r of chart.hits.children) r.classList.toggle("on", Number(r.dataset.i) === i);
    if (state.t < b.t_start) {
      tip.replaceChildren(el("div", {}, `${blockLabel(b)}: not played yet`));
    } else {
      const v = blockValues(b, state.t);
      const head = el("div", {}, `${blockLabel(b)}${v.live ? " (so far)" : ""}`);
      head.style.fontWeight = "600";
      const row = (team) => {
        const d = el("div", { class: "row" });
        d.append(el("span", { class: `swatch ${team.split("_")[1]}` }), el("span", {}, `${teamName(team)} ${fmt(v[team])} xT`));
        return d;
      };
      tip.replaceChildren(head, row("london_red"), row("london_blue"));
    }
    tip.hidden = false;
    const box = $("chart").getBoundingClientRect();
    const px = e.clientX - box.left;
    const w = tip.offsetWidth;
    tip.style.left = `${Math.max(0, Math.min(box.width - w, px - w / 2))}px`;
    tip.style.top = `${Math.max(0, e.clientY - box.top - tip.offsetHeight - 14)}px`;
  }

  function hideTip() {
    $("tooltip").hidden = true;
    for (const r of chart.hits.children) r.classList.remove("on");
  }

  // ------------------------------------------------------------ commentary

  function renderFeed() {
    if (!state.profile) return;
    const list = overlays();
    const revealed = list.filter((o) => o.start_seconds <= state.t);
    if (revealed.length === state.shown) return;
    // A newly revealed card takes over the pass map; otherwise keep the chosen one while it is shown.
    const ids = revealed.map((o) => o.moment_id);
    if (revealed.length > state.shown || !ids.includes(state.mapId)) state.mapId = ids.length ? ids[ids.length - 1] : null;
    state.shown = revealed.length;
    const favourite = Object.fromEntries(profile().moments.map((x) => [x.id, x.involves_favourite]));
    const fav = profile().profile.favourite_team;
    $("feed-empty").hidden = revealed.length > 0;
    $("feed").replaceChildren(...revealed.slice().reverse().map((o, i) => {
      const mo = D.moments[o.moment_id];
      const li = el("li", { class: `moment ${mo.team}${i === 0 ? " latest" : ""}`, "data-id": o.moment_id });
      li.addEventListener("click", () => showMove(o.moment_id));
      const meta = el("div", { class: "moment-meta" });
      const time = mo.category === "momentum_shift" ? `${clockText(mo.t)}–${clockText(mo.reveal_t)}` : clockText(mo.t);
      meta.append(el("span", { class: "time" }, time),
        el("span", { class: `badge ${mo.category === "goal" ? "goal" : ""}` }, TYPE_LABELS[mo.category] || mo.category),
        el("span", {}, teamName(mo.team)));
      if (fav !== "none" && favourite[o.moment_id]) meta.append(el("span", {}, `★ involves ${teamName(fav)}`));
      li.append(meta, el("h3", {}, displayHeadline(o.headline)));
      for (const line of o.lines) li.append(el("p", {}, line));
      li.append(el("button", { type: "button", class: "show-move", "aria-pressed": "false" }, "Show the move"));
      return li;
    }));
    markSelected();
    renderMap();
  }

  // ------------------------------------------------------------ pass map

  // The pitch is drawn in metres (105 x 68), attacking left to right. Events
  // are 0-100 in the acting team's frame, attacking x = 100, with y = 0 on the
  // attacker's right, so y = 0 is the bottom edge here.
  const PW = 105, PH = 68;
  const px = (x) => (x * PW) / 100;
  const py = (y) => ((100 - y) * PH) / 100;
  // xT levels for passes and carries: colour (a colour-blind-safe purple-orange
  // scale) and line width. Analyst views show the numbers, fan views the words.
  const XT_LEVELS = [
    { key: "big", min: 0.05, range: "xT +0.050 or more", words: "Much more dangerous", width: 1.1 },
    { key: "gain", min: 0.005, range: "xT +0.005 to +0.050", words: "More dangerous", width: 0.75 },
    { key: "flat", min: -0.005, range: "xT within ±0.005", words: "Little change", width: 0.6 },
    { key: "loss", min: -Infinity, range: "xT below −0.005", words: "Less dangerous", width: 0.6 },
  ];
  const xtLevel = (v) => XT_LEVELS.find((l) => v >= l.min);
  const OUTCOME_WORDS = { off_target: "off target", free_kick: "free kick", yellow_card: "yellow card" };
  const SHOT_LABELS = { goal: "Goal", saved: "Saved", off_target: "Off target", blocked: "Blocked" };
  const signed = (v) => `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(3)}`;
  const isMoveLine = (e) => ["pass", "carry", "shot"].includes(e.type);
  const failed = (e) => ["incomplete", "lost"].includes(e.outcome);

  function momentTitle(mo) {
    const time = mo.category === "momentum_shift" ? `${clockText(mo.t)}–${clockText(mo.reveal_t)}` : clockText(mo.t);
    return `${time} ${TYPE_LABELS[mo.category] || mo.category}, ${teamName(mo.team)}`;
  }

  function eventWords(e, withTeam) {
    return `${e.player}${withTeam ? ` (${teamName(e.team)})` : ""} ${e.type}, ${OUTCOME_WORDS[e.outcome] || e.outcome}`;
  }

  function drawPitch(s) {
    s.append(svg("rect", { class: "turf", x: -2.5, y: 0, width: PW + 5, height: PH }));
    const line = (attrs, tag = "rect") => s.append(svg(tag, { class: "line", ...attrs }));
    line({ x: 0, y: 0, width: PW, height: PH });
    line({ x1: PW / 2, x2: PW / 2, y1: 0, y2: PH }, "line");
    line({ cx: PW / 2, cy: PH / 2, r: 9.15 }, "circle");
    for (const [x0, dir] of [[0, 1], [PW, -1]]) {
      line({ x: Math.min(x0, x0 + dir * 16.5), y: PH / 2 - 20.16, width: 16.5, height: 40.32 });
      line({ x: Math.min(x0, x0 + dir * 5.5), y: PH / 2 - 9.16, width: 5.5, height: 18.32 });
      line({ x: Math.min(x0, x0 - dir * 2), y: PH / 2 - 3.66, width: 2, height: 7.32 });
      s.append(svg("circle", { class: "spot", cx: x0 + dir * 11, cy: PH / 2, r: 0.45 }));
    }
    s.append(svg("circle", { class: "spot", cx: PW / 2, cy: PH / 2, r: 0.45 }));
  }

  function arrowHead(x1, y1, x2, y2, size) {
    const a = Math.atan2(y2 - y1, x2 - x1);
    const pt = (da) => `${x2 - size * Math.cos(a + da)},${y2 - size * Math.sin(a + da)}`;
    return `M${x2},${y2}L${pt(0.45)}L${pt(-0.45)}Z`;
  }

  // Text in pitch units, k times larger on narrow screens so it stays readable.
  const text = (cls, x, y, size, content, anchor = "middle") => {
    const t = svg("text", { class: cls, x, y, "text-anchor": anchor, style: `font-size:${size}px` });
    t.textContent = content;
    return t;
  };

  function drawMove(s, own, keyId, analyst, k) {
    const lines = svg("g");
    const marks = svg("g");
    const badges = svg("g");
    s.append(lines, marks, badges);
    const R = (analyst ? 5.2 : 4.2) * k;
    // A shot's outcome sits just above the goal it was aimed at, kept clear of the badges.
    const outcomeY = PH / 2 - 3.66 - 1.6;
    const placed = own.some((e) => e.type === "shot") ? [{ x: PW - 1, y: outcomeY - k }, { x: PW - 4 * k, y: outcomeY - k }] : [];
    const free = (x, y) => !placed.some((p) => Math.hypot(p.x - x, p.y - y) < R);
    own.forEach((e, i) => {
      const x1 = px(e.x), y1 = py(e.y), x2 = px(e.end_x), y2 = py(e.end_y);
      const arrow = isMoveLine(e) && Math.hypot(x2 - x1, y2 - y1) > 0.5;
      const shot = e.type === "shot";
      const level = xtLevel(e.xt_added);
      const color = shot ? "var(--text)" : `var(--xt-${level.key})`;
      const width = shot ? 0.9 : level.width;
      let bx = x1, by = y1 - 3;
      if (arrow) {
        if (e.event_id === keyId) {
          lines.append(svg("line", { class: "halo", x1, y1, x2, y2, "stroke-width": width + 2.4 }));
        }
        const len = Math.hypot(x2 - x1, y2 - y1);
        const head = Math.min(2.4, len / 2);
        const cut = failed(e) ? 0 : head * 0.8;
        const ex = x2 - ((x2 - x1) / len) * cut, ey = y2 - ((y2 - y1) / len) * cut;
        lines.append(svg("line", { x1, y1, x2: ex, y2: ey, stroke: color, "stroke-width": width,
          "stroke-linecap": "round", ...(e.type === "carry" ? { "stroke-dasharray": "1.6 1.2" } : {}) }));
        if (failed(e)) { // the ball did not reach its end: a cross, no arrowhead
          const c = 1.2;
          marks.append(svg("path", { d: `M${x2 - c},${y2 - c}L${x2 + c},${y2 + c}M${x2 - c},${y2 + c}L${x2 + c},${y2 - c}`,
            stroke: color, "stroke-width": 0.7, fill: "none" }));
        } else {
          marks.append(svg("path", { d: arrowHead(x1, y1, x2, y2, head), fill: color }));
        }
        if (shot) {
          marks.append(text("outcome", PW + 2.5, outcomeY, 2.6 * k, SHOT_LABELS[e.outcome] || e.outcome, "end"));
        }
        bx = x1 + (x2 - x1) * 0.45;
        by = y1 + (y2 - y1) * 0.45;
      } else {
        const d = 1.4;
        if (e.event_id === keyId) marks.append(svg("circle", { class: "halo", cx: x1, cy: y1, r: 2.6, "stroke-width": 1.6 }));
        marks.append(svg("path", { class: "won", d: `M${x1},${y1 - d}L${x1 + d},${y1}L${x1},${y1 + d}L${x1 - d},${y1}Z` }));
      }
      // Nudge the badge (and its xT label) off earlier ones, staying inside the drawing.
      const hw = (analyst ? 4.4 : 2) * k;
      const clampX = (x) => Math.min(PW + 3 - hw, Math.max(-3 + hw, x));
      const clampY = (y) => Math.min(PH - 2 * k, Math.max(2 * k, y));
      const tries = [[0, 0], [0, -R], [0, R], [-R, 0], [R, 0], [-R, -R], [-R, R], [R, -R], [R, R], [0, -2 * R], [0, 2 * R],
        [-2 * R, 0], [-2 * R, -R], [-2 * R, R]].map(([tx, ty]) => [clampX(bx + tx), clampY(by + ty)]);
      [bx, by] = tries.find(([x, y]) => free(x, y)) || tries[0];
      placed.push({ x: bx, y: by });
      badges.append(svg("circle", { class: "badge-dot", cx: bx, cy: by, r: 1.9 * k }));
      badges.append(text("badge-num", bx, by + 0.95 * k, 2.6 * k, String(i + 1)));
      if (analyst && ["pass", "carry"].includes(e.type)) {
        const below = by + 4.4 * k <= PH; // above the badge if below would leave the pitch
        badges.append(text("xt-label", bx, below ? by + 4.4 * k : by - 2.6 * k, 2.3 * k, signed(e.xt_added)));
      }
    });
  }

  function renderLegend(analyst) {
    const item = (cls, text) => {
      const s = el("span");
      s.append(el("span", { class: `ln ${cls}`, "aria-hidden": "true" }), el("span", {}, text));
      return s;
    };
    $("map-legend").replaceChildren(
      item("", "Pass"), item("dashed", "Carry"), item("shot", analyst ? "Shot (no xT)" : "Shot"),
      ...XT_LEVELS.map((l) => item(l.key, analyst ? l.range : l.words)),
      el("span", {}, "× ball not kept · ◇ won the ball"));
  }

  function renderMap() {
    if (!state.profile) return;
    const mo = state.mapId ? D.moments[state.mapId] : null;
    $("map-empty").hidden = !!mo;
    $("map-body").hidden = !mo;
    const key = mo ? `${state.profile}|${mo.id}` : "";
    if ($("pitch").dataset.key === key) return;
    $("pitch").dataset.key = key;
    $("map-moment").textContent = mo ? `· ${momentTitle(mo)}` : "";
    if (!mo) return;
    const reason = mo.map.reason;
    $("map-reason").hidden = !reason;
    $("map-reason").textContent = reason || "";
    for (const id of ["pitch", "map-legend", "map-list-h", "move-list"]) $(id).hidden = !!reason;
    $("move-others").hidden = true;
    if (reason) {
      $("pitch").replaceChildren();
      $("move-list").replaceChildren();
      return;
    }

    const analyst = profile().profile.mode === "analyst";
    const team = mo.map.team;
    const all = D.possessions[mo.map.possession_id];
    const own = all.filter((e) => e.team === team);
    const others = all.filter((e) => e.team !== team);

    const k = Math.min(1.8, Math.max(1, 560 / ($("pitch").clientWidth || 560)));
    const top = 2.5 + 3.4 * k;
    const s = svg("svg", { viewBox: `-3 ${-top} ${PW + 6} ${PH + top + 1.5}`, role: "img",
      "aria-label": `Pass map of the ${teamName(team)} move at ${clockText(mo.t)}: ${own.length} numbered actions, ` +
        "attacking left to right. The same actions are listed in words below." });
    drawPitch(s);
    s.append(svg("circle", { cx: 1.1 * k, cy: -1.8 - 1.1 * k, r: 1.1 * k, fill: `var(--${team.split("_")[1]})` }),
      text("team-label", 3 * k, -1.8, 3.2 * k, `${teamName(team)} move`, "start"),
      text("dir", PW, -1.8, 2.6 * k, "attacking →", "end"));
    drawMove(s, own, mo.map.key_event_id, analyst, k);
    $("pitch").replaceChildren(s);
    renderLegend(analyst);

    $("move-list").replaceChildren(...own.map((e) => {
      const li = el("li", e.event_id === mo.map.key_event_id ? { class: "key" } : {});
      li.append(el("span", { class: "time" }, `${clockText(e.t)} `), document.createTextNode(eventWords(e, false)));
      if (["pass", "carry"].includes(e.type)) {
        li.append(document.createTextNode(analyst ? ` · xT ${signed(e.xt_added)}`
          : ` · ${xtLevel(e.xt_added).words.toLowerCase()}`));
      }
      if (e.event_id === mo.map.key_event_id) li.append(document.createTextNode(" (this moment)"));
      return li;
    }));
    if (others.length) {
      $("move-others").hidden = false;
      $("move-others").textContent = "Not drawn, the other team's events during this move: " +
        others.map((e) => `${clockText(e.t)} ${eventWords(e, true)}`).join("; ") + ".";
    }
  }

  function markSelected() {
    for (const li of $("feed").children) {
      const on = li.dataset.id === state.mapId;
      li.classList.toggle("on-map", on);
      li.querySelector(".show-move")?.setAttribute("aria-pressed", String(on));
    }
  }

  function showMove(id) {
    state.mapId = id;
    markSelected();
    renderMap();
    $("map-status").textContent = `Pass map now shows ${momentTitle(D.moments[id])}`;
    const r = $("pass-map").getBoundingClientRect();
    if (r.top > window.innerHeight || r.bottom < 0) $("pass-map").scrollIntoView({ block: "start" });
  }

  // ------------------------------------------------------------ recap

  function renderRecap() {
    if (!state.profile) return;
    const open = state.recapOpen || state.t >= D.match.timeline.length_seconds;
    $("recap-locked").hidden = open;
    const list = $("recap");
    list.hidden = !open;
    list.setAttribute("tabindex", "-1");
    if (open && list.dataset.key !== state.profile) {
      list.dataset.key = state.profile;
      list.replaceChildren(...profile().recap.map((line) => el("li", {}, line)));
    }
  }

  // ------------------------------------------------------------ xT panel

  // The xT grid from xt_grid.json (src/xt_reference.py, also behind the README
  // image), drawn on the pitch. Analyst views show the numbers, fan views the
  // words only.
  function renderXt() {
    if (!state.profile) return;
    const g = D.xt_grid;
    const ex = g.example;
    const analyst = profile().profile.mode === "analyst";
    const k = Math.min(1.8, Math.max(1, 560 / ($("about").clientWidth || 560)));
    const key = `${analyst}|${k}`;
    if ($("xt-body").dataset.key === key) return;
    $("xt-body").dataset.key = key;
    $("xt-title").textContent = analyst ? "What is xT?" : "How is danger measured?";

    const when = clockText(timelineSeconds(ex.period, ex.minute, ex.second));
    const top = g.top_value.toFixed(2);
    const v4 = (v) => v.toFixed(4);
    const intro = analyst
      ? "xT (Expected Threat) gives every zone of the pitch a value: how likely possession there is to lead " +
        `to a goal soon. The best zones are about ${top}. It is not shot probability. A completed pass or ` +
        "carry scores the value of the zone it ends in minus the value of the zone it starts in."
      : "The pitch is split into a grid of zones. The closer a zone is to the middle of the goal, the more " +
        "dangerous it is to have the ball there. A completed pass or carry counts as more dangerous when it " +
        "moves the ball into a brighter zone.";

    const head = 2.5 + 3.4 * k;
    const s = svg("svg", { viewBox: `-3 ${-head} ${PW + 6} ${PH + head + 1.5}`, role: "img",
      "aria-labelledby": "xt-svg-t xt-svg-d" });
    const title = svg("title", { id: "xt-svg-t" });
    title.textContent = analyst ? "xT zone values" : "How dangerous each zone is";
    const desc = svg("desc", { id: "xt-svg-d" });
    desc.textContent = (analyst
      ? `Heat map of the ${g.cols} by ${g.rows} xT zone grid, attacking left to right. Values rise from ` +
        `${g.scale[0].label} in the team's own half to about ${top} in the central zones in front of goal.`
      : "Heat map of the pitch zones, attacking left to right. Zones get brighter, meaning more dangerous, " +
        "toward the middle of the goal.") + ` A line shows the ${when} pass described below.`;
    s.append(title, desc);
    drawPitch(s);
    const cw = PW / g.cols, ch = PH / g.rows;
    const stepOf = (v) => g.scale.reduce((i, st, j) => (v >= st.min ? j : i), 0);
    const cells = svg("g", { "shape-rendering": "crispEdges" });
    g.values.forEach((col, c) => col.forEach((v, r) => {
      cells.append(svg("rect", { x: c * cw, y: (g.rows - 1 - r) * ch, width: cw, height: ch,
        fill: g.scale[stepOf(v)].colour }));
    }));
    s.querySelector(".turf").after(cells); // under the pitch lines
    const bc = g.best_zones.map((z) => z[0]), br = g.best_zones.map((z) => z[1]);
    const bx = Math.min(...bc) * cw, by = (g.rows - 1 - Math.max(...br)) * ch;
    const bw = (Math.max(...bc) - Math.min(...bc) + 1) * cw, bh = (Math.max(...br) - Math.min(...br) + 1) * ch;
    s.append(svg("rect", { class: "xt-best", x: bx, y: by, width: bw, height: bh }));
    if (analyst) {
      const size = Math.min(2.4 * k, 3);
      s.append(text("xt-best-label", bx + bw / 2, by + bh / 2 - 0.4, size, "about"),
        text("xt-best-label strong", bx + bw / 2, by + bh / 2 + size, size, top));
    }
    const [x1, y1, x2, y2] = [px(ex.start[0]), py(ex.start[1]), px(ex.end[0]), py(ex.end[1])];
    s.append(svg("line", { class: "xt-ex-halo", x1, y1, x2, y2 }), svg("line", { class: "xt-ex", x1, y1, x2, y2 }),
      svg("circle", { class: "xt-ex-from", cx: x1, cy: y1, r: 1 }),
      svg("circle", { class: "xt-ex-to", cx: x2, cy: y2, r: 1 }),
      text("team-label", 0, -1.8, 3.2 * k, analyst ? "xT zone values" : "Danger by zone", "start"),
      text("dir", PW, -1.8, 2.6 * k, "attacking →", "end"));
    const pitch = el("div", { class: "pitch xt-pitch" });
    pitch.append(s);

    const swatch = (st) => {
      const sp = el("span", { class: "swatch", "aria-hidden": "true" });
      sp.style.background = st.colour;
      return sp;
    };
    const legend = el("div", { class: "legend xt-legend" });
    if (analyst) {
      for (const st of g.scale) {
        const item = el("span");
        item.append(swatch(st), document.createTextNode(st.label));
        legend.append(item);
      }
      legend.append(el("span", {}, `Outlined: the best zones, about ${top}`));
    } else {
      const ramp = el("span", { class: "xt-ramp" });
      ramp.append(el("span", {}, "Less dangerous"), ...g.scale.map(swatch), el("span", {}, "More dangerous"));
      legend.append(ramp, el("span", {}, "Outlined: the most dangerous zones"));
    }
    legend.append(el("span", {}, `Line: the ${when} pass, from the white dot to the dark dot`));

    const example = el("p");
    example.append(el("strong", {}, "Worked example. "), document.createTextNode(analyst
      ? `At ${when} ${ex.player} (${teamName(ex.team)}) passed from zone ${ex.from_zone} (value ` +
        `${v4(ex.from_value)}) to zone ${ex.to_zone} (value ${v4(ex.to_value)}). xT added: ` +
        `${v4(ex.to_value)} − ${v4(ex.from_value)} = ${ex.xt_added >= 0 ? "+" : "−"}${v4(Math.abs(ex.xt_added))}.`
      : `At ${when} ${ex.player} (${teamName(ex.team)}) passed from ${ex.from_place} to ${ex.to_place}: ` +
        `${xtLevel(ex.xt_added).words.toLowerCase()}.`));

    const parts = [el("p", {}, intro), pitch, legend, example, el("p", { class: "hint" }, g.caption)];
    if (analyst) {
      const headRow = el("tr");
      headRow.append(el("th", { scope: "col" }, "Row"), ...g.values.map((_, c) => el("th", { scope: "col" }, `c${c}`)));
      const thead = el("thead");
      thead.append(headRow);
      const tbody = el("tbody");
      for (let r = g.rows - 1; r >= 0; r--) {
        const tr = el("tr");
        const side = r === g.rows - 1 ? " (left)" : r === 0 ? " (right)" : "";
        tr.append(el("th", { scope: "row" }, `r${r}${side}`), ...g.values.map((col) => el("td", {}, v4(col[r]))));
        tbody.append(tr);
      }
      const table = el("table");
      table.append(el("caption", { class: "visually-hidden" },
        "xT zone values: columns c0 to c11 toward goal, rows from the attacker's left to right"), thead, tbody);
      const scroll = el("div", { class: "table-scroll" });
      scroll.append(table);
      const details = el("details", { class: "table-view" });
      details.append(el("summary", {}, "Show the grid as a table"), scroll);
      parts.push(details);
    }
    $("xt-body").replaceChildren(...parts);
  }

  function renderChecks() {
    const c = D.meta.checks;
    const n = Object.values(c.narrations);
    const p = Object.values(c.personalized);
    $("check-status").textContent = c.passed
      ? `When this page was built, ${n.filter(Boolean).length} of ${n.length} narrations, the match analysis and ` +
        `${p.filter(Boolean).length} of ${p.length} reader profiles passed every check as saved.`
      : "Some saved text failed its checks when this page was built.";
  }

  // ------------------------------------------------------------ start

  async function start() {
    try {
      D = await load();
    } catch (err) {
      const msg = el("p", { class: "wrap" },
        "Could not load the match data. If you opened index.html as a file, serve the web folder " +
        `instead (python -m http.server). (${err.message})`);
      document.querySelector("main").prepend(msg);
      return;
    }
    setupControls();
    setSpeed(Number(params.get("speed")) || 60);
    buildChart();
    setupProfiles();
    renderChecks();
    if (params.get("recap") === "1") state.recapOpen = true;
    seek(Number(params.get("t")) || 0);
    let resizeTimer;
    let lastWidth = $("chart").clientWidth;
    window.addEventListener("resize", () => {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(() => {
        if ($("chart").clientWidth === lastWidth) return;
        lastWidth = $("chart").clientWidth;
        buildChart();
        renderChart();
        $("pitch").dataset.key = ""; // the map's text scales with its width
        renderMap();
        renderXt();
      }, 120);
    });
  }

  start();
})();
