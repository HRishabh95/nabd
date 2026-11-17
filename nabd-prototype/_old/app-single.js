// Nabd — one view: the Model room. Three model families from data in to governance, with a live network
// analysis of this week's Aani payments inside the fraud lane.
(() => {
  const D = window.NABD, C = window.NabdChart, L = window.NETLAB;
  const $ = (s, r = document) => r.querySelector(s), $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const MINUS = '−';
  const signed = (v, d = 1) => (v > 0.0001 ? '+' : v < -0.0001 ? MINUS : '') + Math.abs(v).toFixed(d);
  const int = (v) => new Intl.NumberFormat('en').format(v);
  const cssv = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
  const toast = (msg) => { const t = $('#toast'); t.textContent = msg; t.classList.add('show'); clearTimeout(t._h); t._h = setTimeout(() => t.classList.remove('show'), 3800); };
  const store = { get: (k) => { try { return localStorage.getItem(k); } catch { return null; } }, set: (k, v) => { try { localStorage.setItem(k, v); } catch {} } };

  // ---------- role and information barrier ----------
  let role = D.roles.find((r) => r.id === store.get('nabd-role')) || D.roles[0];
  const roleSel = $('#role');
  roleSel.innerHTML = D.roles.map((r) => `<option value="${r.id}">${r.name}</option>`).join('');
  roleSel.value = role.id;
  roleSel.addEventListener('change', () => { role = D.roles.find((r) => r.id === roleSel.value); store.set('nabd-role', role.id); render(); toast(`Viewing as ${role.name}. Only what this role may see is shown.`); });

  const runNo = 4812, result = D.scenario({ days: 30, brent: 95, response: 'none', seed: runNo });
  const top = L.comms[0];

  // ======================= THE MODEL ROOM =======================
  let lens = 'all';
  function render() {
    const inv = D.inventory;
    $('#inv-strip').innerHTML = [
      ['Models in production', inv.production, 'across 3 model families'],
      ['Need attention', inv.attention, 'data coverage and a new scam pattern'],
      ['Challengers ready', inv.challengers, 'awaiting validation to promote'],
      ['Validations overdue', inv.overdue, 'next due 28 Apr 2027'],
      ['Firm records sent out today', D.usage.recordsOut, 'everything runs on premise'],
    ].map(([k, v, s]) => `<div><dt>${k}</dt><dd class="num">${v}</dd><span>${s}</span></div>`).join('');
    const cols = ['Data in', 'Models', 'What it says today', 'How it is performing', 'Governance'];
    const tone = (t) => ({ good: 'better', warn: 'warnc' }[t] || '');
    const lanes = D.lanes.map((l) => {
      const data = `<ul class="mini-feeds">${l.data.map((d) => `<li><i class="sd ${d.ok ? 'ok' : 'bad'}" aria-label="${d.ok ? 'current' : 'below threshold'}"></i><span class="nm">${d.name}${d.isNew ? ' <em class="newtag">New input</em>' : ''}</span><span class="vl num">${d.vol}</span></li>`).join('')}</ul>`;
      let model = `<div class="mdl"><span class="mdl-k">Champion</span><span class="mdl-n">${l.champion.name}</span><span class="mdl-s">${l.champion.note}</span></div><div class="mdl chall"><span class="mdl-k">${l.id === 'res' ? 'Also running' : 'Challenger'}</span><span class="mdl-n">${l.challenger.name}</span><span class="mdl-s">${l.challenger.note}</span></div>`;
      if (l.champErr) model += `<div class="chart" id="cc-gdp"></div><p class="cell-note">Challenger lower error in <strong>${l.challErr.filter((v, i) => v < l.champErr[i]).length} of the last 12 weeks</strong>.</p><button class="btn small" type="button" data-act="promote">Request validation to promote</button>`;
      if (l.tradeoff) { const t = l.tradeoff; model += `<div class="trade">${[['Rings caught', 'recall'], ['Alerts that are real', 'precision']].map(([k, m]) => `<div class="tr-row"><span>${k}</span><span class="hb"><i style="width:${t.champ[m] * 100}%"></i></span><b class="num">${Math.round(t.champ[m] * 100)}%</b></div><div class="tr-row dim"><span>Challenger</span><span class="hb"><i style="width:${t.chall[m] * 100}%"></i></span><b class="num">${Math.round(t.chall[m] * 100)}%</b></div>`).join('')}</div><p class="cell-note">Challenger catches about 6 more rings a quarter but sends analysts 22% more alerts.</p><button class="btn small" type="button" data-act="shadow">Run challenger in shadow mode</button>`; }
      let out = '';
      if (l.id === 'gdp') out = `<span class="out-k">Non-oil growth, Q4 2026</span><span class="out-v num">${D.nowcast.at(-1).toFixed(1)}%</span><span class="out-s"><span class="worse">${signed(D.weekChange, 2)} pp</span> this week · 70% range ${(D.nowcast.at(-1) - D.half70.at(-1)).toFixed(1)} to ${(D.nowcast.at(-1) + D.half70.at(-1)).toFixed(1)}</span><div class="chart" id="out-gdp"></div><p class="cell-note">News coverage of shipping disruption pulled the forecast down 0.10 pp this week.</p>`;
      if (l.id === 'fraud') out = `<span class="out-k">Money trails flagged this week</span><span class="out-v num">${L.flagged.length}</span><span class="out-s">from ${int(L.stats.transfers)} transfers between ${int(L.stats.accounts)} accounts</span><ul class="out-list">${L.comms.map((c) => `<li><span>${c.id}: ${c.size} accounts, ${c.banks} banks</span><span class="num">${c.score.toFixed(2)}</span></li>`).join('')}</ul><p class="cell-note">The analysis below shows how they were found.</p>`;
      if (l.id === 'res') { const f = result.days / 30, tot = D.allocation.reduce((a, x) => a + (x.w * x.hormuz30 * f) / 100, 0); out = `<span class="out-k">Notional portfolio under scenario run ${runNo}</span><span class="out-v num ${tot < 0 ? 'worse' : ''}">${signed(tot, 2)}%</span><span class="out-s">Hormuz ${result.days} days · equities ${signed(-6.1 * f)}%, gold ${signed(5.8 * f)}%</span><div class="budget"><span class="meta">Active risk budget used</span><span class="hb big-hb"><i style="width:62%"></i></span><span class="num">62%</span></div><p class="cell-note">Emerging-market debt mandate: 2 due-diligence findings need answers.</p>`; }
      const perf = `<ul class="perf-list">${l.perf.map((p) => `<li><span class="pk">${p.k}</span><span class="pv num ${tone(p.tone)}">${p.v}</span><span class="ps">${p.s}</span></li>`).join('')}</ul>`;
      const g = l.gov;
      const gov = `<span class="pill">${g.tier}</span><dl class="gov-dl"><dt>Validated</dt><dd class="num">${g.validated}</dd><dt>Next validation</dt><dd class="num">${g.next}</dd><dt>Approved by</dt><dd>${g.approver}</dd></dl><ul class="checks">${g.checks.map((c) => `<li>${c}</li>`).join('')}</ul>`;
      return `<section class="lane" aria-labelledby="lane-${l.id}">
        <header class="lane-head"><h2 id="lane-${l.id}">${l.title}</h2><span class="pill ${l.tone}">${l.status}</span><span class="why">${l.why}</span><span class="owner">${l.owner}</span></header>
        <svg class="lane-flow" viewBox="0 0 1000 4" preserveAspectRatio="none" aria-hidden="true"><line x1="0" y1="2" x2="1000" y2="2" class="flow-line"/></svg>
        <div class="lane-row">
          <div class="cell" data-col="data">${data}</div><div class="cell" data-col="model">${model}</div><div class="cell" data-col="out">${out}</div><div class="cell" data-col="perf">${perf}</div><div class="cell" data-col="gov">${gov}</div>
        </div>
        ${l.id === 'fraud' ? '<div class="netlab" id="netlab"></div>' : ''}
      </section>`;
    }).join('');
    const grid = $('#room-grid'); grid.dataset.lens = lens;
    grid.innerHTML = `<div class="room-cols">${cols.map((c, i) => `<span data-col="${['data', 'model', 'out', 'perf', 'gov'][i]}">${c}</span>`).join('')}</div>${lanes}`;
    const g0 = D.lanes[0];
    C.render($('#cc-gdp'), {
      height: 110, padR: 4, xLabels: g0.champErr.map((_, i) => (i === 11 ? 'This week' : `${12 - i} wk`)), yTicks: [0.15, 0.2, 0.25, 0.3], yFormat: (v) => v.toFixed(2), label: 'Champion and challenger error, last 12 weeks',
      series: [{ values: g0.champErr, color: '#8a9098', width: 1.75 }, { values: g0.challErr, color: cssv('--bronze-ink'), width: 2.25 }],
      tip: (i) => `Champion ${g0.champErr[i].toFixed(2)} · challenger ${g0.challErr[i].toFixed(2)}`,
    });
    const labels = [D.hist.at(-1).label, ...D.fcst.map((f) => f.label)], v = [D.hist.at(-1).value, ...D.fcst.map((f) => f.value)];
    const b = (k, sg) => v.map((x, i) => (i === 0 ? x : x + sg * D.fcst[i - 1][k]));
    C.render($('#out-gdp'), {
      height: 110, padR: 4, xLabels: labels.map((l) => l.replace(' 20', ' ’')), yTicks: [0, 3, 6], yFormat: (x) => `${x}%`, label: 'Four-quarter forecast fan',
      bands: [{ lo: b('h90', -1), hi: b('h90', 1), color: cssv('--bronze-1') }, { lo: b('h70', -1), hi: b('h70', 1), color: cssv('--bronze-2') }],
      series: [{ values: v, color: cssv('--bronze-ink'), width: 2 }],
    });
    $$('#room-grid [data-act]').forEach((btn) => btn.addEventListener('click', () => toast(btn.dataset.act === 'promote' ? 'Validation request sent to Model Validation for Ensemble v3.3. The champion stays live until sign-off.' : 'Graph model v2.5 now scores in shadow mode. Its alerts are logged for comparison and not sent to banks.')));
    netlab();
  }
  $$('#lens button').forEach((b) => b.addEventListener('click', () => { lens = b.dataset.lens; $$('#lens button').forEach((x) => x.setAttribute('aria-pressed', x === b)); $('#room-grid').dataset.lens = lens; }));
  $('#board-btn').addEventListener('click', () => toast('Board report drafted: model inventory, validation status, monitoring breaches and challengers, every figure cited. Awaits the CRO’s review.'));

  // ======================= NETWORK ANALYSIS (inside the fraud lane) =======================
  let step = 4, bankOnly = false, playTimer = null;
  const STEPS = [
    { n: 1, t: 'Payment network' }, { n: 2, t: 'Communities' }, { n: 3, t: 'Fast money trails' }, { n: 4, t: 'Risk-scored rings' },
  ];
  const TONES = ['#5d6b78', '#7d8a96', '#4c5a66', '#98a2ac', '#6b7782', '#8794a0'];
  function netlab() {
    const host = $('#netlab'); if (!host) return;
    if (!role.fraud) {
      host.innerHTML = `<div class="net-head"><h3>Network analysis of this week’s Aani payments</h3></div><div class="restricted"><span class="lock"></span><span><strong>Restricted for ${role.name}.</strong> Account-level network analysis is visible to Payment Systems and the Governor’s Office only.</span></div>`;
      return;
    }
    host.innerHTML = `
      <div class="net-head">
        <div><h3>Network analysis of this week’s Aani payments</h3><p class="meta">${int(L.stats.accounts)} accounts at 6 banks, ${int(L.stats.transfers)} transfers. Every step below is computed in the browser on this synthetic week.</p></div>
        <div class="net-ctrl">
          <label class="chk"><input type="checkbox" id="bank-only"${bankOnly ? ' checked' : ''}> Show only what Bank C sees</label>
          <button class="btn small" type="button" id="net-play">Replay the analysis</button>
        </div>
      </div>
      <ol class="stepper" id="stepper">${STEPS.map((s) => `<li><button type="button" data-step="${s.n}" aria-pressed="${s.n === step}"><b>${s.n}</b>${s.t}</button></li>`).join('')}</ol>
      <div class="net-body">
        <div class="net-canvas" id="net-canvas" role="img" aria-label="Payment network of this week"></div>
        <aside class="net-side" id="net-side"></aside>
      </div>`;
    $$('#stepper button').forEach((b) => b.addEventListener('click', () => { stopPlay(); step = +b.dataset.step; drawNet(); }));
    $('#bank-only').addEventListener('change', (e) => { bankOnly = e.target.checked; drawNet(); });
    $('#net-play').addEventListener('click', () => { stopPlay(); step = 1; drawNet(); playTimer = setInterval(() => { if (step >= 4) return stopPlay(); step++; drawNet(); }, 2200); });
    buildNet(); drawNet();
  }
  function stopPlay() { clearInterval(playTimer); playTimer = null; }
  let nodeEls = [], edgeEls = [], labelEls = [];
  function buildNet() {
    const host = $('#net-canvas'); host.innerHTML = '';
    const s = C.el('svg', { viewBox: `0 0 ${L.W} ${L.H}` }, host);
    edgeEls = L.edges.map((e) => C.el('line', { x1: L.nodes[e.s].x, y1: L.nodes[e.s].y, x2: L.nodes[e.t].x, y2: L.nodes[e.t].y, 'stroke-width': 1 }, s));
    nodeEls = L.nodes.map((n) => { const c = C.el('circle', { cx: n.x, cy: n.y, r: 3 }, s); C.el('title', {}, c).textContent = `${n.kind === 'abroad' ? 'Outward remittances' : `${L.BANKS[n.bank]}, account ${n.age} days old`} · passes on ${Math.round(n.flow * 100)}% · ${n.trail || 'no fast trail'}`; return c; });
    const abroad = L.nodes.find((n) => n.kind === 'abroad');
    labelEls = [C.el('text', { x: abroad.x + 10, y: abroad.y + 4, 'font-size': 13, 'font-weight': 700, 'font-family': cssv('--font'), fill: cssv('--ink') }, s)];
    labelEls[0].textContent = 'Sent abroad';
  }
  function drawNet() {
    $$('#stepper button').forEach((b) => b.setAttribute('aria-pressed', +b.dataset.step === step));
    const red = cssv('--red'), bronze = cssv('--bronze'), amber = cssv('--amber');
    const inTrail = (n) => n.trail && L.commOf.get(n.trail).score >= 0.7;
    const sourcesOf = new Set(L.flagged.flatMap((c) => c.sources));
    const seen = (n) => !bankOnly || n.bank === 2 || n.kind === 'abroad';
    L.nodes.forEach((n, i) => {
      const el = nodeEls[i];
      let fill = '#9aa1a9', r = 2.6, op = 1, stroke = 'none';
      if (step === 2) fill = TONES[n.comm % TONES.length];
      if (step === 3) { const f = n.flow; fill = f >= 0.7 ? bronze : f > 0.3 ? cssv('--bronze-3') : '#c3c8ce'; r = f >= 0.7 ? 3.6 : 2.4; }
      if (step === 4) {
        if (inTrail(n)) { const c = L.commOf.get(n.trail); fill = c.rank === 1 ? red : amber; r = 3 + n.pr * 9; }
        else if (sourcesOf.has(n.id)) { fill = '#fff'; stroke = red; r = 3.4; }
        else { fill = '#c9ced4'; op = 0.55; }
      }
      if (n.kind === 'abroad') { fill = cssv('--ink'); r = 8; }
      if (!seen(n)) op = 0.06;
      el.setAttribute('fill', fill); el.setAttribute('r', r.toFixed(1)); el.setAttribute('opacity', op); el.setAttribute('stroke', stroke); el.setAttribute('stroke-width', stroke === 'none' ? 0 : 1.6);
    });
    L.edges.forEach((e, k) => {
      const el = edgeEls[k], a = L.nodes[e.s], b = L.nodes[e.t];
      let col = '#dde1e5', op = 0.8, w = 1, cls = '';
      if (step === 2) { col = a.comm === b.comm ? TONES[a.comm % TONES.length] : '#e6e9ec'; op = a.comm === b.comm ? 0.45 : 0.6; }
      if (step === 3) { if (L.fastEdge[k]) { col = bronze; w = 1.6; op = 0.95; cls = 'flow'; } else { col = '#e6e9ec'; op = 0.5; } }
      if (step === 4) {
        const hot = (inTrail(a) || sourcesOf.has(a.id)) && (inTrail(b) || b.kind === 'abroad') && (L.fastEdge[k] || sourcesOf.has(a.id));
        if (hot) { col = inTrail(a) && L.commOf.get(a.trail).rank !== 1 ? amber : red; w = 1.6; op = 0.9; cls = 'flow'; } else { col = '#e6e9ec'; op = 0.35; }
      }
      if (!seen(a) && !seen(b)) op = 0.03; else if (!seen(a) || !seen(b)) op = Math.min(op, 0.25);
      el.setAttribute('stroke', col); el.setAttribute('stroke-width', w); el.setAttribute('opacity', op); el.setAttribute('class', cls);
    });
    labelEls[0].setAttribute('opacity', step >= 3 ? 1 : 0);
    side();
  }
  function side() {
    const host = $('#net-side');
    const bankCInTop = top.members.filter((id) => L.nodes[id].bank === 2).length;
    const notes = {
      1: `<p class="net-lede">${int(L.stats.accounts)} accounts at six banks made ${int(L.stats.transfers)} transfers on Aani this week. Each dot is an account, each line a transfer. Nothing stands out yet.</p>`,
      2: `<p class="net-lede"><strong>Community detection</strong> (weighted label propagation) groups accounts that pay each other into <strong>${L.stats.communities} communities</strong>: payroll, merchants, households.</p><p class="net-note">The mule ring does not stand out here. Its layers look like ordinary chains of payments, which is why a single rule or a single bank misses it.</p>`,
      3: `<p class="net-lede"><strong>Money-trail tracing</strong> follows transfers that an account passes on within an hour, when it forwards at least 70% of what it received. It finds <strong>${L.comms.length} fast money trails</strong>.</p><p class="net-note">Dot colour shows how much of its incoming money each account passes straight on.</p>`,
      4: `<p class="net-lede">Each trail is scored on five signals, and <strong>PageRank on money flows</strong> sizes accounts by how much money ends up with them. ${top.id} scores <strong>${top.score.toFixed(2)}</strong>.</p>`,
    };
    const table = `<table class="trail-table"><thead><tr><th>Trail</th><th class="r">Accounts</th><th class="r">Banks</th><th class="r">Held</th><th class="r">Score</th></tr></thead><tbody>${L.comms.map((c) => `<tr><td><i class="sw-dot" style="background:${c.rank === 1 ? cssv('--red') : cssv('--amber')}"></i>${c.id}</td><td class="r num">${c.size}</td><td class="r num">${c.banks}</td><td class="r num">${Math.round(c.holdMed)} min</td><td class="r num strong">${c.score.toFixed(2)}</td></tr>`).join('')}</tbody></table>`;
    const pmax = Math.max(...Object.values(top.parts));
    const explain = `<h4>Why ${top.id} scores ${top.score.toFixed(2)}</h4><ul class="explain">${Object.entries(top.parts).map(([k, v]) => `<li><span>${k}</span><span class="hb"><i style="width:${(v / pmax) * 100}%"></i></span><b class="num">+${v.toFixed(2)}</b></li>`).join('')}</ul><p class="net-note">${top.size} accounts across ${top.banks} banks, money held a median ${Math.round(top.holdMed)} minutes, ${Math.round(top.youngShare * 100)}% of accounts under 90 days old, fed by ${top.sources.length} victims, ending abroad.</p><div class="net-actions"><button class="btn primary small" type="button" data-net="case">Open a case</button><button class="btn small" type="button" data-net="alert">Alert the ${top.banks} banks</button></div>`;
    const bankNote = bankOnly ? `<p class="bank-note">Bank C sees only <strong>${bankCInTop} of the ${top.size}</strong> accounts in ${top.id}. To Bank C they look like ordinary customers paying customers at other banks.</p>` : '';
    host.innerHTML = notes[step] + bankNote + (step >= 3 ? table : '') + (step === 4 ? explain : '');
    $$('#net-side [data-net]').forEach((b) => b.addEventListener('click', () => toast(b.dataset.net === 'case' ? `Case opened for ${top.id}: ${top.size} accounts, ${top.banks} banks. Logged for the Anti-Fraud Operations Centre.` : `Alert drafted to ${top.banks} banks for ${top.size} accounts. Awaits analyst sign-off before it is sent.`)));
  }

  let rz; window.addEventListener('resize', () => { clearTimeout(rz); rz = setTimeout(render, 200); });
  (document.fonts ? document.fonts.ready : Promise.resolve()).then(render);
})();
