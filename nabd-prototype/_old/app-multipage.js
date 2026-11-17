// Nabd prototype v3 — screens rendered from data.js. Routes: #home #scenarios #nowcast #time #network #fraud #gov
(() => {
  const D = window.NABD, C = window.NabdChart;
  const $ = (s, r = document) => r.querySelector(s), $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const MINUS = '−';
  const signed = (v, d = 1) => (v > 0.0001 ? '+' : v < -0.0001 ? MINUS : '') + Math.abs(v).toFixed(d);
  const int = (v) => new Intl.NumberFormat('en').format(v);
  const cssv = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
  const toast = (msg) => { const t = $('#toast'); t.textContent = msg; t.classList.add('show'); clearTimeout(t._h); t._h = setTimeout(() => t.classList.remove('show'), 3600); };
  const store = { get: (k) => { try { return localStorage.getItem(k); } catch { return null; } }, set: (k, v) => { try { localStorage.setItem(k, v); } catch {} } };

  // ---------- role and information barrier ----------
  let role = D.roles.find((r) => r.id === store.get('nabd-role')) || D.roles[0];
  const roleSel = $('#role');
  roleSel.innerHTML = D.roles.map((r) => `<option value="${r.id}">${r.name}</option>`).join('');
  roleSel.value = role.id;
  roleSel.addEventListener('change', () => { role = D.roles.find((r) => r.id === roleSel.value); store.set('nabd-role', role.id); route(); toast(`Viewing as ${role.name}. Screens now show only what this role may see.`); });
  const firmName = (f) => (role.firms ? `<span class="strong">${f.id}</span><span class="sub">${f.sector} · ${f.where}</span>` : `<span class="lock">Restricted firm</span><span class="sub">${f.sector}</span>`);

  // ---------- scenario state ----------
  const params = { days: 30, brent: 95, response: 'none' };
  let runNo = 4812, result = D.scenario({ ...params, seed: runNo }), stale = false;
  const history = [
    { no: 4812, label: 'Hormuz 30 days, Brent $95', by: 'Investment', when: 'Today 10:30', avg: result.avg },
    { no: 4811, label: 'Hormuz 14 days, Brent $88', by: 'Financial Stability', when: 'Yesterday', avg: -0.9 },
    { no: 4810, label: 'Oil at $45 for six months', by: 'Financial Stability', when: 'Yesterday', avg: -1.3 },
  ];

  const releases = [{ label: 'Q4 2025 official estimate', date: '2026-04-13' }, { label: 'Q1 2026 official', date: '2026-07-06' }, { label: 'Q2 2026 official', date: '2026-10-05' }]
    .map((m) => ({ ...m, at: Math.floor((new Date(m.date + 'T00:00:00Z') - D.weeks[0]) / (7 * D.DAY)) }));

  // ======================= HOME =======================
  function home() {
    $('#greet').textContent = `Good morning, ${role.name}`;
    $('#greet-sub').textContent = 'Monday 16 November 2026. Here is what changed in the UAE economy since yesterday, and what is waiting for your team.';
    const now = D.nowcast.at(-1);
    $('#home-now').textContent = `${now.toFixed(1)}%`;
    $('#home-now-note').innerHTML = `<span class="worse">${signed(D.weekChange, 2)} pp</span> on last week · 70% range ${(now - D.half70.at(-1)).toFixed(1)}% to ${(now + D.half70.at(-1)).toFixed(1)}%`;
    // signature band: the year's pulse, full width, with uncertainty and the official release dates
    C.render($('#home-chart'), {
      height: 210, xLabels: D.weeks.map(D.fmtShort), yTicks: [0, 2, 4, 6, 8], yFormat: (v) => `${v}%`, label: 'Weekly non-oil nowcast for 2026 with uncertainty bands',
      bands: [{ lo: D.nowcast.map((v, i) => v - D.half90[i]), hi: D.nowcast.map((v, i) => v + D.half90[i]), color: cssv('--bronze-1') }, { lo: D.nowcast.map((v, i) => v - D.half70[i]), hi: D.nowcast.map((v, i) => v + D.half70[i]), color: cssv('--bronze-2') }],
      series: [{ values: D.nowcast, color: cssv('--bronze-ink'), width: 2.5, cls: 'draw' }],
      points: [{ at: D.nowcast.length - 1, value: now, color: cssv('--bronze-ink'), r: 5, pulse: true }],
      markers: releases.map((m) => ({ at: m.at, label: m.label })),
      tip: (i) => `Week of ${D.fmtShort(D.weeks[i])}: ${D.nowcast[i].toFixed(1)}%`,
    });
    const items = [
      { text: `Non-oil activity eased. The Q4 nowcast is <strong>${now.toFixed(1)}%</strong>, down ${Math.abs(D.weekChange).toFixed(2)} points on last week; contractor payments explain about half of the fall.`, src: 'Nowcast run, 16 Nov 06:00', href: '#nowcast', cta: 'See what moved' },
      role.fraud
        ? { text: `A suspected mule ring across <strong>6 banks</strong> was opened overnight: AED ${D.ring.aed.toFixed(2)} m from ${D.ring.victims} victims in ${D.ring.days} days.`, src: 'Mule ring detector, case R-2611-07', href: '#fraud', cta: 'Open case' }
        : { text: 'One payment-system case was opened overnight. Its details are restricted to Payment Systems and the Governor’s Office.', src: 'Information barrier applied for your role', href: '#gov', cta: 'Why restricted' },
      { text: 'The Hormuz 30-day playbook from scenario run 4812 is waiting for the Chief Risk Officer’s sign-off.', src: 'Saved by Investment, today 10:30', href: '#scenarios', cta: 'Review run' },
    ];
    $('#brief').innerHTML = items.map((b) => `<li><p>${b.text}<span class="src">${b.src}</span></p><a class="link" href="${b.href}">${b.cta}</a></li>`).join('');
    const movers = [...D.news].sort((a, b) => a.pp - b.pp), mx = Math.max(...movers.map((x) => Math.abs(x.pp)));
    $('#home-news').innerHTML = movers.map((x) => `<li><span class="name">${x.release}</span><span class="dbar" aria-hidden="true"><i class="${x.pp < 0 ? 'neg' : 'pos'}" style="width:${(Math.abs(x.pp) / mx) * 50}%"></i></span><span class="v num ${x.pp < 0 ? 'worse' : 'better'}">${signed(x.pp, 2)}</span></li>`).join('') + `<li class="total"><span class="name">Total revision</span><span></span><span class="v num worse">${signed(D.weekChange, 2)}</span></li>`;
    const late = D.feeds.filter((f) => f.status !== 'current').length;
    $('#trust').innerHTML = [
      ['Models on premise', '4 of 5'], ['Hosted language model', 'UAE North'], ['Firm records sent out', `${D.usage.recordsOut}`],
      ['Feeds current', `${D.feeds.length - late} of ${D.feeds.length}`], ['Language-model calls today', `${D.usage.llmCalls}`], ['Last validation', '3 Nov 2026'], ['Audit events today', int(D.usage.runs)], ['Information barriers', '4 roles'], ['Data in this prototype', 'Illustrative'],
    ].map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join('');
    // entry columns, each with its own live preview
    const last = history[0], r = result;
    C.render($('#way-scn-chart'), {
      height: 96, padR: 4, xLabels: Array.from({ length: r.T }, (_, t) => `Day ${t}`), yTicks: [-6, -3, 0], yFormat: (v) => (v === 0 ? '0' : signed(v, 0)), label: 'Last scenario run, range of outcomes',
      bands: [{ lo: r.bands[0], hi: r.bands[4], color: cssv('--bronze-1') }, { lo: r.bands[1], hi: r.bands[3], color: cssv('--bronze-2') }],
      series: [{ values: r.median, color: cssv('--bronze-ink'), width: 2 }],
    });
    $('#way-scn').innerHTML = `<strong class="num">${signed(last.avg)} pp</strong>last run: ${last.label}`;
    const top3 = [...D.news].sort((a, b) => a.pp - b.pp).slice(0, 4), m3 = Math.abs(top3[0].pp);
    $('#way-now-chart').innerHTML = `<span class="minibars">${top3.map((x) => `<div><span>${x.release}</span><span class="dbar"><i class="neg" style="width:${(Math.abs(x.pp) / m3) * 50}%"></i></span><b class="worse num">${signed(x.pp, 2)}</b></div>`).join('')}</span>`;
    $('#way-now').innerHTML = `<strong class="num">${now.toFixed(1)}%</strong>current estimate, ${signed(D.weekChange, 2)} pp this week`;
    const qs = D.quarters.filter((x) => x.lead != null), ml = Math.max(...qs.map((x) => x.lead));
    $('#way-time-chart').innerHTML = `<span class="leadbars" role="img" aria-label="Days ahead of the official estimate, by quarter">${qs.map((x, i) => `<span class="lb" title="${x.label}: ${x.lead} days ahead"><span class="lb-bar${i === qs.length - 1 ? ' last' : ''}" style="height:${(x.lead / ml) * 72}px"></span><em>${x.label.startsWith('Q1') ? x.label.slice(3) : '&nbsp;'}</em></span>`).join('')}</span>`;
    $('#way-time').innerHTML = `<strong class="num">${D.meanLead} days</strong>ahead of the first official estimate, on average`;
    $('#team').innerHTML = D.activity.map((a) => {
      let what = a.what, status = `<span class="pill ${{ warn: 'amber', neg: 'red', pos: 'green' }[a.tone] || ''}">${a.status}</span>`;
      if (a.fraud && !role.fraud) { what = '<span class="lock">Payment-system case, restricted</span>'; status = '<span class="pill">Restricted</span>'; }
      else if (a.firmLevel && !role.firms) what = `<span class="lock">${a.masked}</span>`;
      return `<tr class="link-row" data-href="#${a.route}"><td class="strong">${what}</td><td>${a.kind}</td><td>${a.who}</td><td class="num">${a.when}</td><td class="r">${status}</td></tr>`;
    }).join('');
    $$('#team tr').forEach((tr) => tr.addEventListener('click', () => (location.hash = tr.dataset.href)));
  }

  // ======================= SCENARIOS =======================
  function scenarios() {
    $('#days').value = params.days; $('#days-out').textContent = `${params.days} days`; $('#brent').value = params.brent; $('#response').value = params.response;
    const r = result, T = r.T, facility = r.response === 'facility';
    const lo = Math.min(-1, Math.min(...r.bands[0])), step = lo < -6 ? 2 : 1, yTicks = []; for (let v = Math.floor(lo / step) * step; v <= 0; v += step) yTicks.push(v);
    const sample = r.runs.filter((_, k) => k % 16 === 0);
    const compare = facility ? D.scenario({ days: r.days, brent: r.brent, response: 'none', seed: runNo }).median : null;
    fanChart = C.render($('#fan-chart'), {
      height: 300, xLabels: Array.from({ length: T }, (_, t) => `Day ${t}`), yTicks, yFormat: (v) => (v === 0 ? '0' : signed(v, 0)), label: 'Distribution of non-oil GDP outcomes across 1,000 runs',
      bands: [{ lo: r.bands[0], hi: r.bands[4], color: cssv('--bronze-1') }, { lo: r.bands[1], hi: r.bands[3], color: cssv('--bronze-2') }],
      hairlines: [{ lines: sample, color: cssv('--ink'), opacity: 0.045 }],
      series: [...(compare ? [{ values: compare, color: '#8a9098', width: 1.5, dash: '5 4' }] : []), { values: r.median, color: cssv('--bronze-ink'), width: 2.5 }],
      markers: [{ at: r.days, label: `Strait reopens, day ${r.days}` }],
      tip: (t) => `Day ${t}: median ${signed(r.median[t])} pp (90% of runs ${signed(r.bands[4][t])} to ${signed(r.bands[0][t])})`,
    });
    $('#fan-legend').innerHTML = `<span><i class="sw sw-line" style="background:${cssv('--bronze-ink')}"></i>Median run</span><span><i class="sw" style="background:${cssv('--bronze-2')}"></i>60% of runs</span><span><i class="sw" style="background:${cssv('--bronze-1')}"></i>90% of runs</span>${compare ? '<span><i class="sw sw-line" style="background:#8a9098"></i>No response, median</span>' : ''}`;
    $('#fan-source').textContent = `Run ${runNo} · 1,000 simulations on ${int(D.totalFirms)} firms and ${D.banksCount} banks · data vintage 16 Nov 2026, 06:00 · computed on premise. Illustrative model and data.`;
    const lowDay = r.median.indexOf(r.low);
    $('#scn-kpis').innerHTML = [
      ['Output lost, 90-day average', `${signed(r.avg)} pp`, `90% of runs ${signed(r.avg5)} to ${signed(r.avg95)}`],
      ['Lowest point, median run', `${signed(r.low)} pp`, `on day ${lowDay}`],
      ['Firms that miss payroll', int(r.payroll), `range ${int(r.payrollLo)} to ${int(r.payrollHi)}`],
      ['Banks below 100% liquidity cover', `${r.banks} of ${D.banksCount}`, facility ? `facility drawn AED ${r.drawn.toFixed(1)} bn of 30` : 'no facility in this run'],
    ].map(([l, v, s]) => `<div class="kpi"><div class="kpi-label">${l}</div><div class="kpi-value num">${v}</div><div class="kpi-sub">${s}</div></div>`).join('');
    $('#brk').innerHTML = D.firms.slice(0, 5).map((f) => {
      const out = r.breakDay(f), pct = (d) => `${Math.min(100, (d / 90) * 100).toFixed(2)}%`;
      const bridge = facility ? `<i class="bridge" style="left:${pct(f.buffer)};width:${pct(D.BRIDGE)};top:2px;height:6px"></i>` : '';
      return `<tr><td>${firmName(f)}</td><td class="r num">${f.buffer} days</td><td><div class="bar-track" title="Closure in light bronze, cash buffer in dark grey${facility ? ', payroll bridge in bronze' : ''}"><i class="closure" style="left:0;width:${pct(r.days)}"></i><i class="buf" style="left:0;width:${pct(f.buffer)};top:2px;height:6px"></i>${bridge}${out ? `<span class="out" style="left:${pct(out)}"></span>` : ''}</div></td><td class="r num ${out ? 'worse strong' : ''}">${out ? `Day ${out}` : 'Holds'}</td><td class="r num">${f.banks}</td></tr>`;
    }).join('');
    $('#runs').innerHTML = history.map((h) => `<li><span class="strong">Run ${h.no}</span><span class="num">${signed(h.avg)} pp</span><span class="sub">${h.label} · ${h.by}, ${h.when}</span></li>`).join('');
    setupPlay();
    const st = $('#run-state'); st.classList.toggle('stale', stale);
    st.textContent = stale ? 'Settings changed. Run again to update the results.' : `Showing run ${runNo}.`;
  }
  const markStale = () => { params.days = +$('#days').value; params.brent = +$('#brent').value || 95; params.response = $('#response').value; $('#days-out').textContent = `${params.days} days`; stale = true; const st = $('#run-state'); st.classList.add('stale'); st.textContent = 'Settings changed. Run again to update the results.'; };
  ['#days', '#brent', '#response'].forEach((s) => $(s).addEventListener('input', markStale));
  $('#parse-btn').addEventListener('click', () => {
    const t = $('#scn-text').value, d = t.match(/(\d+)\s*-?\s*days?/i), b = t.match(/\$\s?(\d+)/) || t.match(/brent[^0-9]*(\d+)/i);
    if (d) params.days = Math.max(7, Math.min(60, +d[1]));
    if (b) params.brent = Math.max(40, Math.min(150, +b[1]));
    params.response = /facility|liquidity|bridge/i.test(t) ? 'facility' : 'none';
    $('#days').value = params.days; $('#days-out').textContent = `${params.days} days`; $('#brent').value = params.brent; $('#response').value = params.response;
    $('#parse-note').textContent = `Read as: closure ${params.days} days, Brent $${params.brent}, ${params.response === 'facility' ? 'liquidity facility and payroll bridge' : 'no policy response'}. Check the settings, then run.`;
    stale = true; $('#run-state').classList.add('stale'); $('#run-state').textContent = 'Settings changed. Run again to update the results.';
  });
  $('#run-btn').addEventListener('click', () => {
    const btn = $('#run-btn'), st = $('#run-state'), t0 = performance.now();
    btn.disabled = true; st.classList.remove('stale'); st.textContent = `Running 1,000 simulations on ${int(D.totalFirms)} firms…`;
    setTimeout(() => {
      runNo += 1; result = D.scenario({ ...params, seed: runNo }); stale = false;
      history.unshift({ no: runNo, label: `Hormuz ${params.days} days, Brent $${params.brent}${params.response === 'facility' ? ', facility' : ''}`, by: role.name, when: 'Just now', avg: result.avg });
      history.length = Math.min(history.length, 5);
      btn.disabled = false; scenarios();
      $('#run-state').textContent = `Run ${runNo} finished in ${((performance.now() - t0) / 1000).toFixed(1)} s.`;
    }, 700);
  });
  $('#save-btn').addEventListener('click', () => toast(`Run ${runNo} saved as a playbook and sent to the Chief Risk Officer for sign-off.`));

  // ======================= NOWCAST =======================
  let ncN = 46;
  function nowcast() {
    const now = D.nowcast.at(-1);
    $('#now-lede').innerHTML = `This week Nabd estimates current-quarter non-oil growth at <strong>${now.toFixed(1)}%</strong>, down ${Math.abs(D.weekChange).toFixed(2)} points. The first official estimate for Q4 2026 is due in April 2027; Nabd updates every morning.`;
    $('#nc-now').textContent = `${now.toFixed(1)}%`;
    $('#nc-note').innerHTML = `<span class="worse">${signed(D.weekChange, 2)} pp</span> on last week · 70% range ${(now - D.half70.at(-1)).toFixed(1)}% to ${(now + D.half70.at(-1)).toFixed(1)}%`;
    const from = D.nowcast.length - ncN, sl = (a) => a.slice(from);
    C.render($('#nc-chart'), {
      height: 280, xLabels: sl(D.weeks).map(D.fmtShort), yTicks: [0, 2, 4, 6, 8], yFormat: (v) => `${v}%`, label: 'Weekly non-oil nowcast with uncertainty bands',
      bands: [{ lo: sl(D.nowcast.map((v, i) => v - D.half90[i])), hi: sl(D.nowcast.map((v, i) => v + D.half90[i])), color: cssv('--bronze-1') }, { lo: sl(D.nowcast.map((v, i) => v - D.half70[i])), hi: sl(D.nowcast.map((v, i) => v + D.half70[i])), color: cssv('--bronze-2') }],
      series: [{ values: sl(D.nowcast), color: cssv('--bronze-ink'), width: 2.5 }],
      markers: releases.filter((m) => m.at >= from).map((m) => ({ at: m.at - from, label: m.label })),
      tip: (i) => `Week of ${D.fmtShort(D.weeks[from + i])}: ${D.nowcast[from + i].toFixed(1)}% (70% range ${(D.nowcast[from + i] - D.half70[from + i]).toFixed(1)} to ${(D.nowcast[from + i] + D.half70[from + i]).toFixed(1)})`,
    });
    $('#news-meta').textContent = 'Each data release’s contribution to this week’s revision, in points';
    const max = Math.max(...D.news.map((x) => Math.abs(x.pp)));
    $('#news').innerHTML = [...D.news].sort((a, b) => a.pp - b.pp).map((x) => `<li><span class="name">${x.release}<span>${x.when}</span>${x.note ? `<em>${x.note}</em>` : ''}</span><span class="dbar" aria-hidden="true"><i class="${x.pp < 0 ? 'neg' : 'pos'}" style="width:${(Math.abs(x.pp) / max) * 50}%"></i></span><span class="v num ${x.pp < 0 ? 'worse' : 'better'}">${signed(x.pp, 2)}</span></li>`).join('')
      + `<li class="total"><span class="name">Total revision</span><span></span><span class="v num worse">${signed(D.weekChange, 2)}</span></li>`;
    $('#feeds').innerHTML = D.feeds.map((f) => `<tr><td class="strong">${f.source}</td><td>${f.measure}</td><td class="r num">${f.latest}</td><td class="r num">${f.asOf}</td><td>${f.status === 'current' ? '<span class="pill green">Current</span>' : `<span class="pill amber">Late</span> <span class="sub">${f.note}</span>`}</td></tr>`).join('');
  }
  $$('#nowcast .seg button').forEach((b) => b.addEventListener('click', () => { ncN = +b.dataset.n; $$('#nowcast .seg button').forEach((x) => x.setAttribute('aria-pressed', x === b)); nowcast(); }));
  $('#note-btn').addEventListener('click', () => {
    const c = (v, src) => `<button type="button" class="cite" data-src="${src}">${v}</button>`;
    $('#note-body').innerHTML = `
      <p>Non-oil activity slowed this week. Nabd’s nowcast for Q4 2026 is ${c(`${D.nowcast.at(-1).toFixed(1)}%`, 'Non-oil nowcast|Run 16 Nov 2026 06:00 · dynamic factor model · on premise · validated 28 Oct 2026')} year on year, ${c(`${signed(D.weekChange, 2)} points`, 'Weekly revision|Sum of six data-release contributions, run 16 Nov 06:00')} on last week.</p>
      <p>Contractor and port payments took off ${c('0.18 points', 'UAEFTS contractor and freight payments|−0.12 and −0.06, run 16 Nov 06:00')}; card spending and October payroll took off a further 0.12. Property deals and Aani merchant payments added back ${c('0.05 points', 'Dubai Land Department and Aani|+0.03 and +0.02, run 16 Nov 06:00')}.</p>
      ${role.fraud ? `<p>Payment Systems has opened a suspected mule ring across six banks (${c(`AED ${D.ring.aed.toFixed(2)} m`, 'Case R-2611-07|Mule ring detector · 41 accounts · on premise')}) and recommends alerting all six banks today. This recommendation is the team’s, not the model’s.</p>` : ''}`;
    $('#note').showModal();
  });
  document.addEventListener('click', (e) => {
    const pop = $('#pop'), b = e.target.closest('.cite');
    if (!b) { pop.hidden = true; return; }
    const [title, body] = b.dataset.src.split('|'), r = b.getBoundingClientRect();
    pop.innerHTML = `<strong>${title}</strong>${body}`; pop.hidden = false;
    pop.style.left = `${Math.min(window.innerWidth - 316, r.left)}px`; pop.style.top = `${r.bottom + 8}px`;
  });
  $('#note').addEventListener('close', () => { $('#pop').hidden = true; if ($('#note').returnValue === 'send') toast('Sent to the Chief Economist for sign-off. Logged in Governance.'); });

  // ======================= TIME MACHINE =======================
  const quarterOf = (d) => { const m = d.getUTCMonth(); return `Q${Math.floor(m / 3) + 1} ${d.getUTCFullYear()}`; };
  function time() {
    $('#tm-lede').innerHTML = `Nabd keeps every estimate exactly as it stood on the day. Over the last ten quarters its quarter-end estimate came <strong>${D.meanLead} days</strong> before the first official GDP estimate, with a mean difference of <strong>${D.mae.toFixed(2)} points</strong>.`;
    const wk = +$('#tm-week').value, date = D.weeks[wk];
    $('#tm-date').textContent = D.fmtDate(date);
    const shown = D.nowcast.map((v, i) => (i <= wk ? v : null));
    C.render($('#tm-chart'), {
      height: 260, xLabels: D.weeks.map(D.fmtShort), yTicks: [0, 2, 4, 6, 8], yFormat: (v) => `${v}%`, label: 'Nowcast as known on the selected date',
      bands: [{ lo: D.nowcast.map((v, i) => (i <= wk ? v - D.half70[i] : v)).slice(0, wk + 1), hi: D.nowcast.map((v, i) => v + D.half70[i]).slice(0, wk + 1), color: cssv('--bronze-1') }],
      series: [{ values: shown, color: cssv('--bronze-ink'), width: 2.5 }],
      points: [{ at: wk, value: D.nowcast[wk], color: cssv('--bronze-ink') }],
      markers: [{ at: wk, label: `As known on ${D.fmtShort(date)}` }],
    });
    const qLabel = quarterOf(date), q = D.quarters.find((x) => x.label === qLabel);
    const est = D.nowcast[wk];
    let official;
    if (q && q.official != null) {
      const diff = +(est - q.official).toFixed(1), days = Math.round((q.release - date) / D.DAY);
      official = `<p>The first official estimate for ${qLabel} was <strong>${q.official.toFixed(1)}%</strong>, published ${D.fmtDate(q.release)}: <strong>${days} days later</strong>. Difference ${signed(diff)} points.</p>`;
    } else official = `<p>The first official estimate for ${qLabel} has not been published yet. It is due about three months after the quarter ends.</p>`;
    $('#tm-read').innerHTML = `<span class="meta">On ${D.fmtDate(date)} Nabd estimated ${qLabel} non-oil growth at</span><span class="big num">${est.toFixed(1)}%</span>${official}<p class="meta">Only data available on that date was used. Later revisions do not change this record.</p>`;
    $('#tr-kpis').innerHTML = `<div><strong class="num">${D.mae.toFixed(2)} pp</strong><span>Nabd mean difference</span></div><div><strong class="num">${D.benchmarkMae.toFixed(2)} pp</strong><span>Standard PMI and oil model</span></div><div><strong class="num">${D.meanLead} days</strong><span>Ahead, on average</span></div>`;
    $('#tr').innerHTML = [...D.quarters].reverse().map((r) => `<tr><td class="strong">${r.label}</td><td class="r num">${r.nabd.toFixed(1)}%</td><td class="r num">${r.official == null ? '<span class="muted">Due Jan 2027</span>' : `${r.official.toFixed(1)}%`}</td><td class="r num">${r.err == null ? '—' : `${signed(r.err)} pp`}</td><td class="r num">${r.release ? D.fmtDate(r.release) : '—'}</td><td class="r num">${r.lead == null ? '—' : `${r.lead} days`}</td></tr>`).join('');
  }
  $('#tm-week').addEventListener('input', time);

  // ======================= NETWORK =======================
  const exposure = { 'Logistics and ports': 1.25, 'Energy services': 1.15, Construction: 1, Manufacturing: 0.8, Retail: 0.7, Hospitality: 0.6, 'Real estate': 0.4, 'Financial services': 0.3 };
  const shockAt = (w) => (w < 9 ? 0.04 : w <= 13 ? 0.04 + (w - 8) * 0.11 : Math.max(0.22, 0.59 - (w - 13) * 0.012));
  function network() {
    $('#net-lede').innerHTML = `<strong>${D.systemicCount} firms</strong>, 0.035% of ${int(D.totalFirms)}, carry <strong>${D.systemicShare}%</strong> of non-oil output. Three of the top six are in logistics and energy services, the sectors a Hormuz closure reaches first.`;
    $('#web-meta').textContent = `A sample of ${int(D.nodes.length)} of ${int(D.totalFirms)} firms, clustered by sector`;
    drawWeb(+$('#week').value);
    $('#sys').innerHTML = D.firms.map((f) => `<tr><td>${firmName(f)}</td><td class="r num">${f.esri.toFixed(1)}%</td><td class="r num">${f.banks}</td></tr>`).join('');
  }
  function drawWeb(week) {
    const host = $('#web'); host.innerHTML = '';
    const s = C.el('svg', { viewBox: `0 0 ${D.W} ${D.H}` }, host), shock = shockAt(week);
    D.edges.forEach(([a, b]) => { const A = D.nodes[a], B = D.nodes[b], sys = A.systemic || B.systemic; C.el('line', { x1: A.x, y1: A.y, x2: B.x, y2: B.y, stroke: sys ? cssv('--bronze') : '#d6dade', 'stroke-width': 1, opacity: sys ? 0.22 : 0.7 }, s); });
    let stressed = 0;
    D.nodes.forEach((n) => {
      const st = !n.systemic && n.vul < shock * exposure[n.sector] * 0.55; if (st) stressed++;
      const c = C.el('circle', { cx: n.x, cy: n.y, r: n.systemic ? 6 : st ? 3 : 2.4, fill: n.systemic ? cssv('--bronze') : st ? cssv('--red') : '#c3c8ce', stroke: n.systemic ? '#fff' : 'none', 'stroke-width': 1.5 }, s);
      if (n.firm && role.firms) { const f = D.firms.find((x) => x.id === n.firm); C.el('title', {}, c).textContent = `${f.id} · ${f.sector}, ${f.where} · ${f.esri}% of output at risk`; }
    });
    D.sectorClusters.forEach((name, k) => { const [cx, cy] = D.centres[k]; const t = C.el('text', { x: cx, y: cy < D.H / 2 ? cy - 92 : cy + 104, 'text-anchor': 'middle', fill: cssv('--ink-2'), 'font-size': 14, 'font-weight': 600, 'font-family': cssv('--font') }, s); t.textContent = name; });
    $('#week-out').textContent = D.fmtShort(D.weeks[week]);
    $('#week-meta').textContent = `${int(stressed)} of the ${int(D.nodes.length)} sample firms show payment stress this week: falling inflows, late supplier payments or missed payroll.`;
  }
  $('#week').addEventListener('input', (e) => drawWeb(+e.target.value));

  // ======================= FRAUD =======================
  let fraudView = 'all';
  function fraud() {
    const allowed = role.fraud;
    $('#fraud-restricted').hidden = allowed; $('#fraud-body').hidden = !allowed;
    $('#str-btn').disabled = !allowed; $('#alert-btn').disabled = !allowed;
    if (!allowed) {
      $('#fraud-lede').textContent = 'Fraud cases hold account-level data.';
      $('#fraud-restricted').innerHTML = `<span class="lock"></span><span><strong>Restricted for ${role.name}.</strong> Fraud cases are visible to Payment Systems and the Governor’s Office only. Switch “Viewing as” to one of those roles to see how the case looks.</span>`;
      return;
    }
    fraudSystem();
    const r = D.ring;
    $('#case-lede').innerHTML = `AED ${r.aed.toFixed(2)} m from ${r.victims} victims passed through <strong>${r.accounts} accounts at ${D.banks.length} banks</strong> in ${r.days} days, a median of ${r.medianHoldMin} minutes in each account. The banks’ own systems flagged ${r.ownFlags} of the ${r.accounts}.`;
    $('#banks').innerHTML = D.banks.map((b) => `<tr><td>${b.name}</td><td class="r num">${b.accounts}</td><td class="r num">AED ${b.aed.toFixed(2)} m</td><td class="r num">${b.ownFlags}</td></tr>`).join('');
    $('#banks-total').innerHTML = `<tr><td>All banks</td><td class="r num">${r.accounts}</td><td class="r num">AED ${r.aed.toFixed(2)} m</td><td class="r num">${r.ownFlags}</td></tr>`;
    $('#banks-note').textContent = `No single bank sees more than ${Math.max(...D.banks.map((b) => b.accounts))} of the ${r.accounts} accounts. Only the central bank sees the ring whole.`;
    drawLanes();
  }
  function drawLanes() {
    const host = $('#lanes'); host.innerHTML = '';
    const Wd = 1000, Ht = 470, laneW = Wd / D.banks.length, ys = [118, 212, 306, 392], only = fraudView === 'all' ? null : +fraudView;
    const s = C.el('svg', { viewBox: `0 0 ${Wd} ${Ht}` }, host), F = cssv('--font');
    D.banks.forEach((b, k) => {
      if (k % 2 === 0) C.el('rect', { x: k * laneW, y: 30, width: laneW, height: Ht - 30, fill: cssv('--sunk') }, s);
      const t = C.el('text', { x: k * laneW + laneW / 2, y: 20, 'text-anchor': 'middle', 'font-family': F, 'font-size': 14, 'font-weight': 600, fill: only === null || only === k ? cssv('--ink') : '#9aa1a9' }, s); t.textContent = b.name;
    });
    const lab = (txt, y) => { const t = C.el('text', { x: 12, y, 'font-family': F, 'font-size': 13, fill: cssv('--muted') }, s); t.textContent = txt; };
    lab(`${D.ring.victims} victims pay in`, 56); lab('Sent abroad', Ht - 12);
    const pos = {};
    D.accts.forEach((a) => { const peers = D.accts.filter((x) => x.bank === a.bank && x.layer === a.layer), i = peers.indexOf(a); pos[a.id] = [a.bank * laneW + laneW * ((i + 1) / (peers.length + 1)), ys[a.layer] + (i % 2 ? 10 : -10)]; });
    const seen = (id) => only === null || D.accts.find((x) => x.id === id).bank === only;
    D.accts.filter((a) => a.layer === 0).forEach((a) => { const [x, y] = pos[a.id]; C.el('path', { d: `M${x} 68 L${x} ${y - 7}`, stroke: '#9aa1a9', 'stroke-dasharray': '2 3', opacity: seen(a.id) ? 1 : 0.15 }, s); });
    D.accts.filter((a) => a.layer === 3).forEach((a) => { const [x, y] = pos[a.id]; C.el('path', { d: `M${x} ${y + 7} L${x} ${Ht - 30}`, stroke: cssv('--red'), 'stroke-width': 1.5, opacity: seen(a.id) ? 1 : 0.15 }, s); });
    D.links.forEach(([f, t]) => { const [x1, y1] = pos[f], [x2, y2] = pos[t], my = (y1 + y2) / 2, both = seen(f) && seen(t), one = seen(f) || seen(t); C.el('path', { d: `M${x1} ${y1} C${x1} ${my} ${x2} ${my} ${x2} ${y2}`, fill: 'none', stroke: both ? cssv('--bronze') : '#b5bbc2', 'stroke-width': both ? 1.5 : 1, opacity: both ? 0.85 : one ? 0.6 : 0.08, class: both ? 'flow' : null }, s); });
    D.accts.forEach((a) => {
      const [x, y] = pos[a.id], vis = seen(a.id);
      const flagged = only !== null && vis && a.layer === 1 && D.accts.filter((x2) => x2.bank === a.bank && x2.layer === 1).indexOf(a) < D.banks[a.bank].ownFlags;
      const c = C.el('circle', { cx: x, cy: y, r: 6, fill: flagged ? cssv('--amber') : vis ? cssv('--ink') : '#c3c8ce', stroke: '#fff', 'stroke-width': 1.5, opacity: vis ? 1 : 0.4 }, s);
      C.el('title', {}, c).textContent = `${a.id} · ${D.banks[a.bank].name}`;
    });
    $('#ring-meta').textContent = only === null
      ? 'Money enters at the top, passes through two layers of accounts and leaves the country at the bottom. Each dot is one account.'
      : `${D.banks[only].name} sees ${D.banks[only].accounts} accounts and flags ${D.banks[only].ownFlags} (amber). To ${D.banks[only].name}, the grey lines are ordinary payments to customers of other banks.`;
  }
  $$('#fraud .seg button').forEach((b) => b.addEventListener('click', () => { fraudView = b.dataset.view; $$('#fraud .seg button').forEach((x) => x.setAttribute('aria-pressed', x === b)); drawLanes(); }));
  $('#alert-btn').addEventListener('click', () => toast('Risk alert sent to Banks A to F for 41 accounts. Logged in Governance.'));
  $('#str-btn').addEventListener('click', () => toast('Report drafted on premise for the Financial Intelligence Unit. Awaits sign-off.'));

  // ======================= GOVERNANCE =======================
  function gov() {
    const u = D.usage;
    $('#gov-lede').innerHTML = `Today: ${int(u.runs)} model runs and ${u.llmCalls} language-model calls. ${u.hostedCalls} calls went to Azure UAE North, all on aggregates. <strong>${u.recordsOut} firm or account records left CBUAE.</strong>`;
    $('#gov-kpis').innerHTML = [['Model runs today', int(u.runs)], ['Language-model calls', u.llmCalls], ['Sent to Azure UAE North', u.hostedCalls], ['Firm records sent out', u.recordsOut]].map(([l, v]) => `<div class="kpi"><div class="kpi-label">${l}</div><div class="kpi-value num">${v}</div></div>`).join('');
    $('#gov-kpis').style.marginBottom = '24px';
    $('#models').innerHTML = D.models.map((m) => `<tr><td class="strong">${m.name}</td><td>${m.kind}</td><td><span class="pill">${m.tier}</span></td><td>${m.data}</td><td class="r num">${m.validated}</td><td>${m.owner}</td></tr>`).join('');
    $('#audit').innerHTML = D.audit.map((a) => `<tr><td class="num">${a.time}</td><td>${a.who}</td><td>${a.what}</td><td>${a.tier}</td><td>${a.approved.startsWith('Pending') ? `<span class="pill amber">${a.approved}</span>` : a.approved}</td></tr>`).join('');
    $('#roles').innerHTML = D.roles.map((r) => `<tr${r.id === role.id ? ' style="background:var(--bronze-1)"' : ''}><td class="strong">${r.name}${r.id === role.id ? ' <span class="sub">You are viewing as this role</span>' : ''}</td><td>${r.firms ? 'Visible' : '<span class="lock">Hidden</span>'}</td><td>${r.fraud ? 'Visible' : '<span class="lock">Hidden</span>'}</td></tr>`).join('');
  }

  // ======================= SCENARIO PLAYBACK (the shock moving through the network) =======================
  let fanChart = null, playDay = 0, playing = false, playTimer = null, playNodes = [], playEdges = [], spans = [], cursor = null;
  function computeSpans() {
    const sev = Math.min(1.5, Math.abs(result.avg) / 1.9), facility = result.response === 'facility';
    return D.nodes.map((n) => {
      if (n.firm) { const f = D.firms.find((x) => x.id === n.firm), d = result.breakDay(f); return d ? [d, Math.min(90, result.days + 28)] : null; }
      const e = exposure[n.sector];
      if (n.vul > e * 0.62 * sev) return null;
      const start = Math.round(1 + (1.3 - e) * 14 + n.vul * 18);
      if (start > result.days + 5) return null;
      return [start, Math.min(90, Math.round(result.days + (facility ? 8 : 18) + n.vul * 20))];
    });
  }
  function setupPlay() {
    spans = computeSpans();
    const host = $('#play-web'); host.innerHTML = '';
    const s = C.el('svg', { viewBox: `0 0 ${D.W} ${D.H}` }, host);
    playEdges = D.edges.map(([a, b]) => ({ a, b, el: C.el('line', { x1: D.nodes[a].x, y1: D.nodes[a].y, x2: D.nodes[b].x, y2: D.nodes[b].y, stroke: '#d6dade', 'stroke-width': 1 }, s) }));
    playNodes = D.nodes.map((n) => C.el('circle', { cx: n.x, cy: n.y, r: n.systemic ? 6 : 2.6, fill: '#c3c8ce', stroke: n.systemic ? '#fff' : 'none', 'stroke-width': 1.5 }, s));
    D.sectorClusters.forEach((name, k) => { const [cx, cy] = D.centres[k]; const t = C.el('text', { x: cx, y: cy < D.H / 2 ? cy - 92 : cy + 104, 'text-anchor': 'middle', fill: cssv('--ink-2'), 'font-size': 14, 'font-weight': 600, 'font-family': cssv('--font') }, s); t.textContent = name; });
    if (fanChart) { cursor = C.el('line', { y1: 20, y2: 274, stroke: cssv('--red'), 'stroke-width': 1.5, opacity: 0 }, fanChart.svg); }
    drawDay(Math.min(playDay, 90));
  }
  function drawDay(t) {
    playDay = t; $('#play-day').value = t; $('#play-day-out').textContent = t;
    let stressed = 0, recovering = 0;
    const state = spans.map((sp) => (!sp ? 0 : t >= sp[0] && t <= sp[1] ? 2 : t > sp[1] && t <= sp[1] + 12 ? 1 : 0));
    state.forEach((st, i) => {
      const n = D.nodes[i]; if (st === 2) stressed++; if (st === 1) recovering++;
      playNodes[i].setAttribute('fill', st === 2 ? cssv('--red') : st === 1 ? cssv('--bronze') : n.systemic ? '#8a9098' : '#c3c8ce');
      playNodes[i].setAttribute('r', n.systemic ? 6 : st === 2 ? 3.4 : 2.6);
    });
    playEdges.forEach((e) => { const hot = state[e.a] === 2 && state[e.b] === 2; e.el.setAttribute('stroke', hot ? cssv('--red') : '#d6dade'); e.el.setAttribute('opacity', hot ? 0.5 : 1); });
    if (cursor && fanChart) { const x = fanChart.x(t); cursor.setAttribute('x1', x); cursor.setAttribute('x2', x); cursor.setAttribute('opacity', t > 0 ? 0.8 : 0); }
    const outOfCash = D.firms.slice(0, 5).filter((f) => { const d = result.breakDay(f); return d && d <= t; }).length;
    const banksNow = t < 10 ? 0 : t <= result.days + 12 ? result.banks : Math.max(0, result.banks - Math.floor((t - result.days - 12) / 6));
    $('#play-stats').innerHTML = [
      ['Day', `${t} of 90`, t <= result.days ? 'Strait closed' : 'Strait reopened'],
      ['Non-oil output vs baseline', `${signed(result.median[t])} pp`, 'median of 1,000 runs'],
      ['Firms showing payment stress', int(Math.round((stressed / D.nodes.length) * D.totalFirms)), `${stressed} of ${D.nodes.length} in the sample`],
      ['Recovering', int(Math.round((recovering / D.nodes.length) * D.totalFirms)), 'firms back to normal payments'],
      ['Systemic firms out of cash', `${outOfCash} of 5`, 'most exposed firms'],
      ['Banks below 100% liquidity cover', `${banksNow} of ${D.banksCount}`, result.response === 'facility' ? 'with the facility' : 'no facility'],
    ].map(([k, v, s]) => `<div><dt>${k}</dt><dd class="num">${v}</dd><span>${s}</span></div>`).join('');
  }
  function stopPlay() { playing = false; clearInterval(playTimer); $('#play-btn').textContent = 'Play'; $('#play-btn').setAttribute('aria-pressed', 'false'); }
  $('#play-btn').addEventListener('click', () => {
    if (playing) return stopPlay();
    if (playDay >= 90) drawDay(0);
    playing = true; $('#play-btn').textContent = 'Pause'; $('#play-btn').setAttribute('aria-pressed', 'true');
    const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
    playTimer = setInterval(() => { if (playDay >= 90) return stopPlay(); drawDay(Math.min(90, playDay + (reduce ? 10 : 1))); }, reduce ? 400 : 70);
  });
  $('#play-day').addEventListener('input', (e) => { stopPlay(); drawDay(+e.target.value); });

  // ======================= FORECASTING =======================
  function forecast() {
    const better = Math.round((1 - D.ensemble.h1 / D.benchmarks[0].h1) * 100);
    $('#fc-lede').innerHTML = `Four models trained on daily payment data forecast non-oil growth up to four quarters ahead. Combined, they are <strong>${better}% more accurate</strong> one quarter ahead than the standard PMI and oil model, and they retrain every night.`;
    const labels = [...D.hist.map((h) => h.label), ...D.fcst.map((f) => f.label)], nh = D.hist.length;
    const last = D.hist.at(-1).value;
    const val = labels.map((_, i) => (i < nh ? D.hist[i].value : D.fcst[i - nh].value));
    const band = (k, sgn) => labels.map((_, i) => (i < nh - 1 ? val[i] : i === nh - 1 ? last : val[i] + sgn * D.fcst[i - nh][k]));
    const histLine = val.map((v, i) => (i < nh ? v : null)), fLine = val.map((v, i) => (i >= nh - 1 ? (i === nh - 1 ? last : v) : null));
    C.render($('#fc-chart'), {
      height: 290, xLabels: labels.map((l) => l.replace(' 20', ' ’')), yTicks: [0, 2, 4, 6, 8], yFormat: (v) => `${v}%`, label: 'Quarterly non-oil growth with forecast fan',
      bands: [{ lo: band('h90', -1), hi: band('h90', 1), color: cssv('--bronze-1') }, { lo: band('h70', -1), hi: band('h70', 1), color: cssv('--bronze-2') }],
      series: [{ values: histLine, color: cssv('--ink'), width: 2 }, { values: fLine, color: cssv('--bronze-ink'), width: 2.5, dash: '6 4' }],
      points: D.hist.map((h, i) => ({ at: i, value: h.value, color: h.official ? cssv('--ink') : cssv('--bronze-ink'), r: 3.5 })),
      markers: [{ at: nh - 1, label: 'Forecast from here' }],
      tip: (i) => (i < nh ? `${labels[i]}: ${val[i].toFixed(1)}% ${D.hist[i].official ? '(first official estimate)' : '(Nabd estimate, official due Jan 2027)'}` : `${labels[i]} forecast: ${val[i].toFixed(1)}% (70% range ${(val[i] - D.fcst[i - nh].h70).toFixed(1)} to ${(val[i] + D.fcst[i - nh].h70).toFixed(1)})`),
    });
    $('#fc-legend').innerHTML = `<span><i class="sw sw-line" style="background:${cssv('--ink')}"></i>History</span><span><i class="sw sw-line" style="background:${cssv('--bronze-ink')}"></i>Forecast</span><span><i class="sw" style="background:${cssv('--bronze-2')}"></i>70%</span><span><i class="sw" style="background:${cssv('--bronze-1')}"></i>90%</span>`;
    $('#fc-strip').innerHTML = D.fcst.map((f) => `<div><span class="meta">${f.label}</span><strong class="num">${f.value.toFixed(1)}%</strong><span class="meta">70%: ${(f.value - f.h70).toFixed(1)} to ${(f.value + f.h70).toFixed(1)}</span></div>`).join('');
    const fm = Math.max(...D.features.map((f) => f.v));
    $('#feat').innerHTML = D.features.map((f) => `<li><span>${f.name}</span><span class="hb"><i style="width:${(f.v / fm) * 100}%"></i></span><b class="num">${f.v.toFixed(2)}</b></li>`).join('');
    $('#lb').innerHTML = `<tr class="lead"><td><span class="strong">${D.ensemble.name}</span><span class="sub">Weighted combination of the four models below</span></td><td class="r num">100%</td><td class="r num strong">${D.ensemble.h1.toFixed(2)}</td><td class="r num strong">${D.ensemble.h4.toFixed(2)}</td><td class="r num">15 Nov 22:00</td></tr>`
      + D.fmodels.map((m) => `<tr><td><span class="strong">${m.name}</span><span class="sub">${m.kind}</span></td><td class="r num">${m.weight}%</td><td class="r num">${m.h1.toFixed(2)}</td><td class="r num">${m.h4.toFixed(2)}</td><td class="r num">${m.trained}</td></tr>`).join('')
      + D.benchmarks.map((b) => `<tr class="bench"><td><span>${b.name}</span><span class="sub">Benchmark</span></td><td class="r">—</td><td class="r num">${b.h1.toFixed(2)}</td><td class="r num">${b.h4.toFixed(2)}</td><td class="r">—</td></tr>`).join('');
    C.render($('#hz-chart'), {
      height: 240, xLabels: D.horizons, yTicks: [0, 0.5, 1, 1.5], yFormat: (v) => v.toFixed(1), label: 'Forecast error by horizon',
      series: D.horizonErr.map((h, k) => ({ values: h.values, color: h.main ? cssv('--bronze-ink') : k === 1 ? '#6b7178' : '#a3a9b0', width: h.main ? 2.5 : 1.75, dash: h.main ? null : k === 2 ? '3 3' : null })),
      points: D.horizonErr[0].values.map((v, i) => ({ at: i, value: v, color: cssv('--bronze-ink'), r: 3.5 })),
      tip: (i) => D.horizonErr.map((h) => `${h.name.split(' ')[0]} ${h.values[i].toFixed(2)}`).join(' · '),
    });
    $('#hz-legend').innerHTML = `<span><i class="sw sw-line" style="background:${cssv('--bronze-ink')}"></i>Nabd</span><span><i class="sw sw-line" style="background:#6b7178"></i>PMI and oil</span><span><i class="sw sw-line" style="background:#a3a9b0"></i>Autoregression</span>`;
  }
  $('#retrain-btn').addEventListener('click', () => {
    const b = $('#retrain-btn'); b.disabled = true; b.textContent = 'Retraining on 2,340 days of data…';
    setTimeout(() => { b.disabled = false; b.textContent = 'Retrain models'; toast('Models retrained on premise. Ensemble error unchanged at 0.21 points; weights rebalanced.'); }, 1400);
  });

  // ======================= INVESTMENT =======================
  let ddSelected = 'M-112';
  function invest() {
    const allowed = role.id === 'gov' || role.id === 'inv';
    $('#inv-restricted').hidden = allowed; $('#inv-body').hidden = !allowed; $('#ic-btn').disabled = !allowed;
    if (!allowed) { $('#inv-lede').textContent = 'Portfolio and mandate data.'; $('#inv-restricted').innerHTML = `<span class="lock"></span><span><strong>Restricted for ${role.name}.</strong> The investment workspace is visible to the Investment Department and the Governor’s Office.</span>`; return; }
    const f = (result.days / 30) * (result.response === 'facility' ? 0.85 : 1);
    const rows = D.allocation.map((a) => ({ ...a, ret: +(a.hormuz30 * f).toFixed(1) }));
    const total = rows.reduce((s, a) => s + (a.w * a.ret) / 100, 0), aedBn = (total / 100) * D.notional;
    $('#inv-lede').innerHTML = `A notional AED ${D.notional} bn reserve portfolio, linked to Nabd’s live scenario. Under run ${runNo} (Hormuz ${result.days} days, Brent $${result.brent}) it moves <strong>${signed(total, 2)}%</strong>, about AED ${signed(aedBn, 2)} bn; equities and gold move most.`;
    $('#alloc-meta').textContent = `Scenario run ${runNo}. Returns are the median of 1,000 runs over 90 days.`;
    const mr = Math.max(...rows.map((a) => Math.abs(a.ret)));
    $('#alloc').innerHTML = rows.map((a) => `<tr><td>${a.name}</td><td class="r num">${a.w}%</td><td><span class="dbar"><i class="${a.ret < 0 ? 'neg' : 'pos'}" style="width:${(Math.abs(a.ret) / mr) * 50}%"></i></span></td><td class="r num ${a.ret < 0 ? 'worse' : a.ret > 0 ? 'better' : ''}">${a.ret === 0 ? '0.0%' : `${signed(a.ret)}%`}</td></tr>`).join('');
    $('#alloc-total').innerHTML = `<tr><td>Portfolio</td><td class="r num">100%</td><td class="r num">AED ${signed(aedBn, 2)} bn</td><td class="r num ${total < 0 ? 'worse' : 'better'}">${signed(total, 2)}%</td></tr>`;
    $('#pipeline').innerHTML = D.stages.map((st, k) => { const items = D.mandates.filter((m) => m.stage === k); return `<div class="stage"><div class="stage-head"><span>${st}</span><b class="num">${items.length}</b></div>${items.map((m) => `<button type="button" class="mandate${m.id === ddSelected ? ' on' : ''}" data-id="${m.id}"><span class="m-name">${m.name}</span><span class="m-meta num">AED ${m.aed.toFixed(1)} bn · ${m.owner}</span><span class="m-next">${m.next}</span></button>`).join('')}</div>`; }).join('');
    $$('#pipeline .mandate').forEach((b) => b.addEventListener('click', () => { ddSelected = b.dataset.id; if (!D.mandates.find((m) => m.id === ddSelected).dd) toast('Due diligence for this mandate is not in the prototype. Showing the emerging-market mandate.'); ddSelected = 'M-112'; invest(); }));
    const open = D.ddFindings.filter((x) => x.sev === 'high').length;
    $('#dd-open').textContent = `${open} findings need answers`;
    $('#dd').innerHTML = D.ddFindings.map((x) => `<li class="f-${x.sev}"><span class="f-tag">${{ high: 'Needs an answer', warn: 'Check', ok: 'Clear' }[x.sev]}</span><p>${x.text}<span class="src">Source: ${x.src}</span></p></li>`).join('');
    $('#mgrs').innerHTML = D.managers.map((m) => `<li><div class="mgr-top"><span class="strong">${m.name}</span><b class="num">${m.score}</b></div><span class="hb"><i style="width:${m.score}%"></i></span><span class="sub">${m.aum} · ${m.track}</span>${m.open ? `<span class="pill red">${m.open} open findings</span>` : '<span class="pill green">No open findings</span>'}</li>`).join('');
  }
  $('#ic-btn').addEventListener('click', () => toast('Committee pack drafted: allocation, scenario impact and due-diligence findings, every figure cited. Awaits review.'));

  // ======================= FRAUD DETECTION SYSTEM =======================
  let scored = D.fraudKpis.scored, ticker = null;
  function fraudSystem() {
    $('#fraud-lede').innerHTML = `Nabd scores every Aani instant payment across all banks as it happens, and sees patterns that no single bank can. Today: <strong>${D.fraudKpis.alerts} alerts</strong>, AED ${D.heldAed.toFixed(2)} m held for review in the top six.`;
    const kp = () => [['Payments scored today', int(scored), 'Aani, all banks, live'], ['Median scoring time', `${D.fraudKpis.medianMs} ms`, 'before the payment settles'], ['Alerts today', D.fraudKpis.alerts, '6 above 0.70 risk'], ['Held for review', `AED ${D.heldAed.toFixed(2)} m`, 'top six alerts']]
      .map(([l, v, s]) => `<div class="kpi"><div class="kpi-label">${l}</div><div class="kpi-value num">${v}</div><div class="kpi-sub">${s}</div></div>`).join('');
    $('#fraud-kpis').innerHTML = kp();
    clearInterval(ticker);
    if (!matchMedia('(prefers-reduced-motion: reduce)').matches) ticker = setInterval(() => { if ($('#fraud').hidden) return clearInterval(ticker); scored += 12 + Math.floor(Math.random() * 30); const v = $('#fraud-kpis .kpi-value'); if (v) v.textContent = int(scored); }, 300);
    $('#queue').innerHTML = D.alerts.map((a) => `<tr${a.link ? ' class="link-row" data-case="1"' : ''}><td class="strong">${a.id}</td><td>${a.typ}<span class="sub">${a.scope}</span></td><td class="r num">${a.banks}</td><td class="r num">AED ${a.aed.toFixed(2)} m</td><td class="r num"><span class="score"><i style="width:${a.score * 100}%"></i></span>${a.score.toFixed(2)}</td><td class="r"><span class="pill ${a.tone}">${a.status}</span></td></tr>`).join('');
    $$('#queue tr[data-case]').forEach((tr) => tr.addEventListener('click', () => document.querySelector('.case-head').scrollIntoView({ behavior: 'smooth', block: 'start' })));
    const d = D.detection, pct = (v) => `${Math.round(v * 100)}%`;
    $('#perf').innerHTML = [['Rings caught', 'recall', d.central.recall, d.single.recall], ['Alerts that are real fraud', 'precision', d.central.precision, d.single.precision]]
      .map(([t, k, c, s]) => `<div class="perf"><span class="perf-t">${t}</span><div class="perf-row"><span>Central bank view</span><span class="hb"><i style="width:${c * 100}%"></i></span><b class="num">${pct(c)}</b></div><div class="perf-row dim"><span>One bank alone</span><span class="hb"><i style="width:${s * 100}%"></i></span><b class="num">${pct(s)}</b></div></div>`).join('');
    const tm = Math.max(...D.typologies.map((t) => t.n));
    $('#typ').innerHTML = D.typologies.map((t) => `<li><span>${t.name}</span><span class="hb"><i style="width:${(t.n / tm) * 100}%"></i></span><b class="num">${t.n}</b></li>`).join('');
  }

  // ======================= MODEL ROOM =======================
  let lens = 'all';
  function room() {
    const inv = D.inventory;
    $('#inv-strip').innerHTML = [
      ['Models in production', inv.production, 'across 3 model families'],
      ['Need attention', inv.attention, 'data coverage and a new scam pattern'],
      ['Challengers ready', inv.challengers, 'awaiting validation to promote'],
      ['Validations overdue', inv.overdue, 'next due 28 Apr 2027'],
      ['Firm records sent out today', D.usage.recordsOut, 'everything runs on premise'],
    ].map(([k, v, s]) => `<div><dt>${k}</dt><dd class="num">${v}</dd><span>${s}</span></div>`).join('');
    const cols = ['Data in', 'Models', 'What it says today', 'How it is performing', 'Governance'];
    const tone = (t) => ({ good: 'better', warn: 'warnc', neutral: '' }[t] || '');
    const lanes = D.lanes.map((l) => {
      const data = `<ul class="mini-feeds">${l.data.map((d) => `<li><i class="sd ${d.ok ? 'ok' : 'bad'}" aria-label="${d.ok ? 'current' : 'below threshold'}"></i><span class="nm">${d.name}${d.isNew ? ' <em class="newtag">New input</em>' : ''}</span><span class="vl num">${d.vol}</span></li>`).join('')}</ul>`;
      let model = `<div class="mdl"><span class="mdl-k">Champion</span><span class="mdl-n">${l.champion.name}</span><span class="mdl-s">${l.champion.note}</span></div><div class="mdl chall"><span class="mdl-k">${l.id === 'res' ? 'Also running' : 'Challenger'}</span><span class="mdl-n">${l.challenger.name}</span><span class="mdl-s">${l.challenger.note}</span></div>`;
      if (l.champErr) model += `<div class="chart" id="cc-${l.id}"></div><p class="cell-note">Challenger lower error in <strong>${l.challErr.filter((v, i) => v < l.champErr[i]).length} of the last 12 weeks</strong>.</p><button class="btn small" type="button" data-act="promote">Request validation to promote</button>`;
      if (l.tradeoff) { const t = l.tradeoff; model += `<div class="trade">${[['Rings caught', 'recall'], ['Alerts that are real', 'precision']].map(([k, m]) => `<div class="tr-row"><span>${k}</span><span class="hb"><i style="width:${t.champ[m] * 100}%"></i></span><b class="num">${Math.round(t.champ[m] * 100)}%</b></div><div class="tr-row dim"><span>Challenger</span><span class="hb"><i style="width:${t.chall[m] * 100}%"></i></span><b class="num">${Math.round(t.chall[m] * 100)}%</b></div>`).join('')}</div><p class="cell-note">Challenger catches about 6 more rings a quarter but sends analysts 22% more alerts.</p><button class="btn small" type="button" data-act="shadow">Run challenger in shadow mode</button>`; }
      let out = '';
      if (l.id === 'gdp') out = `<span class="out-k">Non-oil growth, Q4 2026</span><span class="out-v num">${D.nowcast.at(-1).toFixed(1)}%</span><span class="out-s"><span class="worse">${signed(D.weekChange, 2)} pp</span> this week · 70% range ${(D.nowcast.at(-1) - D.half70.at(-1)).toFixed(1)} to ${(D.nowcast.at(-1) + D.half70.at(-1)).toFixed(1)}</span><div class="chart" id="out-gdp"></div><p class="cell-note">News coverage of shipping disruption pulled the forecast down 0.10 pp this week.</p>`;
      if (l.id === 'fraud') out = `<span class="out-k">Alerts today across all banks</span><span class="out-v num">${D.fraudKpis.alerts}</span><span class="out-s">AED ${D.heldAed.toFixed(2)} m held for review</span><ul class="out-list">${D.alerts.slice(0, 3).map((a) => `<li><span>${a.typ}</span><span class="num">${a.score.toFixed(2)}</span></li>`).join('')}</ul><p class="cell-note">${role.fraud ? 'Case R-2611-07: a mule ring across 6 banks, AED 4.82 m.' : '<span class="lock">Case details restricted for your role</span>'}</p>`;
      if (l.id === 'res') { const f = result.days / 30, tot = D.allocation.reduce((a, x) => a + (x.w * x.hormuz30 * f) / 100, 0); out = `<span class="out-k">Notional portfolio under scenario run ${runNo}</span><span class="out-v num ${tot < 0 ? 'worse' : ''}">${signed(tot, 2)}%</span><span class="out-s">Hormuz ${result.days} days · equities ${signed(-6.1 * f)}%, gold ${signed(5.8 * f)}%</span><div class="budget"><span class="meta">Active risk budget used</span><span class="hb big-hb"><i style="width:62%"></i></span><span class="num">62%</span></div><p class="cell-note">Emerging-market debt mandate: 2 due-diligence findings need answers.</p>`; }
      const perf = `<ul class="perf-list">${l.perf.map((p) => `<li><span class="pk">${p.k}</span><span class="pv num ${tone(p.tone)}">${p.v}</span><span class="ps">${p.s}</span></li>`).join('')}</ul>`;
      const g = l.gov;
      const gov = `<span class="pill">${g.tier}</span><dl class="gov-dl"><dt>Validated</dt><dd class="num">${g.validated}</dd><dt>Next validation</dt><dd class="num">${g.next}</dd><dt>Approved by</dt><dd>${g.approver}</dd></dl><ul class="checks">${g.checks.map((c) => `<li>${c}</li>`).join('')}</ul>`;
      return `<section class="lane" aria-labelledby="lane-${l.id}">
        <header class="lane-head"><h2 id="lane-${l.id}">${l.title}</h2><span class="pill ${l.tone}">${l.status}</span><span class="why">${l.why}</span><span class="owner">${l.owner}</span><a class="link" href="${l.route}">Open</a></header>
        <svg class="lane-flow" viewBox="0 0 1000 4" preserveAspectRatio="none" aria-hidden="true"><line x1="0" y1="2" x2="1000" y2="2" class="flow-line"/></svg>
        <div class="lane-row">
          <div class="cell" data-col="data">${data}</div>
          <div class="cell" data-col="model">${model}</div>
          <div class="cell" data-col="out">${out}</div>
          <div class="cell" data-col="perf">${perf}</div>
          <div class="cell" data-col="gov">${gov}</div>
        </div>
      </section>`;
    }).join('');
    const grid = $('#room-grid'); grid.dataset.lens = lens;
    grid.innerHTML = `<div class="room-cols">${cols.map((c, i) => `<span data-col="${['data', 'model', 'out', 'perf', 'gov'][i]}">${c}</span>`).join('')}</div>${lanes}`;
    const g = D.lanes[0];
    C.render($('#cc-gdp'), {
      height: 110, padR: 4, xLabels: g.champErr.map((_, i) => (i === 11 ? 'This week' : `${12 - i} wk`)), yTicks: [0.15, 0.2, 0.25, 0.3], yFormat: (v) => v.toFixed(2), label: 'Champion and challenger error, last 12 weeks',
      series: [{ values: g.champErr, color: '#8a9098', width: 1.75 }, { values: g.challErr, color: cssv('--bronze-ink'), width: 2.25 }],
      tip: (i) => `Champion ${g.champErr[i].toFixed(2)} · challenger ${g.challErr[i].toFixed(2)}`,
    });
    const nh = D.hist.length, labels = [D.hist.at(-1).label, ...D.fcst.map((f) => f.label)], v = [D.hist.at(-1).value, ...D.fcst.map((f) => f.value)];
    const b = (k, sg) => v.map((x, i) => (i === 0 ? x : x + sg * D.fcst[i - 1][k]));
    C.render($('#out-gdp'), {
      height: 110, padR: 4, xLabels: labels.map((l) => l.replace(' 20', ' ’')), yTicks: [0, 3, 6], yFormat: (x) => `${x}%`, label: 'Four-quarter forecast fan',
      bands: [{ lo: b('h90', -1), hi: b('h90', 1), color: cssv('--bronze-1') }, { lo: b('h70', -1), hi: b('h70', 1), color: cssv('--bronze-2') }],
      series: [{ values: v, color: cssv('--bronze-ink'), width: 2 }],
    });
    $$('#room-grid [data-act]').forEach((btn) => btn.addEventListener('click', () => toast(btn.dataset.act === 'promote' ? 'Validation request sent to Model Validation for Ensemble v3.3. The champion stays live until sign-off.' : 'Graph model v2.5 now scores in shadow mode. Its alerts are logged for comparison and not sent to banks.')));
  }
  $$('#lens button').forEach((b) => b.addEventListener('click', () => { lens = b.dataset.lens; $$('#lens button').forEach((x) => x.setAttribute('aria-pressed', x === b)); $('#room-grid').dataset.lens = lens; }));
  $('#board-btn').addEventListener('click', () => toast('Board report drafted: model inventory, validation status, monitoring breaches and challengers, every figure cited. Awaits the CRO’s review.'));

  // ======================= ROUTER =======================
  const screens = { room, home, scenarios, nowcast, forecast, invest, time, network, fraud, gov };
  const titles = { room: 'Model room', forecast: 'Forecasting', invest: 'Investment', home: 'Briefing', scenarios: 'Scenarios', nowcast: 'Nowcast', time: 'Time machine', network: 'Network', fraud: 'Fraud detection', gov: 'Governance' };
  function route() {
    const id = (location.hash || '#room').slice(1), key = screens[id] ? id : 'room';
    $$('.screen').forEach((s) => (s.hidden = s.id !== key));
    $$('.nav a').forEach((a) => (a.dataset.route === key ? a.setAttribute('aria-current', 'page') : a.removeAttribute('aria-current')));
    document.title = `${titles[key]} · Nabd · Central Bank of the UAE`;
    screens[key]();
  }
  window.addEventListener('hashchange', () => { route(); window.scrollTo(0, 0); });
  let rz; window.addEventListener('resize', () => { clearTimeout(rz); rz = setTimeout(route, 150); });
  (document.fonts ? document.fonts.ready : Promise.resolve()).then(() => { route(); window.scrollTo(0, 0); });
})();
