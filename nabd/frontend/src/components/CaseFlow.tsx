// One case's money flow, left to right: money from outside → where it enters → the accounts that pass it on → where it
// leaves. Arrow width is the amount. Play replays the transfers in time order; hovering an account, an arrow or a
// timeline row highlights the same money everywhere.
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';

export type FlowNode = { id: string; bank: string; role: 'entry' | 'pass' | 'exit' | 'start' | 'single'; layer: number };
export type FlowEdge = { s: string; d: string; amount: number; n: number; first: string; last: string; cross_bank: number };
export type FlowEvent = { ts: string; src: string; dst: string; amount: number; kind: 'in' | 'inside' | 'out'; cross_bank: number };
export type Flow = { nodes: FlowNode[]; edges: FlowEdge[]; in_edges: { d: string; amount: number; n: number; first: string }[];
  out_edges: { s: string; amount: number; n: number; first: string }[]; events: FlowEvent[]; min_outside: number };
export type Member = { account: string; bank: string; kind: string; opened_days_ago: number; in_aed: number; out_aed: number };

export const ROLE: Record<FlowNode['role'], { label: string; color: string }> = {
  entry: { label: 'Money enters', color: '#2a78d6' },
  start: { label: 'Starts the loop', color: '#2a78d6' },
  pass: { label: 'Passes it on', color: '#a0661c' },
  exit: { label: 'Money leaves', color: '#d4458a' },
  single: { label: 'Linked account', color: '#8e8e93' },
};
const IN = '__in', OUT = '__out';
export const eventKey = (e: { src: string; dst: string; kind: string }) =>
  e.kind === 'in' ? `${IN}>${e.dst}` : e.kind === 'out' ? `${e.src}>${OUT}` : `${e.src}>${e.dst}`;
export const aed = (v: number) => (v >= 1e6 ? `AED ${(v / 1e6).toFixed(2)} m` : `AED ${Math.round(v / 1e3).toLocaleString('en-GB')} k`);
const when = (s: string) => new Date(s.replace(' ', 'T')).toLocaleString('en-GB', { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });

type Pos = { x: number; y: number };

export default function CaseFlow({ flow, members, active, onActive, step, onStep }: {
  flow: Flow; members: Member[]; active: string | null; onActive: (k: string | null) => void;
  step: number; onStep: (n: number) => void;
}) {
  const wrap = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 640, h: 360 });
  const [hoverNode, setHoverNode] = useState<string | null>(null);
  const [tip, setTip] = useState<{ x: number; y: number; html: React.ReactNode } | null>(null);
  const [playing, setPlaying] = useState(false);
  useLayoutEffect(() => {
    if (!wrap.current) return;
    const ro = new ResizeObserver(([e]) => setSize({ w: e.contentRect.width, h: Math.max(240, e.contentRect.height) }));
    ro.observe(wrap.current);
    return () => ro.disconnect();
  }, []);

  const N = flow.events.length;
  // replay: one transfer per tick for short cases, faster for long ones, so a replay takes about 15 seconds
  useEffect(() => {
    if (!playing) return;
    if (step >= N) { setPlaying(false); return; }
    const per = Math.max(1, Math.ceil(N / 36));
    const t = setTimeout(() => onStep(Math.min(N, step + per)), 420);
    return () => clearTimeout(t);
  }, [playing, step, N, onStep]);

  const hasIn = flow.in_edges.length > 0, hasOut = flow.out_edges.length > 0;
  const maxLayer = Math.max(0, ...flow.nodes.map((n) => n.layer));
  const cols = maxLayer + 1 + (hasIn ? 1 : 0) + (hasOut ? 1 : 0);
  // Phones: the flow runs top to bottom (a feed), names to the right of each dot. Wider: left to right.
  // Layout and arrows are computed in flow space (u along the flow, v across it), then mapped to x and y.
  const vertical = size.w < 520;
  const U = vertical ? size.h : size.w, V = vertical ? size.w : size.h;
  const padU = vertical ? 40 : 60, padV0 = vertical ? 24 : 34, padV1 = vertical ? 92 : 34;
  const perCol = Math.max(1, ...Object.values(flow.nodes.reduce<Record<number, number>>((acc, n) => ({ ...acc, [n.layer]: (acc[n.layer] ?? 0) + 1 }), {})));
  const dense = (V - padV0 - padV1) / perCol < (vertical ? 110 : 46);  // crowded layers: names on hover only
  const xy = (u: number, v: number): Pos => (vertical ? { x: v, y: u } : { x: u, y: v });
  const posF = useMemo(() => {
    const p = new Map<string, { u: number; v: number }>();
    const colU = (c: number) => (cols <= 1 ? U / 2 : padU + (c / (cols - 1)) * (U - 2 * padU));
    const byLayer = new Map<number, FlowNode[]>();
    flow.nodes.forEach((n) => byLayer.set(n.layer, [...(byLayer.get(n.layer) ?? []), n]));
    byLayer.forEach((ns, l) => {
      ns.sort((x, y) => x.bank.localeCompare(y.bank) || x.id.localeCompare(y.id));
      ns.forEach((n, i) => p.set(n.id, { u: colU(l + (hasIn ? 1 : 0)), v: padV0 + ((i + 0.5) / ns.length) * (V - padV0 - padV1) }));
    });
    const mid = vertical ? V / 2 - 20 : V / 2;
    if (hasIn) p.set(IN, { u: colU(0), v: mid });
    if (hasOut) p.set(OUT, { u: colU(cols - 1), v: mid });
    return p;
  }, [flow, U, V, cols, hasIn, hasOut, vertical, padU, padV0, padV1]);
  const pos = useMemo(() => new Map([...posF].map(([k, f]) => [k, xy(f.u, f.v)])), [posF, vertical]); // eslint-disable-line react-hooks/exhaustive-deps

  // every arrow: inside the case, plus money from and to outside accounts
  const arrows = useMemo(() => [
    ...flow.in_edges.map((e) => ({ key: `${IN}>${e.d}`, s: IN, d: e.d, amount: e.amount, n: e.n, first: e.first, last: e.first, cross: 0, kind: 'in' as const })),
    ...flow.edges.map((e) => ({ key: `${e.s}>${e.d}`, s: e.s, d: e.d, amount: e.amount, n: e.n, first: e.first, last: e.last, cross: e.cross_bank, kind: 'inside' as const })),
    ...flow.out_edges.map((e) => ({ key: `${e.s}>${OUT}`, s: e.s, d: OUT, amount: e.amount, n: e.n, first: e.first, last: e.first, cross: 0, kind: 'out' as const })),
  ], [flow]);
  const maxAmt = Math.max(1, ...arrows.map((a) => a.amount));
  const seen = useMemo(() => new Set(flow.events.slice(0, step).map(eventKey)), [flow, step]);
  const current = step > 0 && step <= N ? flow.events[step - 1] : null;
  const curKey = active ?? (playing || (step > 0 && step < N) ? (current ? eventKey(current) : null) : null);
  const movedSoFar = flow.events.slice(0, step).filter((e) => e.kind === 'inside').reduce((a, e) => a + e.amount, 0);
  const touched = useMemo(() => { const t = new Set<string>(); flow.events.slice(0, step).forEach((e) => { t.add(e.src); t.add(e.dst); }); return t; }, [flow, step]);
  const replaying = step < N;
  const member = new Map(members.map((m) => [m.account, m]));
  const linked = (k: string) => hoverNode != null && (k.startsWith(`${hoverNode}>`) || k.endsWith(`>${hoverNode}`));

  const colStep = cols <= 1 ? U : (U - 2 * padU) / (cols - 1);
  // Forward to the next layer: an S-curve. Back to an earlier account (a cycle): an arc on the far side.
  // Skipping layers: an arc on the near side, clear of the names, so it never runs through accounts in between.
  // Same layer: a bulge between the two. ra, rb: half-sizes (along, across) of the shape at each end.
  function path(a: { u: number; v: number }, b: { u: number; v: number }, ra: { u: number; v: number }, rb: { u: number; v: number }) {
    const P = (u: number, v: number) => { const q = xy(u, v); return `${q.x.toFixed(1)},${q.y.toFixed(1)}`; };
    const span = (b.u - a.u) / colStep, lift = Math.min(V / 2 - 24, 26 + Math.abs(b.u - a.u) * 0.22);
    if (Math.abs(span) <= 0.01) {
      const bulge = Math.min(colStep * 0.4, 18 + Math.abs(b.v - a.v) * 0.18);
      return `M${P(a.u + ra.u, a.v)} C${P(a.u + bulge, a.v)} ${P(b.u + bulge, b.v)} ${P(b.u + rb.u + 3, b.v)}`;
    }
    const names = vertical ? 0 : 40;  // names sit under each dot when the flow runs left to right
    if (span < 0) return `M${P(a.u, a.v - ra.v)} C${P(a.u, a.v - ra.v - lift)} ${P(b.u, b.v - rb.v - lift)} ${P(b.u, b.v - rb.v - 3)}`;
    if (span > 1.2 && Math.abs(b.v - a.v) < 40) {
      const side = vertical ? -1 : 1;
      const la = ra.u > 20 || dense ? ra.v : Math.max(ra.v, names), lb = rb.u > 20 || dense ? rb.v : Math.max(rb.v, names);
      return `M${P(a.u, a.v + side * la)} C${P(a.u, a.v + side * (la + lift))} ${P(b.u, b.v + side * (lb + lift))} ${P(b.u, b.v + side * (lb + 3))}`;
    }
    const u1 = a.u + ra.u, u2 = b.u - rb.u - 3, mu = (u1 + u2) / 2;
    return `M${P(u1, a.v)} C${P(mu, a.v)} ${P(mu, b.v)} ${P(u2, b.v)}`;
  }
  const showTip = (ev: React.PointerEvent, html: React.ReactNode) => {
    const r = wrap.current!.getBoundingClientRect();
    setTip({ x: Math.min(ev.clientX - r.left + 12, size.w - 230), y: Math.max(4, ev.clientY - r.top - 10), html });
  };

  return (
    <div className="cf">
      <div className="cf-stage" ref={wrap} style={vertical ? { flex: 'none', height: Math.max(360, cols * 92) } : undefined} onPointerLeave={() => { setTip(null); setHoverNode(null); onActive(null); }}>
        <svg width={size.w} height={size.h} role="img" aria-label="How the money moved through this case">
          <defs>
            {['base', 'hot'].map((t) => <marker key={t} id={`cf-arrow-${t}`} viewBox="0 0 10 10" refX="8" refY="5" markerWidth="9" markerHeight="9" markerUnits="userSpaceOnUse" orient="auto">
              <path d="M0,0 L10,5 L0,10 z" fill={t === 'hot' ? '#d70015' : 'rgba(60,60,67,.45)'} /></marker>)}
          </defs>
          {arrows.map((a) => {
            const pa = posF.get(a.s), pb = posF.get(a.d);
            if (!pa || !pb) return null;
            const hot = curKey === a.key || linked(a.key);
            const ghost = replaying && !seen.has(a.key);
            const w = 1.5 + 7 * Math.sqrt(a.amount / maxAmt);
            const r = dense ? 7 : 11, dot = { u: r, v: r }, box = vertical ? { u: 22, v: 46 } : { u: 46, v: 22 };
            const d = path(pa, pb, a.s === IN ? box : dot, a.d === OUT ? box : dot);
            return (
              <g key={a.key} className={`cf-edge ${hot ? 'hot' : ''} ${ghost ? 'ghost' : ''} ${hoverNode && !linked(a.key) ? 'dim' : ''}`}
                onPointerEnter={(ev) => { onActive(a.key); showTip(ev, <>
                  <strong>{aed(a.amount)}</strong>
                  <span>{a.kind === 'in' ? `from outside into ${a.d}` : a.kind === 'out' ? `from ${a.s} to outside` : `${a.s} → ${a.d}`}</span>
                  <span>{a.n} transfer{a.n > 1 ? 's' : ''} · {when(a.first)}{a.last !== a.first ? ` to ${when(a.last)}` : ''}</span>
                  {a.kind === 'inside' && <span>{a.cross ? 'Across banks' : 'Same bank'}</span>}
                </>); }}
                onPointerMove={(ev) => tip && showTip(ev, tip.html)} onPointerLeave={() => { onActive(null); setTip(null); }}>
                <path d={d} className="cf-hit" />
                <path d={d} className="cf-line" strokeWidth={hot ? w + 1.5 : w} markerEnd={`url(#cf-arrow-${hot ? 'hot' : 'base'})`} />
              </g>
            );
          })}
          {hasIn && <g className={`cf-outside ${replaying && !flow.events.slice(0, step).some((e) => e.kind === 'in') ? 'ghost' : ''}`} transform={`translate(${pos.get(IN)!.x},${pos.get(IN)!.y})`}>
            <rect x={-46} y={-22} width={92} height={44} rx={12} /><text y={-4} textAnchor="middle">From outside</text>
            <text y={11} textAnchor="middle" className="cf-sub">{aed(flow.in_edges.reduce((s, e) => s + e.amount, 0))}</text></g>}
          {hasOut && <g className={`cf-outside ${replaying && !flow.events.slice(0, step).some((e) => e.kind === 'out') ? 'ghost' : ''}`} transform={`translate(${pos.get(OUT)!.x},${pos.get(OUT)!.y})`}>
            <rect x={-46} y={-22} width={92} height={44} rx={12} /><text y={-4} textAnchor="middle">To outside</text>
            <text y={11} textAnchor="middle" className="cf-sub">{aed(flow.out_edges.reduce((s, e) => s + e.amount, 0))}</text></g>}
          {flow.nodes.map((n) => {
            const p = pos.get(n.id)!, m = member.get(n.id), hot = hoverNode === n.id || (curKey != null && (curKey.startsWith(`${n.id}>`) || curKey.endsWith(`>${n.id}`)));
            return (
              <g key={n.id} className={`cf-node ${replaying && !touched.has(n.id) ? 'ghost' : ''} ${hot ? 'hot' : ''}`} transform={`translate(${p.x},${p.y})`}
                onPointerEnter={(ev) => { setHoverNode(n.id); showTip(ev, <>
                  <strong>{n.id}</strong><span>{n.bank} · {ROLE[n.role].label}</span>
                  {m && <><span>{m.kind}, opened {m.opened_days_ago} days ago</span><span>In {aed(m.in_aed)} · out {aed(m.out_aed)} (14 days)</span></>}
                </>); }}
                onPointerLeave={() => { setHoverNode(null); setTip(null); }}>
                <circle r={dense ? (hot ? 8 : 6) : hot ? 12 : 10} fill={ROLE[n.role].color} />
                {(!dense || hot) && (vertical
                  ? <><text x={16} y={-1} className="cf-id">{n.id}</text><text x={16} y={11} className="cf-sub">{n.bank}</text></>
                  : <><text y={dense ? 18 : 24} textAnchor="middle" className="cf-id">{n.id}</text>
                    <text y={dense ? 30 : 36} textAnchor="middle" className="cf-sub">{n.bank}</text></>)}
              </g>
            );
          })}
        </svg>
        {tip && <div className="cf-tip" style={{ left: tip.x, top: tip.y }}>{tip.html}</div>}
      </div>
      <div className="cf-controls">
        <button type="button" className="btn small filled" onClick={() => { if (playing) setPlaying(false); else { if (step >= N) onStep(0); setPlaying(true); } }}>
          {playing ? 'Pause' : step >= N ? 'Replay the money' : 'Play'}
        </button>
        <input type="range" min={0} max={N} value={step} onChange={(e) => { setPlaying(false); onStep(Number(e.target.value)); }} aria-label="Point in time" />
        <span className="cf-clock num">{current && step < N ? <>{when(current.ts)} · {aed(movedSoFar)} moved inside so far</> : <>{N} transfers · {when(flow.events[0]?.ts ?? '')} to {when(flow.events[N - 1]?.ts ?? '')}</>}</span>
      </div>
      <ul className="cf-legend">
        {(['entry', 'pass', 'exit'] as const).map((r) => <li key={r}><i style={{ background: ROLE[r].color }} />{ROLE[r].label}</li>)}
        <li><i className="cf-key-line" />Arrow width = amount</li>
        {hasIn || hasOut ? <li className="sub">Outside: transfers of {aed(flow.min_outside)} or more</li> : null}
      </ul>
    </div>
  );
}
