// Inside the Game: replays the match from web/data/ (built by src/build_site.py).
// No build step, no external services. Optional URL parameters, handy for
// screenshots: ?t=<timeline seconds>&profile=<profile key>&recap=1

(() => {
  "use strict";

  const FILES = ["match", "events", "threat", "key_moments", "profiles", "overlays", "meta"];
  const TYPE_LABELS = {
    goal: "Goal", save: "Save", big_chance_missed: "Big chance missed",
    momentum_shift: "Spell on top", biggest_threat_swing: "Threat swing",
  };
  const SPEEDS = [1, 10, 60];
  const STORE_KEY = "itg-profile";

  const $ = (id) => document.getElementById(id);
  const svgNS = "http://www.w3.org/2000/svg";
  const params = new URLSearchParams(location.search);

  const state = { t: 0, playing: false, speed: 60, profile: null, recapOpen: false, lastFrame: 0, shown: -1 };
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
    for (const l of D.meta.languages) {
      const label = el("label", { class: "choice" });
      const input = el("input", { type: "radio", name: "language", value: l.code });
      if (l.code === "en") input.checked = true;
      if (!l.available) input.disabled = true;
      const span = el("span", {});
      const name = el("span", l.code === "ar" ? { lang: "ar", dir: "rtl" } : {}, l.name);
      span.append(name);
      if (!l.available) span.append(el("span", { class: "soon" }, "coming soon"));
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
    state.shown = -1;
    renderChart();
    renderFeed();
    renderRecap();
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
    state.shown = revealed.length;
    const favourite = Object.fromEntries(profile().moments.map((x) => [x.id, x.involves_favourite]));
    const fav = profile().profile.favourite_team;
    $("feed-empty").hidden = revealed.length > 0;
    $("feed").replaceChildren(...revealed.slice().reverse().map((o, i) => {
      const mo = D.moments[o.moment_id];
      const li = el("li", { class: `moment ${mo.team}${i === 0 ? " latest" : ""}` });
      const meta = el("div", { class: "moment-meta" });
      const time = mo.category === "momentum_shift" ? `${clockText(mo.t)}–${clockText(mo.reveal_t)}` : clockText(mo.t);
      meta.append(el("span", { class: "time" }, time),
        el("span", { class: `badge ${mo.category === "goal" ? "goal" : ""}` }, TYPE_LABELS[mo.category] || mo.category),
        el("span", {}, teamName(mo.team)));
      if (fav !== "none" && favourite[o.moment_id]) meta.append(el("span", {}, `★ involves ${teamName(fav)}`));
      li.append(meta, el("h3", {}, displayHeadline(o.headline)));
      for (const line of o.lines) li.append(el("p", {}, line));
      return li;
    }));
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
      }, 120);
    });
  }

  start();
})();
