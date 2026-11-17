// Nabd network fraud analysis — a synthetic Aani payment graph and the graph algorithms that run on it.
// Everything here is computed in the browser: community detection (weighted label propagation), flow-through and
// holding time, PageRank on money flows, and an explainable community risk score. The data is synthetic.
(() => {
  const rng = (seed) => () => { seed |= 0; seed = (seed + 0x6d2b79f5) | 0; let t = Math.imul(seed ^ (seed >>> 15), 1 | seed); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
  const R = rng(2611);
  const pick = (a) => a[Math.floor(R() * a.length)];
  const BANKS = ['Bank A', 'Bank B', 'Bank C', 'Bank D', 'Bank E', 'Bank F'];

  // ---------- 1. build the payment graph (one week of Aani transfers) ----------
  const nodes = [], edges = [];
  const add = (o) => { const n = { id: nodes.length, ...o }; nodes.push(n); return n; };
  const pay = (a, b, aed, holdMin) => edges.push({ s: a.id, t: b.id, aed, hold: holdMin });
  // legitimate economy: payroll stars, merchant clusters and household transfers, mostly within one bank
  const groups = [];
  for (let g = 0; g < 9; g++) {
    const bank = g % 6, size = 26 + Math.floor(R() * 18), hub = add({ kind: 'business', bank, age: 1500 + Math.floor(R() * 2000), truth: 'normal' });
    const members = [hub];
    for (let i = 1; i < size; i++) members.push(add({ kind: 'person', bank: R() < 0.8 ? bank : Math.floor(R() * 6), age: 200 + Math.floor(R() * 3000), truth: 'normal' }));
    groups.push(members);
    members.slice(1).forEach((m) => { pay(hub, m, 6000 + R() * 9000, 2000 + R() * 6000); if (R() < 0.6) pay(m, pick(members), 200 + R() * 1500, 900 + R() * 5000); if (R() < 0.35) pay(m, hub, 300 + R() * 2000, 1500 + R() * 4000); });
  }
  // a little cross-group traffic so the graph is one economy, not islands
  for (let i = 0; i < 70; i++) { const a = pick(pick(groups)), b = pick(pick(groups)); if (a !== b) pay(a, b, 300 + R() * 4000, 1200 + R() * 6000); }

  // the mule ring behind case R-2611-07: victims pay in, two layers pass on within minutes, four send abroad
  const victims = Array.from({ length: 22 }, () => { const v = add({ kind: 'person', bank: Math.floor(R() * 6), age: 900 + Math.floor(R() * 3000), truth: 'victim' }); return v; });
  // victims are ordinary people: each is paid a salary by an employer elsewhere in the economy
  victims.forEach((v) => pay(pick(groups)[0], v, 7000 + R() * 9000, 3000 + R() * 5000));
  const layer = (n) => Array.from({ length: n }, () => add({ kind: 'person', bank: Math.floor(R() * 6), age: 5 + Math.floor(R() * 50), truth: 'mule' }));
  const L1 = layer(12), L2 = layer(16), L3 = layer(9), L4 = layer(4);
  const abroad = add({ kind: 'abroad', bank: -1, age: 0, truth: 'cashout', label: 'Outward remittances' });
  // a victim pays the scammer hours or days after their salary arrives, so the victim is not a pass-through account
  victims.forEach((v, i) => { pay(v, L1[i % L1.length], 4000 + R() * 26000, 600 + R() * 4000); if (R() < 0.4) pay(v, L1[(i + 5) % L1.length], 3000 + R() * 15000, 600 + R() * 4000); });
  // each mule passes on about 97% of what it received, within minutes, to two or three accounts in the next layer;
  // every account in the next layer receives from at least one, so the ring is one connected trail
  const inflow = (n) => edges.filter((e) => e.t === n.id).reduce((a, e) => a + e.aed, 0);
  const chain = (A, B) => {
    const targets = A.map((a, i) => { const k = 2 + (R() < 0.4 ? 1 : 0); return Array.from({ length: k }, (_, j) => B[(i * 3 + j * 5) % B.length]); });
    B.forEach((b, i) => { if (!targets.some((t) => t.includes(b))) targets[i % A.length].push(b); });
    A.forEach((a, i) => { const total = inflow(a) * (0.95 + R() * 0.04), w = targets[i].map(() => 0.5 + R()), ws = w.reduce((x, y) => x + y, 0); targets[i].forEach((b, j) => pay(a, b, (total * w[j]) / ws, 3 + R() * 9)); });
  };
  chain(L1, L2); chain(L2, L3); chain(L3, L4);
  L4.forEach((a) => pay(a, abroad, inflow(a) * 0.97, 8 + R() * 10));
  // a second, smaller pattern: fan-out to newly opened accounts across four banks
  const fanHub = add({ kind: 'person', bank: 3, age: 21, truth: 'fanout' });
  const fanFeed = add({ kind: 'business', bank: 1, age: 400, truth: 'fanout' });
  pay(fanFeed, fanHub, 410000, 0);
  pay(pick(groups)[0], fanFeed, 380000, 2000); pay(fanFeed, pick(groups)[0], 52000, 2500);
  const fan = Array.from({ length: 13 }, (_, i) => add({ kind: 'person', bank: [0, 2, 4, 5][i % 4], age: 3 + Math.floor(R() * 25), truth: 'fanout' }));
  fan.forEach((f) => { pay(fanHub, f, 18000 + R() * 12000, 22 + R() * 40); if (R() < 0.5) pay(f, pick(groups[Math.floor(R() * 9)]), 15000 + R() * 9000, 30 + R() * 90); });

  const N = nodes.length;
  const out = nodes.map(() => []), inn = nodes.map(() => []);
  edges.forEach((e, k) => { out[e.s].push(k); inn[e.t].push(k); });

  // ---------- 2. community detection: weighted label propagation on the undirected graph ----------
  const nbr = nodes.map(() => new Map());
  edges.forEach((e) => { nbr[e.s].set(e.t, (nbr[e.s].get(e.t) || 0) + Math.log1p(e.aed)); nbr[e.t].set(e.s, (nbr[e.t].get(e.s) || 0) + Math.log1p(e.aed)); });
  let label = nodes.map((n) => n.id);
  const order = nodes.map((n) => n.id);
  for (let it = 0; it < 25; it++) {
    for (let i = order.length - 1; i > 0; i--) { const j = Math.floor(R() * (i + 1)); [order[i], order[j]] = [order[j], order[i]]; }
    let changed = 0;
    order.forEach((v) => {
      if (!nbr[v].size) return;
      const score = new Map(); nbr[v].forEach((w, u) => score.set(label[u], (score.get(label[u]) || 0) + w));
      let best = label[v], bw = -1; score.forEach((w, l) => { if (w > bw || (w === bw && l < best)) { bw = w; best = l; } });
      if (best !== label[v]) { label[v] = best; changed++; }
    });
    if (!changed) break;
  }
  const remap = new Map(); label = label.map((l) => { if (!remap.has(l)) remap.set(l, remap.size); return remap.get(l); });
  nodes.forEach((n, i) => (n.comm = label[i]));

  // ---------- 3. per-account features: flow-through, holding time, fan-in/out ----------
  const median = (a) => { if (!a.length) return null; const s = [...a].sort((x, y) => x - y), m = s.length >> 1; return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2; };
  nodes.forEach((n, i) => {
    const ins = inn[i].map((k) => edges[k]), outs = out[i].map((k) => edges[k]);
    n.inAed = ins.reduce((a, e) => a + e.aed, 0); n.outAed = outs.reduce((a, e) => a + e.aed, 0);
    n.flow = n.inAed > 0 ? Math.min(1, n.outAed / n.inAed) : 0;
    n.hold = median(outs.map((e) => e.hold));
    n.fanIn = new Set(ins.map((e) => e.s)).size; n.fanOut = new Set(outs.map((e) => e.t)).size;
  });

  // ---------- 4. PageRank on money flows (where does money end up?) ----------
  let pr = new Array(N).fill(1 / N);
  const outW = nodes.map((_, i) => out[i].reduce((a, k) => a + edges[k].aed, 0));
  for (let it = 0; it < 40; it++) {
    const next = new Array(N).fill(0.15 / N); let dangling = 0;
    for (let i = 0; i < N; i++) { if (!outW[i]) { dangling += pr[i]; continue; } out[i].forEach((k) => (next[edges[k].t] += 0.85 * pr[i] * (edges[k].aed / outW[i]))); }
    for (let i = 0; i < N; i++) next[i] += (0.85 * dangling) / N;
    pr = next;
  }
  const prMax = Math.max(...pr); nodes.forEach((n, i) => (n.pr = pr[i] / prMax));

  // ---------- 5. detection, re-runnable with a method and thresholds ----------
  // 'trail'     follow the money: link transfers a pass-through account sends on within `holdMax` minutes when it
  //             forwards at least `flowMin` of what it received; take connected components (layered rings are chains).
  // 'community' score the label-propagation communities instead; layered rings fragment across them.
  // 'rules'     score each account on its own, with no network: what a single-account rule engine sees.
  const scoreGroup = (m, tag) => {
    const acc = m.filter((n) => n.kind !== 'abroad');
    const passers = acc.filter((n) => n.inAed > 0 && n.outAed > 0);
    const ids = new Set(m.map((n) => n.id));
    const sources = new Set(); edges.forEach((e) => { if (ids.has(e.t) && !ids.has(e.s) && nodes[e.s].kind !== 'abroad') sources.add(e.s); });
    const f = {
      flow: passers.length ? median(passers.map((n) => n.flow)) : 0,
      fastShare: passers.length ? passers.filter((n) => n.hold != null && n.hold < 30).length / passers.length : 0,
      youngShare: acc.length ? acc.filter((n) => n.age < 90).length / acc.length : 0,
      banks: new Set(acc.map((n) => n.bank)).size,
      abroad: m.some((n) => n.kind === 'abroad') || acc.some((n) => out[n.id].some((k) => nodes[edges[k].t].kind === 'abroad')),
    };
    const parts = { 'Money passed straight on': 2.4 * f.flow, 'Held under 30 minutes': 2.6 * f.fastShare, 'Accounts under 90 days old': 2.2 * f.youngShare, 'Spread across banks': 1.1 * (f.banks / 6), 'Sends money abroad': f.abroad ? 0.9 : 0 };
    const z = Object.values(parts).reduce((a, v) => a + v, 0) - 4.2;
    return { tag, size: acc.length, members: m.map((n) => n.id), sources: [...sources], ...f, holdMed: median(passers.map((n) => n.hold).filter((h) => h != null)) ?? 0, parts, score: 1 / (1 + Math.exp(-2.2 * z)) };
  };
  function detect({ method = 'trail', holdMax = 60, flowMin = 0.7 } = {}) {
    nodes.forEach((n) => (n.trail = null));
    const fastEdge = edges.map((e) => nodes[e.s].flow >= flowMin && e.hold < holdMax && nodes[e.s].inAed > 0);
    let groups = [];
    if (method === 'trail') {
      const parent = nodes.map((n) => n.id), find = (x) => (parent[x] === x ? x : (parent[x] = find(parent[x])));
      edges.forEach((e, k) => { if (fastEdge[k]) parent[find(e.s)] = find(e.t); });
      const g = new Map(); nodes.forEach((n) => { const r = find(n.id); if (!g.has(r)) g.set(r, []); g.get(r).push(n); });
      groups = [...g.values()].filter((m) => m.filter((n) => n.kind !== 'abroad').length >= 4);
    } else if (method === 'community') {
      const g = new Map(); nodes.forEach((n) => { if (!g.has(n.comm)) g.set(n.comm, []); g.get(n.comm).push(n); });
      groups = [...g.values()].filter((m) => m.filter((n) => n.kind !== 'abroad').length >= 4);
    } else {
      groups = nodes.filter((n) => n.kind !== 'abroad' && n.inAed > 0 && n.flow >= flowMin && n.hold != null && n.hold < holdMax).map((n) => [n]);
    }
    const label = { trail: 'Trail', community: 'Community', rules: 'Account' }[method];
    const comms = groups.map((m) => scoreGroup(m, method)).sort((a, b) => b.score - a.score);
    comms.forEach((c, i) => { c.rank = i + 1; c.id = `${label} ${i + 1}`; c.members.forEach((id) => { if (nodes[id].kind !== 'abroad' || method === 'trail') nodes[id].trail = c.id; }); });
    const flagged = comms.filter((c) => c.score >= 0.7);
    const ring = nodes.filter((n) => n.truth === 'mule');
    const ringCaught = ring.filter((n) => n.trail && flagged.some((c) => c.id === n.trail)).length;
    const largest = flagged.length ? Math.max(...flagged.map((c) => c.members.filter((id) => nodes[id].truth === 'mule').length)) : 0;
    const falseAlarms = flagged.reduce((a, c) => a + c.members.filter((id) => nodes[id].truth === 'normal').length, 0);
    return { method, holdMax, flowMin, fastEdge, comms, flagged, commOf: new Map(comms.map((c) => [c.id, c])), ringSize: ring.length, ringCaught, largest, falseAlarms };
  }
  const first = detect();
  const { fastEdge, comms, flagged, commOf } = first;

  // ---------- 6. force-directed layout (computed once, deterministic) ----------
  const W = 1000, H = 620;
  const cIds = [...new Set(nodes.map((n) => n.comm))];
  nodes.forEach((n) => { const k = cIds.indexOf(n.comm), a = (k / cIds.length) * Math.PI * 2; n.x = W / 2 + Math.cos(a) * 260 + (R() - 0.5) * 80; n.y = H / 2 + Math.sin(a) * 190 + (R() - 0.5) * 80; });
  // Fruchterman-Reingold: repulsion k^2/d between all pairs, attraction d^2/k along transfers, mild gravity
  const kk = Math.sqrt((W * H) / N) * 0.5;
  for (let it = 0, temp = 40; it < 220; it++, temp = Math.max(1.5, temp * 0.982)) {
    const dx = new Float32Array(N), dy = new Float32Array(N);
    for (let i = 0; i < N; i++) for (let j = i + 1; j < N; j++) {
      const ex = nodes[i].x - nodes[j].x, ey = nodes[i].y - nodes[j].y, d2 = ex * ex + ey * ey + 0.01;
      if (d2 > 40000) continue;
      const f = (kk * kk) / d2; dx[i] += ex * f; dy[i] += ey * f; dx[j] -= ex * f; dy[j] -= ey * f;
    }
    edges.forEach((e) => { const a = nodes[e.s], b = nodes[e.t], ex = a.x - b.x, ey = a.y - b.y, d = Math.sqrt(ex * ex + ey * ey) + 0.01, f = d / kk; dx[e.s] -= ex * f; dy[e.s] -= ey * f; dx[e.t] += ex * f; dy[e.t] += ey * f; });
    for (let i = 0; i < N; i++) {
      dx[i] += (W / 2 - nodes[i].x) * 0.02; dy[i] += (H / 2 - nodes[i].y) * 0.032;
      const d = Math.sqrt(dx[i] * dx[i] + dy[i] * dy[i]) + 0.01, s = Math.min(d, temp) / d;
      nodes[i].x = Math.max(20, Math.min(W - 20, nodes[i].x + dx[i] * s)); nodes[i].y = Math.max(20, Math.min(H - 20, nodes[i].y + dy[i] * s));
    }
  }

  // fit the finished layout to the canvas, keeping a margin
  { const xs = nodes.map((n) => n.x), ys = nodes.map((n) => n.y), x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
    nodes.forEach((n) => { n.x = 40 + ((n.x - x0) / (x1 - x0 || 1)) * (W - 80); n.y = 36 + ((n.y - y0) / (y1 - y0 || 1)) * (H - 72); }); }

  window.NETLAB = { BANKS, nodes, edges, comms, flagged, commOf, fastEdge, detect, run: first, W, H, stats: { accounts: N - 1, transfers: edges.length, communities: cIds.length, trails: comms.length } };
})();
