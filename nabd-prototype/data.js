// Nabd prototype v3 — illustrative data and a small synthetic model. Nothing here is real CBUAE data.
// Totals shown on screen are computed from these rows; console.assert checks that the parts agree.
(() => {
  const rng = (seed) => () => { seed |= 0; seed = (seed + 0x6d2b79f5) | 0; let t = Math.imul(seed ^ (seed >>> 15), 1 | seed); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
  const gaussFrom = (r) => () => { let u = 0, v = 0; while (!u) u = r(); while (!v) v = r(); return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v); };
  const DAY = 86400000;
  const fmtDate = (d) => d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' });
  const fmtShort = (d) => d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', timeZone: 'UTC' });

  // ---------- roles and the information barrier ----------
  const roles = [
    { id: 'gov', name: 'Governor’s Office', firms: true, fraud: true },
    { id: 'inv', name: 'Investment Department', firms: false, fraud: false },
    { id: 'fs', name: 'Financial Stability', firms: true, fraud: false },
    { id: 'ps', name: 'Payment Systems', firms: false, fraud: true },
  ];

  // ---------- nowcast: weekly estimate of current-quarter non-oil growth, y/y % ----------
  const start = new Date(Date.UTC(2026, 0, 5));
  const nowcast = [5.0, 5.1, 4.9, 5.0, 5.2, 5.0, 4.9, 5.0, 4.8, 3.9, 2.9, 2.4, 2.0, 1.7, 1.5, 1.3, 1.2, 1.1, 1.2, 1.3, 1.2, 1.1, 1.2, 1.3, 1.4, 1.3, 1.4, 1.5, 1.4, 1.5, 1.6, 1.5, 1.6, 1.7, 1.6, 1.5, 1.6, 1.7, 1.6, 1.7, 1.6, 1.6, 1.7, 1.6, 1.65, 1.4];
  const weeks = nowcast.map((_, i) => new Date(start.getTime() + 7 * i * DAY));
  const half70 = nowcast.map((_, i) => (i >= 9 && i <= 14 ? 0.75 : 0.45));
  const half90 = half70.map((h) => +(h * 1.75).toFixed(2));
  const weekChange = +(nowcast.at(-1) - nowcast.at(-2)).toFixed(2);

  // what moved this week's estimate: the contribution of each data release (points)
  const news = [
    { release: 'UAEFTS contractor payments', when: 'Daily, to 15 Nov', pp: -0.12 },
    { release: 'Card spending', when: 'Daily, to 14 Nov', pp: -0.07, note: '81% of volume; 2 acquirers late' },
    { release: 'Freight and port payments', when: 'Daily, to 15 Nov', pp: -0.06 },
    { release: 'WPS payroll, October', when: 'Monthly, 2 Nov', pp: -0.05 },
    { release: 'Aani merchant payments', when: 'Daily, to 15 Nov', pp: 0.02 },
    { release: 'Dubai Land Department deals', when: 'Daily, to 14 Nov', pp: 0.03 },
  ];
  const newsSum = +news.reduce((a, n) => a + n.pp, 0).toFixed(2);
  console.assert(newsSum === weekChange, 'news contributions must sum to the weekly revision', newsSum, weekChange);

  const sectors = [
    { name: 'Construction', pp: -0.18 }, { name: 'Logistics and ports', pp: -0.11 }, { name: 'Retail', pp: -0.06 },
    { name: 'Manufacturing', pp: -0.03 }, { name: 'Other services', pp: 0.0 }, { name: 'Financial services', pp: 0.02 },
    { name: 'Hospitality', pp: 0.04 }, { name: 'Real estate', pp: 0.07 },
  ];
  console.assert(+sectors.reduce((a, s) => a + s.pp, 0).toFixed(2) === weekChange, 'sectors sum to the weekly revision');

  const feeds = [
    { source: 'UAEFTS', measure: 'Value settled, daily', latest: 'AED 142.6 bn', asOf: 'Today 06:00', status: 'current' },
    { source: 'Aani', measure: 'Instant payments, daily', latest: '1.84 m transactions', asOf: 'Today 06:00', status: 'current' },
    { source: 'WPS', measure: 'Payroll paid, October', latest: 'AED 31.2 bn', asOf: '2 Nov', status: 'current' },
    { source: 'Card acquirers', measure: 'Domestic spending, daily', latest: 'AED 2.41 bn', asOf: 'Yesterday', status: 'late', note: '2 of 9 acquirers a day late; 81% of volume' },
    { source: 'Dubai Land Department', measure: 'Property deals, daily', latest: '1,018 deals', asOf: 'Yesterday', status: 'current' },
  ];

  // ---------- time machine: what Nabd said at each quarter end vs the first official estimate ----------
  const q = (label, qEnd, nabd, official, release) => ({ label, qEnd: new Date(qEnd + 'T00:00:00Z'), nabd, official, release: release ? new Date(release + 'T00:00:00Z') : null });
  const quarters = [
    q('Q1 2024', '2024-03-31', 4.1, 4.4, '2024-07-08'), q('Q2 2024', '2024-06-30', 3.9, 4.0, '2024-10-07'),
    q('Q3 2024', '2024-09-30', 4.6, 4.5, '2025-01-13'), q('Q4 2024', '2024-12-31', 4.8, 5.1, '2025-04-14'),
    q('Q1 2025', '2025-03-31', 4.5, 4.3, '2025-07-07'), q('Q2 2025', '2025-06-30', 4.2, 4.4, '2025-10-06'),
    q('Q3 2025', '2025-09-30', 4.9, 4.8, '2026-01-12'), q('Q4 2025', '2025-12-31', 5.0, 5.2, '2026-04-13'),
    q('Q1 2026', '2026-03-31', 2.6, 2.3, '2026-07-06'), q('Q2 2026', '2026-06-30', 1.2, 1.4, '2026-10-05'),
    q('Q3 2026', '2026-09-30', 1.5, null, null),
  ];
  quarters.forEach((r) => { r.lead = r.release ? Math.round((r.release - r.qEnd) / DAY) : null; r.err = r.official == null ? null : +(r.nabd - r.official).toFixed(1); });
  const done = quarters.filter((r) => r.official != null);
  const mae = +(done.reduce((a, r) => a + Math.abs(r.err), 0) / done.length).toFixed(2);
  const meanLead = Math.round(done.reduce((a, r) => a + r.lead, 0) / done.length);
  const benchmarkMae = 0.55; // illustrative: a standard PMI-and-oil nowcast over the same quarters

  // ---------- firms ----------
  const firms = [
    { id: 'F-00412', sector: 'Logistics and ports', where: 'Jebel Ali', esri: 4.1, banks: 7, buffer: 6 },
    { id: 'F-01877', sector: 'Energy services', where: 'Ruwais', esri: 3.6, banks: 5, buffer: 9 },
    { id: 'F-00093', sector: 'Construction', where: 'Abu Dhabi', esri: 3.2, banks: 9, buffer: 11 },
    { id: 'F-02210', sector: 'Logistics and ports', where: 'Khalifa Port', esri: 2.7, banks: 4, buffer: 14 },
    { id: 'F-00657', sector: 'Retail', where: 'Dubai', esri: 2.2, banks: 6, buffer: 19 },
    { id: 'F-03381', sector: 'Manufacturing', where: 'Sharjah', esri: 1.9, banks: 3, buffer: 24 },
  ];
  const totalFirms = 405000, systemicCount = 142, systemicShare = 22.8, banksCount = 22;
  console.assert(Math.round(totalFirms * 0.00035) === systemicCount, '0.035% of firms');

  // ---------- scenario model (synthetic): 1,000 runs on a stylised network ----------
  const BRIDGE = 21; // the payroll bridge carries a firm for up to three weeks after its cash runs out
  function scenario({ days, brent, response, seed = 4812 }) {
    const g = gaussFrom(rng(seed * 7 + days * 31 + brent));
    const facility = response === 'facility';
    const oilFactor = 1 + Math.max(0, brent - 80) * 0.006;
    const base = -(1.6 + 0.09 * days) * oilFactor * (facility ? 0.6 : 1);
    const N = 1000, T = 91, runs = [];
    for (let k = 0; k < N; k++) {
      const m = Math.exp(0.2 * g()), tau = (facility ? 10 : 16) * Math.exp(0.15 * g()), depth = base * m, p = new Float32Array(T);
      for (let t = 0; t < T; t++) p[t] = t <= days ? depth * (1 - Math.exp(-t / 6)) : depth * (1 - Math.exp(-days / 6)) * Math.exp(-(t - days) / tau);
      runs.push(p);
    }
    const qs = [0.05, 0.2, 0.5, 0.8, 0.95], bands = qs.map(() => new Array(T)), col = new Float32Array(N);
    for (let t = 0; t < T; t++) { for (let k = 0; k < N; k++) col[k] = runs[k][t]; const s = Array.from(col).sort((a, b) => a - b); qs.forEach((qq, j) => (bands[j][t] = s[Math.floor(qq * (N - 1))])); }
    const avgs = runs.map((p) => p.reduce((a, v) => a + v, 0) / T).sort((a, b) => a - b);
    const pick = (arr, qq) => arr[Math.floor(qq * (arr.length - 1))];
    const banksBase = days >= 40 ? 4 : days >= 21 ? 3 : days >= 10 ? 1 : 0;
    const payroll = Math.round((120 + 38 * days) * oilFactor * (facility ? 0.45 : 1));
    return {
      days, brent, response, runs, bands, median: bands[2], T,
      avg: pick(avgs, 0.5), avg5: pick(avgs, 0.95), avg95: pick(avgs, 0.05),
      low: Math.min(...bands[2]),
      payroll, payrollLo: Math.round(payroll * 0.78), payrollHi: Math.round(payroll * 1.28),
      banks: facility ? Math.max(0, banksBase - 2) : banksBase,
      drawn: facility ? Math.min(30, +(0.75 * days).toFixed(1)) : 0,
      breakDay: (f) => { const d = f.buffer + (facility ? BRIDGE : 0); return d <= days ? d : null; },
    };
  }

  // ---------- network sample for the map ----------
  const sectorClusters = ['Logistics and ports', 'Construction', 'Retail', 'Energy services', 'Real estate', 'Hospitality', 'Manufacturing', 'Financial services'];
  const r1 = rng(7), gn = gaussFrom(r1), W = 1000, H = 520;
  const centres = sectorClusters.map((_, k) => { const a = (k / sectorClusters.length) * Math.PI * 2 - Math.PI / 2; return [W / 2 + Math.cos(a) * 360, H / 2 + Math.sin(a) * 180]; });
  const nodes = [];
  sectorClusters.forEach((sec, k) => { for (let i = 0; i < 78; i++) { const [cx, cy] = centres[k]; nodes.push({ id: nodes.length, sector: sec, x: cx + gn() * 46, y: cy + gn() * 30, vul: r1(), systemic: false }); } });
  firms.forEach((f) => { const k = sectorClusters.indexOf(f.sector); const n = nodes.find((x) => x.sector === f.sector && !x.systemic && Math.hypot(x.x - centres[k][0], x.y - centres[k][1]) < 30); n.systemic = true; n.firm = f.id; });
  for (let k = 0, c = nodes.filter((n) => n.systemic).length; c < 14; k++) { const n = nodes[(k * 97 + 13) % nodes.length]; if (!n.systemic) { n.systemic = true; c++; } }
  const edges = [];
  nodes.filter((n) => n.systemic).forEach((s) => { for (let i = 0; i < 18; i++) edges.push([s.id, Math.floor(r1() * nodes.length)]); });
  for (let i = 0; i < 220; i++) { const a = Math.floor(r1() * nodes.length); const b = nodes.findIndex((n, j) => j > a && n.sector === nodes[a].sector); if (b > 0) edges.push([a, b]); }

  // ---------- fraud case ----------
  const banks = [
    { name: 'Bank A', accounts: 9, aed: 1.12, ownFlags: 1 }, { name: 'Bank B', accounts: 8, aed: 0.96, ownFlags: 0 },
    { name: 'Bank C', accounts: 7, aed: 0.88, ownFlags: 2 }, { name: 'Bank D', accounts: 7, aed: 0.79, ownFlags: 0 },
    { name: 'Bank E', accounts: 6, aed: 0.61, ownFlags: 1 }, { name: 'Bank F', accounts: 4, aed: 0.46, ownFlags: 0 },
  ];
  const ring = { id: 'R-2611-07', victims: 212, days: 9, medianHoldMin: 7 };
  ring.accounts = banks.reduce((a, b) => a + b.accounts, 0);
  ring.aed = +banks.reduce((a, b) => a + b.aed, 0).toFixed(2);
  ring.ownFlags = banks.reduce((a, b) => a + b.ownFlags, 0);
  console.assert(ring.accounts === 41 && ring.aed === 4.82, 'ring totals');
  const layers = [12, 16, 9, 4], r2 = rng(42);
  const pool = banks.flatMap((b, k) => Array(b.accounts).fill(k));
  for (let i = pool.length - 1; i > 0; i--) { const j = Math.floor(r2() * (i + 1)); [pool[i], pool[j]] = [pool[j], pool[i]]; }
  const accts = []; let p = 0;
  layers.forEach((n, L) => { for (let i = 0; i < n; i++) accts.push({ id: 'A' + String(accts.length + 1).padStart(2, '0'), bank: pool[p++], layer: L }); }); // taste-skill-ignore: account IDs
  const links = [];
  for (let L = 0; L < layers.length - 1; L++) {
    const from = accts.filter((a) => a.layer === L), to = accts.filter((a) => a.layer === L + 1);
    from.forEach((a, i) => { const k = 1 + Math.floor(r2() * 2); for (let j = 0; j < k; j++) links.push([a.id, to[(i + j * 3) % to.length].id]); });
    to.forEach((b) => { if (!links.some(([, t]) => t === b.id)) links.push([from[Math.floor(r2() * from.length)].id, b.id]); });
  }
  const hops = [
    { time: '2026-11-14 21:42', from: 'A03', to: 'A17', aed: 18400, held: 6 }, { time: '2026-11-14 21:49', from: 'A17', to: 'A31', aed: 18100, held: 7 },
    { time: '2026-11-14 21:55', from: 'A31', to: 'A39', aed: 17900, held: 6 }, { time: '2026-11-14 22:08', from: 'A39', to: 'Abroad', aed: 17600, held: 13 },
  ];

  // ---------- governance ----------
  const models = [
    { name: 'Non-oil nowcast', kind: 'Dynamic factor model', tier: 'On premise', data: 'Aggregated payments', validated: '2026-10-28', owner: 'Economic Research' },
    { name: 'Scenario engine', kind: 'Network cascade, 1,000 runs', tier: 'On premise', data: 'Firm-level, restricted', validated: '2026-10-14', owner: 'Financial Stability' },
    { name: 'Mule ring detector', kind: 'Graph model', tier: 'On premise', data: 'Account-level, restricted', validated: '2026-11-03', owner: 'Payment Systems' },
    { name: 'Analyst language model', kind: 'Open-weight, on premise', tier: 'On premise', data: 'Case files, restricted', validated: '2026-11-01', owner: 'Head of AI' },
    { name: 'Briefing language model', kind: 'Hosted model', tier: 'Azure UAE North', data: 'Aggregates only', validated: '2026-11-01', owner: 'Head of AI' },
  ];
  const audit = [
    { time: '06:00', who: 'System', what: 'Nowcast refreshed from 5 sources', tier: 'On premise', approved: '—' },
    { time: '07:12', who: 'Economic Research', what: 'Governor’s note drafted', tier: 'Azure UAE North', approved: 'Chief Economist' },
    { time: '08:40', who: 'Payment Systems', what: 'Case R-2611-07 opened', tier: 'On premise', approved: '—' },
    { time: '10:30', who: 'Investment', what: 'Scenario run 4812, Hormuz 30 days, saved', tier: 'On premise', approved: 'Pending CRO' },
  ];
  const usage = { runs: 1284, llmCalls: 312, hostedCalls: 41, recordsOut: 0 };

  // ---------- team activity for the home page ----------
  const activity = [
    { what: 'Hormuz closure, 30 days', kind: 'Scenario run 4812', who: 'Investment', when: 'Today 10:30', status: 'Awaiting CRO sign-off', tone: 'warn', route: 'scenarios' },
    { what: 'Governor’s note, 16 Nov', kind: 'Briefing', who: 'Economic Research', when: 'Today 07:12', status: 'Awaiting Chief Economist', tone: 'warn', route: 'nowcast' },
    { what: 'Mule ring across 6 banks, case R-2611-07', kind: 'Fraud case', who: 'Payment Systems', when: 'Today 08:40', status: 'Open', tone: 'neg', route: 'fraud', fraud: true },
    { what: 'F-00412 cash buffer down to 6 days', kind: 'Network alert', who: 'Financial Stability', when: 'Yesterday', status: 'Under review', tone: 'neutral', route: 'network', firmLevel: true, masked: 'A port-logistics firm: cash buffer down to 6 days' },
    { what: 'Oil at $45 for six months', kind: 'Scenario run 4810', who: 'Financial Stability', when: 'Yesterday', status: 'Saved as playbook', tone: 'pos', route: 'scenarios' },
  ];

  window.NABD = { DAY, fmtDate, fmtShort, roles, weeks, nowcast, half70, half90, weekChange, news, sectors, feeds,
    quarters, mae, meanLead, benchmarkMae, firms, totalFirms, systemicCount, systemicShare, banksCount, BRIDGE, scenario,
    sectorClusters, centres, nodes, edges, W, H, banks, ring, accts, links, layers, hops, models, audit, usage, activity };
})();
