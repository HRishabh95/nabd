// Nabd — four pages in Apple HIG style: Overview, Forecasting, Fraud network, Investment.
(() => {
  const D = window.NABD, C = window.NabdChart, L = window.NETLAB;
  const $ = (s, r = document) => r.querySelector(s), $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const MINUS = '−';
  const signed = (v, d = 1) => (v > 0.0001 ? '+' : v < -0.0001 ? MINUS : '') + Math.abs(v).toFixed(d);
  const int = (v) => new Intl.NumberFormat('en').format(v);
  const cssv = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
  const toast = (msg) => { const t = $('#toast'); t.textContent = msg; t.classList.add('show'); clearTimeout(t._h); t._h = setTimeout(() => t.classList.remove('show'), 3800); };
  document.addEventListener('click', (e) => { const b = e.target.closest('[data-toast]'); if (b) toast(b.dataset.toast); });
  document.addEventListener('click', (e) => { if (e.target.closest('[data-board]')) toast('Board report drafted: model inventory, validation status, monitoring breaches and challengers, every figure cited.'); });

  const H = (sel, d) => Math.max(90, ($(sel).clientHeight || d) - 2);
  const runNo = 4812, result = D.scenario({ days: 30, brent: 95, response: 'none', seed: runNo });
  let R = L.run, top = R.comms[0];  // the current detection run; re-run from the Settings tab
  const news = [
    { t: 'Shipping and the Strait of Hormuz', d: '612 articles · coverage up 3.4×', pp: -0.08 },
    { t: 'Construction tenders and delays', d: '204 articles', pp: -0.03 },
    { t: 'Tourism and hotel bookings', d: '318 articles', pp: 0.02 },
    { t: 'Property launches', d: '149 articles', pp: 0.01 },
    { t: 'Oil prices and OPEC+', d: '421 articles · already in the oil input', pp: 0.0 },
  ];
  const newsTotal = +news.reduce((a, n) => a + n.pp, 0).toFixed(2);
  console.assert(newsTotal === -0.08, 'news effect', newsTotal);

  // ======================= OVERVIEW =======================
  function overview() {
    const inv = D.inventory;
    $('#ov-metrics').innerHTML = [
      ['Models in production', inv.production, '3 model families'], ['Need attention', inv.attention, 'data coverage, new scam pattern'],
      ['Challengers ready', inv.challengers, 'awaiting validation'], ['Validations overdue', inv.overdue, 'next due 28 Apr 2027'], ['Records sent out', D.usage.recordsOut, 'everything on premise'],
    ].map(([k, v, s]) => `<div class="metric"><dt>${k}</dt><dd class="num">${v}</dd><span>${s}</span></div>`).join('');
    const tot = D.allocation.reduce((a, x) => a + (x.w * x.hormuz30) / 100, 0);
    const fam = [
      { page: 'forecasting', title: 'GDP nowcast and forecast', owner: 'Economic Research', tone: 'orange', status: 'Attention', stages: [['Data in', '6 sources, news added'], ['Model', 'Ensemble v3.2'], ['Says today', `${D.nowcast.at(-1).toFixed(1)}% Q4, ${signed(D.weekChange, 2)} pp`], ['Performing', '0.21 pp error', false], ['Governance', 'Validated 28 Oct']], alertStage: 0, foot: 'Card data coverage 81%, below its 90% threshold' },
      { page: 'fraud', title: 'Fraud detection for the Anti-Fraud Operations Centre', owner: 'Payment Systems', tone: 'orange', status: 'Attention', stages: [['Data in', '1.84 m payments today'], ['Model', 'Graph model v2.4'], ['Says today', `${L.run.flagged.length} money trails flagged`], ['Performing', '78% of rings caught'], ['Governance', 'Validated 3 Nov']], alertStage: 3, foot: 'Impersonation scams up 40%, beyond the training range' },
      { page: 'investment', title: 'Reserves and investment', owner: 'Reserve Management, Risk as second line', tone: 'green', status: 'Normal', stages: [['Data in', '4,200 instruments'], ['Model', 'Scenario risk v1.8'], ['Says today', `${signed(tot, 2)}% under run ${runNo}`], ['Performing', '2 of 4 backtest limit'], ['Governance', 'Validated 14 Oct']], alertStage: -1, foot: 'Within the active risk budget: 62% used' },
    ];
    $('#ov-families').innerHTML = fam.map((f) => `<a class="card family" href="#${f.page}"><div class="family-top"><h2>${f.title}</h2><span class="pill ${f.tone}">${f.status}</span><span class="spacer" style="flex:1"></span><span class="link">Open</span></div><dl class="flowline">${f.stages.map(([k, v], i) => `<div class="stage${i === f.alertStage ? ' alert' : ''}"><dt>${k}</dt><dd>${v}</dd></div>`).join('')}</dl><div class="family-foot"><span class="sub">${f.owner}</span><span class="sub ${f.tone === 'orange' ? 'warn' : ''}">${f.foot}</span></div></a>`).join('');
    $('#ov-attn').innerHTML = [
      ['Card data below threshold', 'Nowcast runs on 81% of card volume; 2 acquirers a day late', 'Check feed', '#forecasting'],
      ['New scam pattern rising', 'Impersonation scams +40% month on month; challenger model catches more', 'Review', '#fraud'],
      ['Challenger ready: Ensemble v3.3', 'Adds a news model; lower error in 11 of 12 weeks', 'Validate', '#forecasting'],
    ].map(([t, d, b, h]) => `<li><i></i><span class="t">${t}</span><span class="d">${d}</span><a class="btn small" href="${h}">${b}</a></li>`).join('');
    $('#ov-cal').innerHTML = [['Mule-ring graph model', 'Payment Systems', '3 May 2027'], ['GDP ensemble', 'Economic Research', '28 Apr 2027'], ['Scenario risk model', 'Reserve Management', '14 Oct 2027']]
      .map(([t, d, v]) => `<li><span class="t">${t}</span><span class="d">${d}</span><span class="v num">${v}</span></li>`).join('');
  }

  // ======================= FORECASTING =======================
  let fcN = 46;
  // the forecasting models a user can pick; each has its own weekly nowcast, error and four-quarter path (synthetic)
  const FMODELS = [
    { id: 'ens', name: 'Ensemble v3.2', role: 'Champion', note: 'Weighted combination of four models', h1: 0.21, h4: 0.66, bias: 0, amp: 0, fq: [0, 0, 0, 0] },
    { id: 'news', name: 'Ensemble v3.3 with news', role: 'Challenger', note: 'Adds a news model on 1.2 m Arabic and English articles', h1: 0.19, h4: 0.61, bias: -0.03, amp: 0.04, fq: [-0.1, -0.2, -0.2, -0.1], lead: true },
    { id: 'gbt', name: 'Gradient-boosted trees', role: 'Machine learning', note: '214 payment features, retrained nightly', h1: 0.24, h4: 0.71, bias: 0.05, amp: 0.12, fq: [0.1, 0.2, 0.1, 0.2] },
    { id: 'midas', name: 'Mixed-frequency regression', role: 'Econometric', note: 'Daily payments mapped to quarterly GDP', h1: 0.27, h4: 0.78, bias: -0.06, amp: 0.09, fq: [-0.1, 0.0, -0.3, -0.2] },
    { id: 'dfm', name: 'Dynamic factor model', role: 'Statistical', note: 'Common factors across 38 series', h1: 0.29, h4: 0.74, bias: 0.08, amp: 0.07, fq: [0.2, 0.1, 0.2, 0.3] },
    { id: 'tnn', name: 'Temporal neural network', role: 'Deep learning', note: 'Sequence model on daily flows', h1: 0.31, h4: 0.83, bias: -0.02, amp: 0.16, fq: [0.0, 0.3, 0.4, 0.2] },
  ];
  FMODELS.forEach((m, k) => {
    m.values = D.nowcast.map((v, i) => {
      if (m.lead && i >= 7 && i <= 12) return D.nowcast[Math.min(45, i + 1)]; // the news model sees the March turn a week earlier
      return +(v + m.bias + m.amp * Math.sin(i / (3 + k) + k)).toFixed(2);
    });
    m.scale = m.h1 / 0.21;
  });
  let fcModel = 'ens', fcCompare = false;
  function forecasting() {
    const m = FMODELS.find((x) => x.id === fcModel), now = m.values.at(-1);
    $('#fc-lede').innerHTML = `Pick a model to see its nowcast and four-quarter forecast, or compare all six. The ensemble is ${Math.round((1 - D.ensemble.h1 / D.benchmarks[0].h1) * 100)}% more accurate one quarter ahead than the standard PMI and oil model.`;
    $('#fc-model').innerHTML = FMODELS.map((x) => `<option value="${x.id}"${x.id === fcModel ? ' selected' : ''}>${x.name}</option>`).join('');
    $('#fc-compare').checked = fcCompare;
    $('#fc-now').textContent = `${now.toFixed(1)}%`;
    $('#fc-now-sub').innerHTML = `${m.name} · <span class="worse">${signed(now - m.values.at(-2), 2)} pp</span> this week · error ${m.h1.toFixed(2)} pp`;
    const from = D.nowcast.length - fcN, sl = (a) => a.slice(from);
    const h70 = D.half70.map((h) => h * m.scale), h90 = D.half90.map((h) => h * m.scale);
    const others = fcCompare ? FMODELS.filter((x) => x.id !== fcModel).map((x) => ({ values: sl(x.values), color: '#c7c7cc', width: 1.25 })) : [];
    C.render($('#fc-chart'), {
      height: H('#fc-chart', 260), xLabels: sl(D.weeks).map(D.fmtShort), yTicks: [0, 2, 4, 6, 8], yFormat: (v) => `${v}%`, label: `Weekly non-oil nowcast, ${m.name}`,
      bands: fcCompare ? [] : [{ lo: sl(m.values.map((v, i) => v - h90[i])), hi: sl(m.values.map((v, i) => v + h90[i])), color: cssv('--bronze-1') }, { lo: sl(m.values.map((v, i) => v - h70[i])), hi: sl(m.values.map((v, i) => v + h70[i])), color: cssv('--bronze-2') }],
      series: [...others, { values: sl(m.values), color: cssv('--tint-ink'), width: 2.5, cls: 'draw' }],
      points: [{ at: fcN - 1, value: now, color: cssv('--tint-ink'), r: 5 }],
      tip: (i) => fcCompare ? FMODELS.map((x) => `${x.name.split(' ')[0]} ${x.values[from + i].toFixed(1)}`).join(' · ') : `Week of ${D.fmtShort(D.weeks[from + i])}: ${m.values[from + i].toFixed(1)}%`,
    });
    const g = D.lanes[0];
    $('#fc-models').innerHTML = `<div class="mdl-row"><span class="mdl-k">Champion</span><span class="mdl-n">${g.champion.name}</span><span class="mdl-s">${g.champion.note}</span><span class="mdl-v num">${g.champErr.at(-1).toFixed(2)}</span></div><div class="mdl-row chall"><span class="mdl-k">Challenger</span><span class="mdl-n">${g.challenger.name}</span><span class="mdl-s">${g.challenger.note}</span><span class="mdl-v num">${g.challErr.at(-1).toFixed(2)}</span></div>`;
    $('#fc-cc-note').innerHTML = `Lower error in <strong>${g.challErr.filter((v, i) => v < g.champErr[i]).length} of the last 12 weeks</strong>.`;
    C.render($('#fc-cc'), {
      height: H('#fc-cc', 120), padR: 4, xLabels: g.champErr.map((_, i) => (i === 11 ? 'Now' : `${12 - i}w`)), yTicks: [0.15, 0.2, 0.25, 0.3], yFormat: (v) => v.toFixed(2), label: 'Champion and challenger error',
      series: [{ values: g.champErr, color: '#a1a1a6', width: 1.75 }, { values: g.challErr, color: cssv('--tint-ink'), width: 2.25 }],
      tip: (i) => `Champion ${g.champErr[i].toFixed(2)} · challenger ${g.challErr[i].toFixed(2)}`,
    });
    const nm = Math.max(...news.map((n) => Math.abs(n.pp)));
    $('#fc-topics').innerHTML = news.map((n) => `<li><span><span class="t">${n.t}</span><span class="d">${n.d}</span></span><span class="dbar">${n.pp ? `<i class="${n.pp < 0 ? 'neg' : 'pos'}" style="width:${(Math.abs(n.pp) / nm) * 50}%"></i>` : ''}</span><b class="num ${n.pp < 0 ? 'worse' : n.pp > 0 ? 'better' : ''}">${n.pp ? signed(n.pp, 2) : '0.00'}</b></li>`).join('')
      + `<li><span class="t">Net effect of news this week</span><span></span><b class="num worse">${signed(newsTotal, 2)}</b></li>`;
    const labels = [...D.hist.map((h) => h.label), ...D.fcst.map((f) => f.label)], nh = D.hist.length, last = D.hist.at(-1).value;
    const fv = D.fcst.map((f, i) => +(f.value + m.fq[i]).toFixed(1));
    const val = labels.map((_, i) => (i < nh ? D.hist[i].value : fv[i - nh]));
    const band = (k, sg) => labels.map((_, i) => (i < nh - 1 ? val[i] : i === nh - 1 ? last : val[i] + sg * D.fcst[i - nh][k] * m.scale));
    $('#fc-strip').innerHTML = D.fcst.map((f, i) => `<div><span>${f.label}</span><strong class="num">${fv[i].toFixed(1)}%</strong><span>70%: ${(fv[i] - f.h70 * m.scale).toFixed(1)} to ${(fv[i] + f.h70 * m.scale).toFixed(1)}</span></div>`).join('');
    C.render($('#fc-fan'), {
      height: H('#fc-fan', 200), xLabels: labels.map((l) => l.replace(' 20', ' ’')), yTicks: [0, 2, 4, 6, 8], yFormat: (v) => `${v}%`, label: `History and four-quarter forecast, ${m.name}`,
      bands: [{ lo: band('h90', -1), hi: band('h90', 1), color: cssv('--bronze-1') }, { lo: band('h70', -1), hi: band('h70', 1), color: cssv('--bronze-2') }],
      series: [{ values: val.map((v, i) => (i < nh ? v : null)), color: '#8e8e93', width: 2 }, { values: val.map((v, i) => (i >= nh - 1 ? (i === nh - 1 ? last : v) : null)), color: cssv('--tint-ink'), width: 2.5, dash: '6 4' }],
      markers: [{ at: nh - 1, label: 'Forecast from here' }],
      tip: (i) => `${labels[i]}: ${val[i].toFixed(1)}%${i >= nh ? ` forecast, ${m.name}` : ''}`,
    });
    $('#fc-lb').innerHTML = FMODELS.map((x) => `<tr class="${x.id === fcModel ? 'lead' : ''} pick" data-model="${x.id}"><td><strong>${x.name}</strong><span class="d">${x.role} · ${x.note}</span></td><td class="r num">${x.id === 'ens' ? '100%' : x.id === 'news' ? '—' : `${(D.fmodels.find((f) => f.name === x.name) || {}).weight || '—'}%`}</td><td class="r num">${x.h1.toFixed(2)}</td><td class="r num">${x.h4.toFixed(2)}</td></tr>`).join('')
      + D.benchmarks.map((b) => `<tr><td style="color:var(--label-2)">${b.name}<span class="d">Benchmark</span></td><td class="r">—</td><td class="r num">${b.h1.toFixed(2)}</td><td class="r num">${b.h4.toFixed(2)}</td></tr>`).join('');
    $$('#fc-lb tr.pick').forEach((tr) => tr.addEventListener('click', () => { fcModel = tr.dataset.model; forecasting(); }));
    const short = { 'UAEFTS settlements': 'UAEFTS', 'Aani instant payments': 'Aani', 'WPS payroll': 'WPS', 'Card spending': 'Cards 81%', 'Dubai Land Department': 'DLD', 'News, Arabic and English': 'News' };
    $('#fc-feeds').innerHTML = g.data.map((d) => `<li class="${d.ok ? '' : 'bad'}" title="${d.name}: ${d.vol}"><i></i>${short[d.name] || d.name}</li>`).join('');
  }
  $('#fc-model').addEventListener('change', (e) => { fcModel = e.target.value; forecasting(); });
  $('#fc-compare').addEventListener('change', (e) => { fcCompare = e.target.checked; forecasting(); });
  $$('#fc-range button').forEach((b) => b.addEventListener('click', () => { fcN = +b.dataset.n; $$('#fc-range button').forEach((x) => x.setAttribute('aria-pressed', x === b)); forecasting(); }));

  // ======================= FRAUD NETWORK =======================
  let tab = 'analysis', queueHtml = '', modelHtml = '', analysisHtml = '';
  let step = 4, bankOnly = false, playTimer = null, nodeEls = [], edgeEls = [], abroadLabel = null, built = false;
  const TONES = ['#636366', '#8e8e93', '#48484a', '#aeaeb2', '#7c7c80', '#9c9ca1'];
  function fraud() {
    $('#fr-lede').innerHTML = `Every Aani payment scored as it happens, then the whole payment network analysed for rings no single bank can see.`;
    $('#fr-metrics').innerHTML = [['Payments scored today', int(D.fraudKpis.scored), 'Aani, all banks'], ['Median scoring time', `${D.fraudKpis.medianMs} ms`, 'before settlement'], ['Alerts today', D.fraudKpis.alerts, '6 above 0.70 risk'], ['Groups flagged', R.flagged.length, { trail: 'money trails', community: 'communities', rules: 'single accounts' }[R.method]], ['Held for review', `AED ${D.heldAed.toFixed(2)} m`, 'top six alerts']]
      .map(([k, v, s]) => `<div class="metric"><dt>${k}</dt><dd class="num">${v}</dd><span>${s}</span></div>`).join('');
    queueHtml = D.alerts.map((a) => `<tr><td><strong>${a.id}</strong></td><td>${a.typ}<span class="d">${a.scope}</span></td><td class="r num">${a.banks}</td><td class="r num">AED ${a.aed.toFixed(2)} m</td><td class="r num"><span class="score"><i style="width:${a.score * 100}%"></i></span>${a.score.toFixed(2)}</td><td class="r"><span class="pill ${{ red: 'red', amber: 'orange', green: 'green' }[a.tone] || ''}">${a.status}</span></td></tr>`).join('');
    queueHtml = `<table><thead><tr><th>Alert</th><th class="r">Banks</th><th class="r">Value</th><th class="r">Risk</th></tr></thead><tbody>${D.alerts.map((a) => `<tr><td><strong>${a.id}</strong><span class="d">${a.typ} · ${a.scope}</span><span class="pill ${{ red: 'red', amber: 'orange', green: 'green' }[a.tone] || ''}" style="margin-top:4px">${a.status}</span></td><td class="r num">${a.banks}</td><td class="r num">AED ${a.aed.toFixed(2)} m</td><td class="r num">${a.score.toFixed(2)}</td></tr>`).join('')}</tbody></table>`;
    const t = D.lanes[1].tradeoff;
    modelHtml = `<div class="mdl-row"><span class="mdl-k">Champion</span><span class="mdl-n">Mule-ring graph model v2.4</span><span class="mdl-s">scores each payment in 38 ms</span></div><div class="mdl-row chall"><span class="mdl-k">Challenger</span><span class="mdl-n">Graph model v2.5</span><span class="mdl-s">adds device and Confirmation of Payee signals</span></div>`
      + `<ul class="hbars" style="margin-top:8px">${[['Rings caught, champion', t.champ.recall], ['Rings caught, challenger', t.chall.recall], ['Alerts that are real, champion', t.champ.precision], ['Alerts that are real, challenger', t.chall.precision]].map(([k, v]) => `<li><span>${k}</span><span class="hb"><i style="width:${v * 100}%${k.includes('challenger') ? ';background:var(--bronze-3)' : ''}"></i></span><b class="num">${Math.round(v * 100)}%</b></li>`).join('')}</ul><p class="note">The challenger catches about 6 more rings a quarter but sends analysts 22% more alerts. One bank on its own catches 31%.</p><button class="btn small" type="button" data-toast="Graph model v2.5 now scores in shadow mode. Its alerts are logged for comparison and not sent to banks.">Run challenger in shadow mode</button>`;
    if (!built) { buildNet(); built = true; }
    drawNet();
  }
  function buildNet() {
    const host = $('#net-canvas'); host.innerHTML = '';
    const s = C.el('svg', { viewBox: `0 0 ${L.W} ${L.H}` }, host);
    edgeEls = L.edges.map((e) => C.el('line', { x1: L.nodes[e.s].x, y1: L.nodes[e.s].y, x2: L.nodes[e.t].x, y2: L.nodes[e.t].y, 'stroke-width': 1 }, s));
    nodeEls = L.nodes.map((n) => { const c = C.el('circle', { cx: n.x, cy: n.y, r: 3 }, s); C.el('title', {}, c).textContent = n.kind === 'abroad' ? 'Outward remittances' : `${L.BANKS[n.bank]} · account ${n.age} days old · passes on ${Math.round(n.flow * 100)}%${n.trail ? ` · ${n.trail}` : ''}`; return c; });
    const ab = L.nodes.find((n) => n.kind === 'abroad');
    abroadLabel = C.el('text', { x: ab.x + 12, y: ab.y + 4, 'font-size': 13, 'font-weight': 600, 'font-family': cssv('--font'), fill: cssv('--label') }, s); abroadLabel.textContent = 'Sent abroad';
    $$('#stepper button').forEach((b) => b.addEventListener('click', () => { stopPlay(); step = +b.dataset.step; drawNet(); }));
    $('#bank-only').addEventListener('change', (e) => { bankOnly = e.target.checked; drawNet(); });
    $('#net-play').addEventListener('click', () => { stopPlay(); step = 1; drawNet(); playTimer = setInterval(() => { if (step >= 4) return stopPlay(); step++; drawNet(); }, 2200); });
  }
  function stopPlay() { clearInterval(playTimer); playTimer = null; }
  let settings = { method: 'trail', holdMax: 60, flowMin: 0.7 };
  const methodName = { trail: 'Money-trail tracing (network)', community: 'Community detection (network)', rules: 'Account rules (no network)' };
  function settingsHtml() {
    const verdict = R.method === 'rules'
      ? `<strong>${R.flagged.length} separate account alerts.</strong> Each mule account is caught, but nothing links them: analysts see ${R.flagged.length} small cases, not one ring.`
      : R.method === 'community'
        ? `<strong>${R.ringCaught} of ${R.ringSize}</strong> ring accounts flagged, and the largest piece holds only ${R.largest}. Community detection splits a layered ring into fragments.`
        : `<strong>${R.ringCaught} of ${R.ringSize}</strong> ring accounts caught as <strong>one network</strong> of ${R.largest}${R.falseAlarms ? `, with <strong>${R.falseAlarms} ordinary accounts</strong> wrongly included` : ', with no ordinary accounts wrongly included'}.`;
    return `<h2 class="insp-h">Detection method</h2>
      <div class="opt-list" role="radiogroup" aria-label="Detection method">${Object.entries(methodName).map(([k, v]) => `<label class="opt${settings.method === k ? ' on' : ''}"><input type="radio" name="method" value="${k}"${settings.method === k ? ' checked' : ''}><span>${v}</span></label>`).join('')}</div>
      <label class="rng"><span>Passed on within <output class="num">${settings.holdMax} min</output></span><input type="range" id="set-hold" min="10" max="240" step="10" value="${settings.holdMax}"${settings.method === 'community' ? ' disabled' : ''}></label>
      <label class="rng"><span>Forwards at least <output class="num">${Math.round(settings.flowMin * 100)}%</output></span><input type="range" id="set-flow" min="50" max="95" step="5" value="${Math.round(settings.flowMin * 100)}"${settings.method === 'community' ? ' disabled' : ''}></label>
      <button class="btn filled small" type="button" id="set-run">Run detection</button>
      <div class="verdict"><span class="mdl-k">Result of the last run</span><p>${verdict}</p></div>
      <p class="net-note">Synthetic week: the planted ring has ${R.ringSize} accounts, so every method can be checked against the truth.</p>`;
  }
  function wireSettings() {
    $$('#net-side input[name="method"]').forEach((i) => i.addEventListener('change', () => { settings.method = i.value; inspector(); }));
    const h = $('#set-hold'), f = $('#set-flow');
    if (h) h.addEventListener('input', () => { settings.holdMax = +h.value; h.previousElementSibling.querySelector('output').textContent = `${h.value} min`; });
    if (f) f.addEventListener('input', () => { settings.flowMin = +f.value / 100; f.previousElementSibling.querySelector('output').textContent = `${f.value}%`; });
    $('#set-run').addEventListener('click', () => {
      R = L.detect(settings); top = R.comms[0] || L.run.comms[0];
      $('#fr-metrics').innerHTML && fraud();
      toast(`${methodName[settings.method]}: ${R.flagged.length} groups flagged, ${R.ringCaught} of ${R.ringSize} ring accounts caught.`);
    });
  }
  function inspector() {
    $$('#insp-tabs button').forEach((b) => b.setAttribute('aria-pressed', b.dataset.tab === tab));
    $('#net-side').innerHTML = tab === 'analysis' ? analysisHtml : tab === 'queue' ? queueHtml : tab === 'settings' ? settingsHtml() : modelHtml;
    if (tab === 'settings') wireSettings();
  }
  $$('#insp-tabs button').forEach((b) => b.addEventListener('click', () => { tab = b.dataset.tab; inspector(); }));
  function drawNet() {
    $$('#stepper button').forEach((b) => b.setAttribute('aria-pressed', +b.dataset.step === step));
    const red = cssv('--red'), orange = cssv('--orange'), tint = cssv('--tint');
    const inTrail = (n) => n.trail && R.commOf.get(n.trail) && R.commOf.get(n.trail).score >= 0.7;
    const sources = new Set(R.flagged.flatMap((c) => c.sources));
    const seen = (n) => !bankOnly || n.bank === 2 || n.kind === 'abroad';
    L.nodes.forEach((n, i) => {
      let fill = '#aeaeb2', r = 2.6, op = 1, stroke = 'none';
      if (step === 2) fill = TONES[n.comm % TONES.length];
      if (step === 3) { fill = n.flow >= 0.7 ? tint : n.flow > 0.3 ? cssv('--bronze-3') : '#d1d1d6'; r = n.flow >= 0.7 ? 3.6 : 2.4; }
      if (step === 4) {
        if (inTrail(n)) { fill = R.method === 'rules' ? orange : R.commOf.get(n.trail).rank === 1 ? red : orange; r = 3 + n.pr * 9; }
        else if (sources.has(n.id)) { fill = '#fff'; stroke = red; r = 3.4; }
        else { fill = '#d1d1d6'; op = 0.6; }
      }
      if (n.kind === 'abroad') { fill = cssv('--label'); r = 8; }
      if (!seen(n)) op = 0.06;
      const el = nodeEls[i]; el.setAttribute('fill', fill); el.setAttribute('r', r.toFixed(1)); el.setAttribute('opacity', op); el.setAttribute('stroke', stroke); el.setAttribute('stroke-width', stroke === 'none' ? 0 : 1.6);
    });
    L.edges.forEach((e, k) => {
      const a = L.nodes[e.s], b = L.nodes[e.t]; let col = '#e5e5ea', op = 0.9, w = 1, cls = '';
      if (step === 2) { col = a.comm === b.comm ? TONES[a.comm % TONES.length] : '#e5e5ea'; op = a.comm === b.comm ? 0.4 : 0.7; }
      if (step === 3) { if (R.fastEdge[k]) { col = tint; w = 1.6; cls = 'flow'; } else { col = '#ececf0'; op = 0.6; } }
      if (step === 4) { const hot = (inTrail(a) || sources.has(a.id)) && (inTrail(b) || b.kind === 'abroad') && (R.method === 'rules' ? false : R.method === 'community' ? a.trail === b.trail : (R.fastEdge[k] || sources.has(a.id))); if (hot) { col = R.method === 'rules' || (inTrail(a) && R.commOf.get(a.trail).rank !== 1) ? orange : red; w = 1.6; cls = 'flow'; } else { col = '#ececf0'; op = 0.4; } }
      if (!seen(a) && !seen(b)) op = 0.03; else if (!seen(a) || !seen(b)) op = Math.min(op, 0.25);
      const el = edgeEls[k]; el.setAttribute('stroke', col); el.setAttribute('stroke-width', w); el.setAttribute('opacity', op); el.setAttribute('class', cls);
    });
    abroadLabel.setAttribute('opacity', step >= 3 ? 1 : 0);
    const bankC = top.members.filter((id) => L.nodes[id].bank === 2).length;
    const notes = {
      1: `<p class="net-lede">${int(L.stats.accounts)} accounts at six banks made ${int(L.stats.transfers)} transfers on Aani this week. Each dot is an account, each line a transfer.</p><p class="net-note">Nothing stands out by eye. Step through the analysis.</p>`,
      2: `<p class="net-lede"><strong>Community detection</strong> (weighted label propagation) groups accounts that pay each other into <strong>${L.stats.communities} communities</strong>: payroll, merchants, households.</p><p class="net-note">The mule ring does not stand out here. Its layers look like ordinary chains of payments, which is why a single rule, or a single bank, misses it.</p>`,
      3: `<p class="net-lede"><strong>Money-trail tracing</strong> follows transfers an account passes on within an hour, when it forwards at least 70% of what it received. It finds <strong>${R.method === 'trail' ? R.comms.length : L.stats.trails} fast money trails</strong>.</p><p class="net-note">Colour shows how much of its incoming money each account passes straight on.</p>`,
      4: `<p class="net-lede">Each trail is scored on five signals; <strong>PageRank on money flows</strong> sizes accounts by how much money ends up with them. ${top.id} scores <strong>${top.score.toFixed(2)}</strong>.</p>`,
    };
    const table = `<table><thead><tr><th>${{ trail: 'Trail', community: 'Community', rules: 'Account' }[R.method]}</th><th class="r">Accounts</th><th class="r">Banks</th><th class="r">Held</th><th class="r">Score</th></tr></thead><tbody>${R.comms.slice(0, 8).map((c) => `<tr><td><i class="sw-dot" style="background:${c.rank === 1 ? red : orange}"></i>${c.id}</td><td class="r num">${c.size}</td><td class="r num">${c.banks}</td><td class="r num">${Math.round(c.holdMed)} min</td><td class="r num"><strong>${c.score.toFixed(2)}</strong></td></tr>`).join('')}</tbody></table>`;
    const pm = Math.max(...Object.values(top.parts));
    const explain = `<h2 class="insp-h">Why ${top.id} scores ${top.score.toFixed(2)}</h2><ul class="explain">${Object.entries(top.parts).map(([k, v]) => `<li><span>${k}</span><span class="hb"><i style="width:${(v / pm) * 100}%"></i></span><b class="num">+${v.toFixed(2)}</b></li>`).join('')}</ul><p class="net-note">${top.size} accounts across ${top.banks} banks, money held a median ${Math.round(top.holdMed)} minutes, ${Math.round(top.youngShare * 100)}% of accounts under 90 days old, fed by ${top.sources.length} victims, ending abroad.</p><div class="net-actions"><button class="btn filled small" type="button" data-toast="Case opened for ${top.id}: ${top.size} accounts, ${top.banks} banks. Logged for the Anti-Fraud Operations Centre.">Open a case</button><button class="btn small" type="button" data-toast="Alert drafted to ${top.banks} banks for ${top.size} accounts. Awaits analyst sign-off before it is sent.">Alert the ${top.banks} banks</button></div>`;
    const bankNote = bankOnly ? `<p class="bank-note">Bank C sees only <strong>${bankC} of the ${top.size}</strong> accounts in ${top.id}. To Bank C they look like ordinary customers paying customers at other banks.</p>` : '';
    analysisHtml = notes[step] + bankNote + (step >= 3 ? table : '') + (step === 4 ? explain : '');
    inspector();
  }

  // ======================= INVESTMENT: lifecycle and Ask Nabd =======================
  const JOURNEY = ['Screening', 'Due diligence', 'Investment committee', 'Approved', 'Funded', 'Monitoring', 'Review'];
  const stageToStep = [0, 1, 2, 3, 5];
  const fmtD = (d) => d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' });
  D.mandates.forEach((m, k) => {
    const cur = stageToStep[m.stage], today = Date.UTC(2026, 10, 16), DAYW = 7 * 86400000;
    m.step = cur;
    m.dates = JOURNEY.map((_, i) => new Date(today + (i - cur) * (5 + (k % 3)) * DAYW));
  });
  let ivSel = 'M-112', ivTab = 'findings';
  const portfolio = () => { const rows = D.allocation.map((a) => ({ ...a, ret: a.hormuz30 })); const tot = rows.reduce((s, a) => s + (a.w * a.ret) / 100, 0); return { rows, tot, aed: (tot / 100) * D.notional }; };
  function investment() {
    const { rows, tot, aed } = portfolio();
    $('#iv-lede').innerHTML = `A notional AED ${D.notional} bn reserve portfolio under scenario run ${runNo}, a 30-day Hormuz closure: <strong>${signed(tot, 2)}%</strong>. Follow each mandate through its lifecycle and ask Nabd about any of it.`;
    $('#iv-alloc-sub').textContent = `Run ${runNo}, median of 1,000 runs, 90 days · AED ${signed(aed, 2)} bn`;
    const mr = Math.max(...rows.map((a) => Math.abs(a.ret)));
    $('#iv-alloc').innerHTML = rows.map((a) => `<tr><td>${a.name}</td><td class="r num">${a.w}%</td><td><span class="dbar">${a.ret ? `<i class="${a.ret < 0 ? 'neg' : 'pos'}" style="width:${(Math.abs(a.ret) / mr) * 50}%"></i>` : ''}</span></td><td class="r num ${a.ret < 0 ? 'worse' : a.ret > 0 ? 'better' : ''}">${a.ret ? `${signed(a.ret)}%` : '0.0%'}</td></tr>`).join('')
      + `<tr><td><strong>Portfolio</strong></td><td class="r num"><strong>100%</strong></td><td></td><td class="r num ${tot < 0 ? 'worse' : 'better'}"><strong>${signed(tot, 2)}%</strong></td></tr>`;
    $('#iv-pipe').innerHTML = D.stages.map((st, k) => { const items = D.mandates.filter((m) => m.stage === k); return `<div class="pcol"><div class="pcol-head"><span>${st}</span><span class="num">${items.length}</span></div>${items.map((m) => `<button type="button" class="mandate${m.id === ivSel ? ' on' : ''}" data-id="${m.id}"><span class="m-name">${m.name}</span><span class="m-meta num">AED ${m.aed.toFixed(1)} bn</span></button>`).join('')}</div>`; }).join('');
    $$('#iv-pipe .mandate').forEach((b) => b.addEventListener('click', () => { ivSel = b.dataset.id; investment(); }));
    const m = D.mandates.find((x) => x.id === ivSel);
    $('#iv-journey').innerHTML = `<div class="j-head"><strong>${m.name}</strong><span class="sub">${m.id} · AED ${m.aed.toFixed(1)} bn · ${m.owner} · next: ${m.next}</span></div><ol class="j-steps">${JOURNEY.map((s, i) => `<li class="${i < m.step ? 'done' : i === m.step ? 'now' : ''}"><span class="j-dot"></span><span class="j-name">${s}</span><span class="j-date num">${i < m.step ? fmtD(m.dates[i]) : i === m.step ? 'Now' : `Planned ${fmtD(m.dates[i]).replace(/ \d{4}$/, '')}`}</span></li>`).join('')}</ol>`;
    $('#iv-dd-title').textContent = m.dd ? 'Due diligence: emerging-market local-currency debt' : `Due diligence: ${m.name.toLowerCase()}`;
    $$('#iv-tabs button').forEach((b) => b.setAttribute('aria-pressed', b.dataset.tab === ivTab));
    if (ivTab === 'findings') {
      $('#iv-dd').innerHTML = m.dd
        ? `<ul class="findings">${D.ddFindings.map((x) => `<li><span><span class="pill ${{ high: 'red', warn: 'orange', ok: 'green' }[x.sev]}">${{ high: 'Needs an answer', warn: 'Check', ok: 'Clear' }[x.sev]}</span></span><p>${x.text}<span class="src">Source: ${x.src}</span></p></li>`).join('')}</ul>`
        : `<p class="note">${m.step < 1 ? 'Due diligence starts after screening. ' + m.next + '.' : 'Due diligence for this mandate is complete and filed. ' + m.next + '.'}</p>`;
    } else {
      $('#iv-dd').innerHTML = `<ul class="mgr">${D.managers.map((g) => `<li><div class="top"><span>${g.name}</span><b class="num">${g.score}</b></div><span class="hb"><i style="width:${g.score}%"></i></span><span class="sub">${g.aum} · ${g.track}</span>${g.open ? `<span class="pill red">${g.open} open findings</span>` : '<span class="pill green">No open findings</span>'}</li>`).join('')}</ul>`;
    }
    if (!$('#chat-log').children.length) chatSay('nabd', 'Ask me about the portfolio under the scenario, any mandate in the lifecycle, or the managers in due diligence. I answer from Nabd’s models and documents and cite each source.', []);
    $('#chat-chips').innerHTML = ['How does Hormuz hit the portfolio?', 'What are the red flags on Manager B?', 'Which manager should we pick?', 'What is coming to committee?'].map((q) => `<button type="button" class="chip-q">${q}</button>`).join('');
    $$('#chat-chips .chip-q').forEach((b) => b.addEventListener('click', () => ask(b.textContent)));
  }
  $$('#iv-tabs button').forEach((b) => b.addEventListener('click', () => { ivTab = b.dataset.tab; investment(); }));

  function chatSay(who, html, sources) {
    const li = document.createElement('div'); li.className = `msg ${who}`;
    li.innerHTML = `<div class="bubble">${html}${sources && sources.length ? `<div class="srcs">${sources.map((s) => `<span>${s}</span>`).join('')}</div>` : ''}</div>`;
    $('#chat-log').appendChild(li); $('#chat-log').scrollTop = $('#chat-log').scrollHeight;
    return li;
  }
  function answer(q) {
    const t = q.toLowerCase(), { rows, tot, aed } = portfolio(), by = (n) => rows.find((r) => r.name.startsWith(n));
    if (/manager b|red flag|finding|diligence|concern/.test(t)) {
      const hi = D.ddFindings.filter((x) => x.sev === 'high');
      return { html: `Manager B has <strong>${hi.length} findings that need an answer</strong>:<ul>${hi.map((x) => `<li>${x.text}</li>`).join('')}</ul>Screening is clear for all three managers.`, src: hi.map((x) => x.src).concat(['Screening run, 15 Nov 2026']) };
    }
    if (/which manager|best|compare|pick|choose|shortlist/.test(t)) {
      const s = [...D.managers].sort((a, b) => b.score - a.score);
      return { html: `<strong>${s[0].name}</strong> scores highest at ${s[0].score} with no open findings (${s[0].aum}, ${s[0].track}). ${s[1].name} follows at ${s[1].score}. Manager B has the best track record (+1.4% a year) but scores ${D.managers[1].score} because of 2 open findings. The committee decides; this is the evidence, not a recommendation.`, src: ['Due-diligence model scores, 15 Nov 2026', 'Manager questionnaires'] };
    }
    if (/hormuz|scenario|impact|portfolio|hit|stress/.test(t)) {
      return { html: `Under scenario run ${runNo} (Strait of Hormuz closed 30 days, Brent $95) the notional portfolio moves <strong>${signed(tot, 2)}%</strong>, about AED ${signed(aed, 2)} bn. Equities fall ${Math.abs(by('Equities').ret).toFixed(1)}% and emerging-market bonds ${Math.abs(by('Emerging').ret).toFixed(1)}%; gold rises ${by('Gold').ret.toFixed(1)}% and developed-market bonds ${by('Developed').ret.toFixed(1)}%.`, src: [`Scenario engine, run ${runNo}, 1,000 simulations`, 'Allocation as of 16 Nov 2026'] };
    }
    if (/gold/.test(t)) return { html: `Gold is ${by('Gold').w}% of the notional portfolio and rises ${by('Gold').ret.toFixed(1)}% under run ${runNo}. Mandate M-104, a gold allocation rebalance of AED 1.5 bn, is approved and executing over 6 weeks.`, src: [`Scenario engine, run ${runNo}`, 'Mandate M-104'] };
    if (/committee|pipeline|stage|status|mandate|coming/.test(t)) {
      const ic = D.mandates.filter((m) => m.stage === 2), dd = D.mandates.filter((m) => m.stage === 1);
      return { html: `${ic.map((m) => `<strong>${m.name}</strong> (AED ${m.aed.toFixed(1)} bn) goes to committee: ${m.next.toLowerCase()}.`).join(' ')} ${dd.map((m) => `${m.name} is in due diligence with ${m.next.toLowerCase()}.`).join(' ')} ${D.mandates.filter((m) => m.stage === 0).length} mandates are in screening.`, src: ['Mandate pipeline, 16 Nov 2026'] };
    }
    if (/budget|limit|risk budget/.test(t)) return { html: 'The portfolio uses <strong>62% of the active risk budget</strong> set by the Board. The risk model had 2 backtest exceptions in 250 days, inside its limit of 4.', src: ['Scenario risk model v1.8', 'Board risk budget'] };
    return { html: 'I can answer about the portfolio under the scenario, the mandates in the lifecycle, due-diligence findings, the managers, gold and the risk budget. Try one of the suggestions below.', src: [] };
  }
  function ask(q) {
    if (!q.trim()) return;
    chatSay('me', q.replace(/</g, '&lt;'), []);
    const typing = chatSay('nabd', '<span class="typing"><i></i><i></i><i></i></span>', []);
    setTimeout(() => { typing.remove(); const a = answer(q); chatSay('nabd', a.html, a.src); }, 650);
  }
  $('#chat-form').addEventListener('submit', (e) => { e.preventDefault(); const i = $('#chat-q'); ask(i.value); i.value = ''; });

  // ======================= ROUTER =======================
  const pages = { overview, forecasting, fraud, investment };
  const names = { overview: 'Overview', forecasting: 'Forecasting', fraud: 'Fraud network', investment: 'Investment' };
  function route() {
    const id = (location.hash || '#overview').slice(1), key = pages[id] ? id : 'overview';
    $$('.page').forEach((p) => p.classList.toggle('on', p.id === key));
    $$('.tab').forEach((a) => (a.dataset.page === key ? a.setAttribute('aria-current', 'page') : a.removeAttribute('aria-current')));
    document.title = `${names[key]} · Nabd · Central Bank of the UAE`;
    pages[key]();
  }
  window.addEventListener('hashchange', () => { stopPlay(); route(); window.scrollTo(0, 0); });
  // keys 1 to 4 switch pages, unless the person is typing
  document.addEventListener('keydown', (e) => { if (e.metaKey || e.ctrlKey || e.altKey || /input|textarea|select/i.test(e.target.tagName)) return; const k = { 1: 'overview', 2: 'forecasting', 3: 'fraud', 4: 'investment' }[e.key]; if (k) location.hash = '#' + k; });
  let rz; window.addEventListener('resize', () => { clearTimeout(rz); rz = setTimeout(route, 200); });
  (document.fonts ? document.fonts.ready : Promise.resolve()).then(route);
})();
