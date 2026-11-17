// The whole payment network as a live force simulation: accounts repel, payments pull like springs, and the network
// settles into its natural clusters. Drag an account and its neighbours follow; scroll to zoom, drag the background
// to pan. Hover lights up who an account paid and who paid it (arrows show direction); click opens its case.
import { forceCenter, forceCollide, forceLink, forceManyBody, forceSimulation, forceX, forceY, type Simulation, type SimulationLinkDatum, type SimulationNodeDatum } from 'd3-force';
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import type { NEdge, NNode } from './NetworkCanvas';

type SNode = SimulationNodeDatum & NNode & { deg: number; vol: number; r: number };
type SLink = SimulationLinkDatum<SNode> & { amount: number; n: number; s: string; d: string };
type View = { k: number; x: number; y: number };

const COL = { other: 'rgba(110,110,118,0.55)', flagged: '#a0661c', sel: '#d70015', truth: '#2a78d6', edge: 'rgba(110,110,118,', hot: 'rgba(215,0,21,' };
export const BANK_COLOURS = ['#a0661c', '#2a78d6', '#d4458a', '#138a62', '#6e56cf', '#8a6d00'];

export default function ForceNetwork({ nodes, edges, flagged, selected, caseOf, showTruth, colourBy, onPick, focusId }: {
  nodes: NNode[]; edges: NEdge[]; flagged: Set<string>; selected: Set<string>; caseOf: Map<string, string>;
  showTruth: boolean; colourBy: 'flag' | 'bank'; onPick: (id: string | null) => void; focusId?: string | null;
}) {
  const wrap = useRef<HTMLDivElement>(null);
  const cv = useRef<HTMLCanvasElement>(null);
  const [size, setSize] = useState({ w: 800, h: 560 });
  const view = useRef<View>({ k: 1, x: 0, y: 0 });
  const sim = useRef<Simulation<SNode, SLink> | null>(null);
  const hover = useRef<SNode | null>(null);
  const [tip, setTip] = useState<{ n: SNode; x: number; y: number } | null>(null);
  const [running, setRunning] = useState(true);
  const [query, setQuery] = useState('');
  const [onlyFlagged, setOnlyFlagged] = useState(false);
  const drag = useRef<{ kind: 'pan' | 'node'; node?: SNode; sx: number; sy: number; vx: number; vy: number; moved: boolean } | null>(null);
  const raf = useRef(0);

  const banks = useMemo(() => [...new Set(nodes.map((n) => n.bank))].sort(), [nodes]);
  // simulation data: copies, so the physics never mutates props. Size by money moved.
  const placed = useRef(new Map<string, { x: number; y: number }>());  // last positions, so a rebuild keeps the layout
  const data = useMemo(() => {
    const keep = onlyFlagged ? new Set([...flagged]) : null;
    if (keep) edges.forEach((e) => { if (flagged.has(e.s) || flagged.has(e.d)) { keep.add(e.s); keep.add(e.d); } });
    const ns = nodes.filter((n) => !keep || keep.has(n.id));
    const ids = new Set(ns.map((n) => n.id));
    const es = edges.filter((e) => ids.has(e.s) && ids.has(e.d));
    const deg = new Map<string, number>(), vol = new Map<string, number>();
    es.forEach((e) => { for (const id of [e.s, e.d]) { deg.set(id, (deg.get(id) ?? 0) + 1); vol.set(id, (vol.get(id) ?? 0) + e.amount); } });
    const xs = ns.map((n) => n.x), ys = ns.map((n) => n.y);
    const cx = (Math.min(...xs) + Math.max(...xs)) / 2, cy = (Math.min(...ys) + Math.max(...ys)) / 2;
    const span = Math.max(Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys)) || 1;
    const sn: SNode[] = ns.map((n) => {
      const was = placed.current.get(n.id);
      return { ...n, deg: deg.get(n.id) ?? 0, vol: vol.get(n.id) ?? 0, r: 2.5 + Math.min(7, Math.sqrt((vol.get(n.id) ?? 0) / 60000)),
        x: was?.x ?? ((n.x - cx) / span) * 900, y: was?.y ?? ((n.y - cy) / span) * 900 };
    });
    const sl: SLink[] = es.map((e) => ({ source: e.s, target: e.d, amount: e.amount, n: e.n, s: e.s, d: e.d }));
    const adj = new Map<string, Set<string>>();
    es.forEach((e) => { adj.set(e.s, (adj.get(e.s) ?? new Set()).add(e.d)); adj.set(e.d, (adj.get(e.d) ?? new Set()).add(e.s)); });
    return { sn, sl, adj, byId: new Map(sn.map((n) => [n.id, n])) };
  }, [nodes, edges, flagged, onlyFlagged]);

  useLayoutEffect(() => {
    if (!wrap.current) return;
    const ro = new ResizeObserver(([e]) => setSize({ w: e.contentRect.width, h: e.contentRect.height }));
    ro.observe(wrap.current);
    return () => ro.disconnect();
  }, []);

  const draw = useCallback(() => {
    const c = cv.current;
    if (!c) return;
    const dpr = window.devicePixelRatio || 1;
    if (c.width !== Math.round(size.w * dpr)) { c.width = Math.round(size.w * dpr); c.height = Math.round(size.h * dpr); }
    const g = c.getContext('2d')!;
    const { k, x: vx, y: vy } = view.current;
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, size.w, size.h);
    g.setTransform(dpr * k, 0, 0, dpr * k, dpr * (size.w / 2 + vx), dpr * (size.h / 2 + vy));
    const h = hover.current, near = h ? data.adj.get(h.id) ?? new Set<string>() : null;
    const focus = (id: string) => (h ? id === h.id || near!.has(id) : selected.size ? selected.has(id) : true);
    const maxAmt = Math.max(1, ...data.sl.map((l) => l.amount));
    // edges: faint everywhere, bright in the hovered neighbourhood or the selected case
    for (const l of data.sl) {
      const a = l.source as SNode, b = l.target as SNode;
      const hot = h ? a.id === h.id || b.id === h.id : selected.has(a.id) && selected.has(b.id);
      const w = (0.4 + 2.2 * Math.sqrt(l.amount / maxAmt)) / Math.sqrt(k);
      g.strokeStyle = hot ? `${COL.hot}0.75)` : `${COL.edge}${h || selected.size ? 0.06 : flagged.has(a.id) && flagged.has(b.id) ? 0.35 : 0.13})`;
      g.lineWidth = hot ? w * 1.6 : w;
      g.beginPath(); g.moveTo(a.x!, a.y!); g.lineTo(b.x!, b.y!); g.stroke();
      if (hot && k > 0.7) {  // direction: an arrowhead at the receiving account
        const br = b.r / Math.sqrt(Math.max(1, k)) + 2 / k, ang = Math.atan2(b.y! - a.y!, b.x! - a.x!), ex = b.x! - Math.cos(ang) * br, ey = b.y! - Math.sin(ang) * br, s = 7 / k;
        g.fillStyle = `${COL.hot}0.85)`;
        g.beginPath(); g.moveTo(ex, ey); g.lineTo(ex - s * Math.cos(ang - 0.45), ey - s * Math.sin(ang - 0.45)); g.lineTo(ex - s * Math.cos(ang + 0.45), ey - s * Math.sin(ang + 0.45)); g.fill();
      }
    }
    for (const n of data.sn) {
      const sel = selected.has(n.id), fl = flagged.has(n.id), on = focus(n.id);
      g.globalAlpha = on ? 1 : 0.18;
      g.fillStyle = colourBy === 'bank' ? BANK_COLOURS[banks.indexOf(n.bank) % BANK_COLOURS.length] : sel ? COL.sel : fl ? COL.flagged : COL.other;
      const rr = (n.r * (sel || n === h ? 1.35 : 1)) / Math.sqrt(Math.max(1, k));
      g.beginPath(); g.arc(n.x!, n.y!, rr, 0, Math.PI * 2); g.fill();
      if (n === h || (n.fx != null)) { g.lineWidth = 2 / k; g.strokeStyle = '#1d1d1f'; g.stroke(); }
      if (showTruth && n.truth) { g.lineWidth = 1.5 / k; g.strokeStyle = COL.truth; g.beginPath(); g.arc(n.x!, n.y!, rr + 3 / k, 0, Math.PI * 2); g.stroke(); }
    }
    g.globalAlpha = 1;
    // names when zoomed in, for the accounts in focus
    if (k > 1.6 || h) {
      g.font = `600 ${11 / k}px -apple-system, system-ui, sans-serif`;
      g.fillStyle = '#1d1d1f'; g.textAlign = 'center';
      for (const n of data.sn) {
        if (!(h ? focus(n.id) : selected.size ? selected.has(n.id) : k > 2.4 && flagged.has(n.id))) continue;
        g.fillText(n.id, n.x!, n.y! - n.r / Math.sqrt(Math.max(1, k)) - 4 / k);
      }
    }
  }, [data, size, selected, flagged, showTruth, colourBy, banks]);

  const drawRef = useRef(draw);
  drawRef.current = draw;
  const schedule = useCallback(() => { cancelAnimationFrame(raf.current); raf.current = requestAnimationFrame(() => drawRef.current()); }, []);
  useEffect(() => { hover.current = null; schedule(); }, [selected, schedule]);  // a new selection replaces any lingering hover
  useEffect(() => { schedule(); }, [draw, schedule]);  // redraw on selection, colour or label changes without touching the physics

  // Physics: every account repels; payments are springs. Springs between flagged accounts are strong, so rings pull
  // into tight knots; incidental links to ordinary accounts are weak, so the crowd spreads instead of forming a ball.
  const userMoved = useRef(false);
  useEffect(() => {
    const strong = (l: SLink) => flagged.has(l.s) && flagged.has(l.d);
    const s = forceSimulation<SNode, SLink>(data.sn)
      .force('charge', forceManyBody<SNode>().strength((n) => -30 - n.r * 6).distanceMax(700).theta(0.9))
      .force('link', forceLink<SNode, SLink>(data.sl).id((n) => n.id)
        .distance((l) => (strong(l) ? 18 : 60))
        .strength((l) => (strong(l) ? 0.7 : 0.04)))
      .force('collide', forceCollide<SNode>().radius((n) => n.r + 2))
      .force('x', forceX(0).strength(0.035)).force('y', forceY(0).strength(0.035))
      .force('center', forceCenter(0, 0))
      .alpha(placed.current.size ? 0.35 : 1).alphaDecay(0.02)
      .on('tick', () => { for (const n of data.sn) placed.current.set(n.id, { x: n.x!, y: n.y! }); schedule(); })
      .on('end', () => { if (!userMoved.current) fitRef.current(); });
    sim.current = s;
    userMoved.current = false;
    setRunning(true);
    return () => { s.stop(); };
  }, [data, schedule, flagged]);
  useEffect(() => { schedule(); }, [schedule, size]);

  const fit = useCallback((ids?: Set<string>) => {
    const ns = ids && ids.size ? data.sn.filter((n) => ids.has(n.id)) : data.sn;
    if (!ns.length) return;
    const xs = ns.map((n) => n.x!), ys = ns.map((n) => n.y!);
    const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
    const k = Math.min(6, Math.max(0.2, 0.85 * Math.min(size.w / (x1 - x0 + 80), size.h / (y1 - y0 + 80))));
    view.current = { k, x: -((x0 + x1) / 2) * k, y: -((y0 + y1) / 2) * k };
    schedule();
  }, [data, size, schedule]);
  const fitRef = useRef(fit);
  fitRef.current = fit;
  // fit the whole network once it has settled a little; zoom to a case when one is selected
  useEffect(() => { const t = setTimeout(() => { if (!userMoved.current) fit(); }, 1500); return () => clearTimeout(t); }, [data]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (selected.size) { userMoved.current = true; const t = setTimeout(() => fit(selected), 50); return () => clearTimeout(t); } }, [selected]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (focusId && data.byId.get(focusId)) fit(new Set([focusId, ...(data.adj.get(focusId) ?? [])])); }, [focusId]); // eslint-disable-line react-hooks/exhaustive-deps

  const toWorld = (px: number, py: number) => { const v = view.current; return { x: (px - size.w / 2 - v.x) / v.k, y: (py - size.h / 2 - v.y) / v.k }; };
  const nodeAt = (px: number, py: number) => {
    const p = toWorld(px, py), k = view.current.k;
    let best: SNode | null = null, bd = Infinity;
    for (const n of data.sn) { const d = (n.x! - p.x) ** 2 + (n.y! - p.y) ** 2, rr = (n.r / Math.sqrt(Math.max(1, k)) + 6 / k) ** 2; if (d < rr && d < bd) { bd = d; best = n; } }
    return best;
  };
  const local = (e: React.PointerEvent | React.WheelEvent) => { const r = wrap.current!.getBoundingClientRect(); return { px: e.clientX - r.left, py: e.clientY - r.top }; };

  function onDown(e: React.PointerEvent) {
    const { px, py } = local(e), n = nodeAt(px, py);
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
    if (n) { drag.current = { kind: 'node', node: n, sx: px, sy: py, vx: 0, vy: 0, moved: false }; n.fx = n.x; n.fy = n.y; sim.current?.alphaTarget(0.25).restart(); setRunning(true); }
    else drag.current = { kind: 'pan', sx: px, sy: py, vx: view.current.x, vy: view.current.y, moved: false };
    userMoved.current = true;
  }
  function onMove(e: React.PointerEvent) {
    const { px, py } = local(e), d = drag.current;
    if (d) {
      if (Math.abs(px - d.sx) + Math.abs(py - d.sy) > 3) d.moved = true;
      if (d.kind === 'node' && d.node) { const p = toWorld(px, py); d.node.fx = p.x; d.node.fy = p.y; }
      else { view.current = { ...view.current, x: d.vx + px - d.sx, y: d.vy + py - d.sy }; schedule(); }
      setTip(null);
      return;
    }
    const n = nodeAt(px, py);
    if (n !== hover.current) { hover.current = n; schedule(); }
    setTip(n ? { n, x: px, y: py } : null);
    wrap.current!.style.cursor = n ? 'pointer' : 'grab';
  }
  function onUp(e: React.PointerEvent) {
    const d = drag.current; drag.current = null;
    if (!d) return;
    if (d.kind === 'node' && d.node) {
      sim.current?.alphaTarget(0);
      if (!e.shiftKey) { d.node.fx = null; d.node.fy = null; }  // shift-drag pins an account where you drop it
      if (!d.moved) onPick(d.node.id);
    } else if (!d.moved) onPick(null);
  }
  function onWheel(e: React.WheelEvent) {
    userMoved.current = true;
    const { px, py } = local(e), v = view.current, f = Math.exp(-e.deltaY * 0.0015);
    const k = Math.min(10, Math.max(0.15, v.k * f)), kk = k / v.k;
    const ox = px - size.w / 2, oy = py - size.h / 2;
    view.current = { k, x: ox - (ox - v.x) * kk, y: oy - (oy - v.y) * kk };
    schedule();
  }
  function zoom(f: number) { const v = view.current, k = Math.min(10, Math.max(0.15, v.k * f)); view.current = { k, x: v.x * (k / v.k), y: v.y * (k / v.k) }; schedule(); }
  function search(e: React.FormEvent) {
    e.preventDefault();
    const id = query.trim().toUpperCase();
    const n = data.byId.get(id) ?? data.sn.find((x) => x.id.endsWith(id));
    if (n) { userMoved.current = true; fit(new Set([n.id, ...(data.adj.get(n.id) ?? [])])); onPick(n.id); }
  }
  useEffect(() => {  // wheel must be non-passive to stop the page scrolling while zooming
    const el = wrap.current; if (!el) return;
    const stop = (e: WheelEvent) => e.preventDefault();
    el.addEventListener('wheel', stop, { passive: false });
    return () => el.removeEventListener('wheel', stop);
  }, []);

  const tn = tip?.n, inCase = tn ? caseOf.get(tn.id) : undefined;
  return (
    <div className="fn">
      <div className="fn-stage" ref={wrap} onPointerDown={onDown} onPointerMove={onMove} onPointerUp={onUp}
        onPointerLeave={() => { if (!drag.current) { hover.current = null; setTip(null); schedule(); } }} onWheel={onWheel}>
        <canvas ref={cv} style={{ width: size.w, height: size.h }} role="img" aria-label="Payment network. Drag accounts, scroll to zoom, click an account to open its case." />
        {tn && (
          <div className="fn-tip" style={{ left: Math.min(tip!.x + 14, size.w - 220), top: Math.max(6, tip!.y - 12) }}>
            <strong>{tn.id}</strong><span>{tn.bank} · {tn.kind}</span>
            <span>{tn.deg} counterpart{tn.deg === 1 ? '' : 's'} shown · AED {(tn.vol / 1e3).toFixed(0)} k moved</span>
            {inCase ? <span className="flag">In case {inCase}: click to open</span> : flagged.has(tn.id) ? <span className="flag">Flagged</span> : null}
            {showTruth && tn.truth ? <span className="truthy">Labelled laundering</span> : null}
          </div>
        )}
        <div className="fn-tools" onPointerDown={(e) => e.stopPropagation()}>
          <form onSubmit={search}><input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Find account, e.g. AC03182" aria-label="Find account" /></form>
          <div className="fn-btns">
            <button type="button" className="btn small" onClick={() => zoom(1.3)} aria-label="Zoom in">+</button>
            <button type="button" className="btn small" onClick={() => zoom(1 / 1.3)} aria-label="Zoom out">−</button>
            <button type="button" className="btn small" onClick={() => fit()}>Fit</button>
            <button type="button" className="btn small" onClick={() => { const s = sim.current; if (!s) return; if (running) { s.stop(); setRunning(false); } else { s.alpha(0.5).restart(); setRunning(true); } }}>{running ? 'Freeze' : 'Shake'}</button>
          </div>
          <label className="switch small-sw"><input type="checkbox" checked={onlyFlagged} onChange={(e) => setOnlyFlagged(e.target.checked)} aria-label="Only flagged accounts and their counterparts" /> Flagged and counterparts only</label>
        </div>
        <ul className="fn-legend">
          {colourBy === 'bank' ? banks.map((b, i) => <li key={b}><i style={{ background: BANK_COLOURS[i % BANK_COLOURS.length] }} />{b}</li>) : <>
            <li><i style={{ background: COL.sel }} />Selected case</li><li><i style={{ background: COL.flagged }} />Flagged</li><li><i style={{ background: COL.other }} />Other accounts</li></>}
          {showTruth && <li><i className="ring" />Labelled laundering</li>}
          <li className="sub">Size = money moved · drag to move, shift-drag to pin</li>
        </ul>
      </div>
    </div>
  );
}
