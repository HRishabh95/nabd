import { forceCollide, forceLink, forceManyBody, forceSimulation, forceX, forceY, type SimulationNodeDatum } from 'd3-force';
import { useLayoutEffect, useMemo, useRef, useState } from 'react';
import { aed, type Flow, type FlowNode } from './CaseFlow';

// Fraud ring view: every detected network is a bubble; the open one shows its accounts and the transfers between
// them (arrows in time order), with the outside money that came in and went out. Click a bubble to open it, click
// an account to trace where its money came from (blue) and went (orange).
export type Net = { id: string; size: number; banks: number; flow_aed: number; transfers: number; pattern: { key: string; label: string; hub: string | null } };
export type Account = { account: string; bank: string; risk: number; role: string | null };

type N = SimulationNodeDatum & { id: string; kind: 'net' | 'acc' | 'in' | 'out'; r: number; net?: Net; acc?: Account; label: string };
type E = { s: string; d: string; amount: number; n: number; first: string; order: number; kind: 'inside' | 'in' | 'out' };

const riskColor = (r: number) => (r >= 0.9 ? '#c62828' : r >= 0.6 ? '#e0603a' : r >= 0.25 ? '#e9a23b' : '#a3a3ab');
const SHORT: Record<string, string> = { cycle: 'Circular', chain: 'Chain', fan_in: 'Fan-in', fan_out: 'Fan-out', scatter_gather: 'Scatter-gather', gather_scatter: 'Gather-scatter', mixed: 'Mixed' };

export default function FraudGraph({ nets, open, flow, accounts, selected, cutoff, onOpen, onSelect }: {
  nets: Net[]; open: string | null; flow: Flow | null; accounts: Account[]; selected: string | null; cutoff: string | null;
  onOpen: (id: string | null) => void; onSelect: (acc: string | null) => void;
}) {
  const wrap = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 800, h: 520 });
  const [hover, setHover] = useState<{ x: number; y: number; text: string } | null>(null);
  const [drag, setDrag] = useState<Record<string, { x: number; y: number }>>({});
  useLayoutEffect(() => {
    if (!wrap.current) return;
    const ro = new ResizeObserver(([e]) => setSize({ w: e.contentRect.width, h: Math.max(320, e.contentRect.height) }));
    ro.observe(wrap.current);
    return () => ro.disconnect();
  }, []);

  const accBy = useMemo(() => Object.fromEntries(accounts.map((a) => [a.account, a])), [accounts]);
  const edges: E[] = useMemo(() => {
    if (!flow || !open) return [];
    const inside = [...flow.edges].sort((a, b) => a.first.localeCompare(b.first)).map((e, i) => ({ ...e, order: i + 1, kind: 'inside' as const }));
    const ins = flow.in_edges.map((e) => ({ s: `in:${e.d}`, d: e.d, amount: e.amount, n: e.n, first: e.first, order: 0, kind: 'in' as const }));
    const outs = flow.out_edges.map((e) => ({ s: e.s, d: `out:${e.s}`, amount: e.amount, n: e.n, first: e.first, order: 0, kind: 'out' as const }));
    return [...inside, ...ins, ...outs];
  }, [flow, open]);

  // layout: run the forces to rest once per network, then draw (no jitter while reading)
  const nodes: N[] = useMemo(() => {
    const { w, h } = size;
    const cx = w / 2, cy = h / 2;
    const maxFlow = Math.max(...nets.map((n) => n.flow_aed), 1);
    const others = nets.filter((n) => n.id !== open);
    // with a network open, the others sit evenly on an ellipse round the edge (fixed), the open one fills the middle
    const ns: N[] = others.map((n, i) => {
      const r = open ? 9 + 8 * Math.sqrt(n.flow_aed / maxFlow) : 10 + 16 * Math.sqrt(n.flow_aed / maxFlow);
      const a = -Math.PI / 2 + (i / others.length) * 2 * Math.PI;
      return { id: `net:${n.id}`, kind: 'net', net: n, label: n.id, r,
        ...(open ? { fx: cx + (w / 2 - 17 - 16) * Math.cos(a), fy: cy + (h / 2 - 17 - 22) * Math.sin(a) } : {}) };  // inside by the largest bubble plus a margin
    });
    if (open && flow) {
      flow.nodes.forEach((f: FlowNode) => ns.push({ id: f.id, kind: 'acc', acc: accBy[f.id] ?? { account: f.id, bank: f.bank, risk: 0, role: f.role }, label: f.id, r: 13, x: cx + (f.layer - 2) * 60, y: cy }));
      flow.in_edges.forEach((e) => ns.push({ id: `in:${e.d}`, kind: 'in', label: 'outside', r: 5 }));
      flow.out_edges.forEach((e) => ns.push({ id: `out:${e.s}`, kind: 'out', label: 'outside', r: 5 }));
    }
    const sim = forceSimulation<N>(ns)
      .force('charge', forceManyBody<N>().strength((n) => (n.kind === 'net' ? -40 : n.kind === 'acc' ? -480 : -40)))
      .force('collide', forceCollide<N>((n) => n.r + (n.kind === 'net' ? 6 : 10)))
      .force('link', forceLink<N, { source: string | N; target: string | N }>(edges.map((e) => ({ source: e.s, target: e.d }))).id((n) => n.id)
        .distance((l) => ((l.source as N).kind === 'acc' && (l.target as N).kind === 'acc' ? Math.min(200, Math.min(w, h) / 3.2) : 50)).strength(0.7))
      .force('x', forceX<N>(cx).strength((n) => (n.kind === 'net' && open ? 0 : 0.06)))
      .force('y', forceY<N>(cy).strength((n) => (n.kind === 'net' && open ? 0 : 0.09)))
      .stop();
    for (let i = 0; i < 320; i++) sim.tick();
    ns.forEach((n) => { if (n.fx != null) { n.x = n.fx; n.y = n.fy ?? n.y; return; } n.x = Math.max(n.r + 4, Math.min(w - n.r - 4, n.x ?? cx)); n.y = Math.max(n.r + 18, Math.min(h - n.r - 4, n.y ?? cy)); });
    return ns;
  }, [nets, open, flow, accBy, edges, size]);

  const pos = (id: string) => drag[id] ?? (() => { const n = nodes.find((x) => x.id === id); return { x: n?.x ?? 0, y: n?.y ?? 0 }; })();

  // money trace from the selected account: everything upstream and downstream along inside transfers
  const trace = useMemo(() => {
    if (!selected) return { up: new Set<string>(), down: new Set<string>() };
    const walk = (dir: 'down' | 'up') => {
      const seen = new Set<string>([selected]);
      const q = [selected];
      while (q.length) {
        const x = q.shift()!;
        edges.filter((e) => e.kind === 'inside' && (dir === 'down' ? e.s === x : e.d === x)).forEach((e) => {
          const y = dir === 'down' ? e.d : e.s;
          if (!seen.has(y)) { seen.add(y); q.push(y); }
        });
      }
      return seen;
    };
    return { up: walk('up'), down: walk('down') };
  }, [selected, edges]);

  const maxAmt = Math.max(...edges.map((e) => e.amount), 1);
  const visible = (e: E) => !cutoff || e.first <= cutoff;
  const edgeClass = (e: E) => {
    if (!selected) return '';
    if (trace.down.has(e.s) && trace.down.has(e.d)) return 'down';
    if (trace.up.has(e.s) && trace.up.has(e.d)) return 'up';
    return 'dim';
  };

  function startDrag(ev: React.PointerEvent, id: string) {
    const svg = (ev.currentTarget as SVGElement).ownerSVGElement!;
    const box = svg.getBoundingClientRect();
    const move = (m: PointerEvent) => setDrag((d) => ({ ...d, [id]: { x: m.clientX - box.left, y: m.clientY - box.top } }));
    const up = () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up); };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  }

  return (
    <div className="fg" ref={wrap} onMouseLeave={() => setHover(null)}>
      <svg width={size.w} height={size.h} role="img" aria-label="Detected fraud networks and the money between their accounts"
        onClick={(e) => { if (e.target === e.currentTarget) onSelect(null); }}>
        <defs>
          {['base', 'down', 'up', 'outside'].map((k) => (
            <marker key={k} id={`fg-arrow-${k}`} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="11" markerHeight="11" markerUnits="userSpaceOnUse" orient="auto-start-reverse">
              <path d="M0,0 L10,5 L0,10 z" className={`fg-head ${k}`} />
            </marker>
          ))}
        </defs>
        {edges.filter(visible).map((e) => {
          const a = pos(e.s), b = pos(e.d);
          const ra = nodes.find((n) => n.id === e.s)?.r ?? 6, rb = nodes.find((n) => n.id === e.d)?.r ?? 6;
          const dx = b.x - a.x, dy = b.y - a.y, len = Math.hypot(dx, dy) || 1;
          const sx = a.x + (dx / len) * ra, sy = a.y + (dy / len) * ra, tx = b.x - (dx / len) * (rb + 3), ty = b.y - (dy / len) * (rb + 3);
          const bend = e.kind === 'inside' ? 0.18 : 0;  // curve so transfers both ways stay apart
          const mx = (sx + tx) / 2 - dy * bend, my = (sy + ty) / 2 + dx * bend;
          const cls = e.kind === 'inside' ? edgeClass(e) : 'outside';
          const wdt = e.kind === 'inside' ? 1.5 + 5 * Math.sqrt(e.amount / maxAmt) : 1;
          const text = `${e.kind === 'in' ? 'From outside → ' + e.d : e.kind === 'out' ? e.s + ' → outside' : e.s + ' → ' + e.d}: ${aed(e.amount)} in ${e.n} transfer${e.n > 1 ? 's' : ''}, first ${e.first.slice(5, 16)}`;
          return (
            <g key={`${e.s}-${e.d}`} className={`fg-edge ${cls}`} onMouseMove={(m) => setHover({ x: m.nativeEvent.offsetX, y: m.nativeEvent.offsetY, text })}>
              <path d={`M${sx},${sy} Q${mx},${my} ${tx},${ty}`} strokeWidth={wdt} markerEnd={`url(#fg-arrow-${cls === 'down' || cls === 'up' ? cls : cls === 'outside' ? 'outside' : 'base'})`} />
              <path d={`M${sx},${sy} Q${mx},${my} ${tx},${ty}`} className="fg-hit" />
              {e.order > 0 && <g className="fg-badge" transform={`translate(${(sx + 2 * mx + tx) / 4},${(sy + 2 * my + ty) / 4})`}><circle r={8} /><text>{e.order}</text></g>}
            </g>
          );
        })}
        {nodes.map((n) => {
          const p = pos(n.id);
          if (n.kind === 'net') {
            const net = n.net!;
            return (
              <g key={n.id} className="fg-net" transform={`translate(${p.x},${p.y})`} onClick={() => onOpen(net.id)}
                role="button" tabIndex={0} aria-label={`Open network ${net.id}: ${net.pattern.label}, ${net.size} accounts, ${aed(net.flow_aed)}`}
                onKeyDown={(k) => { if (k.key === 'Enter' || k.key === ' ') { k.preventDefault(); onOpen(net.id); } }}
                onMouseMove={(m) => setHover({ x: m.nativeEvent.offsetX, y: m.nativeEvent.offsetY, text: `${net.id} · ${net.pattern.label} · ${net.size} accounts, ${net.banks} banks · ${aed(net.flow_aed)} moved — click to open` })}>
                <circle r={n.r} />
                <text y={4} className="fg-net-id">{net.id}</text>
                {!open && n.r > 16 && <text y={n.r + 11} className="fg-net-sub">{SHORT[net.pattern.key]}</text>}
              </g>
            );
          }
          if (n.kind !== 'acc') return <circle key={n.id} cx={p.x} cy={p.y} r={n.r} className="fg-outside" />;
          const a = n.acc!;
          const on = selected === a.account;
          const traced = selected && (trace.up.has(a.account) || trace.down.has(a.account));
          return (
            <g key={n.id} className={`fg-acc ${on ? 'on' : ''} ${selected && !traced ? 'dim' : ''}`} transform={`translate(${p.x},${p.y})`}
              onPointerDown={(ev) => startDrag(ev, n.id)} onClick={(ev) => { ev.stopPropagation(); onSelect(on ? null : a.account); }}
              role="button" tabIndex={0} aria-pressed={on} aria-label={`Account ${a.account}, ${a.bank}, ML risk ${a.risk.toFixed(2)}: trace its money`}
              onKeyDown={(k) => { if (k.key === 'Enter' || k.key === ' ') { k.preventDefault(); onSelect(on ? null : a.account); } }}
              onMouseMove={(m) => setHover({ x: m.nativeEvent.offsetX, y: m.nativeEvent.offsetY, text: `${a.account} · ${a.bank} · ML risk ${a.risk.toFixed(2)} · ${a.role === 'entry' || a.role === 'start' ? 'money enters here' : a.role === 'exit' ? 'money leaves here' : 'passes money on'}` })}>
              <circle r={n.r} fill={riskColor(a.risk)} />
              {(a.role === 'entry' || a.role === 'start' || a.role === 'exit') && <circle r={n.r + 4} className="fg-role" />}
              <text y={n.r + 13} className="fg-acc-id">{a.account}</text>
              <text y={n.r + 24} className="fg-acc-bank">{a.bank}</text>
            </g>
          );
        })}
        {open && <g className="fg-close" transform="translate(12,10)" onClick={() => onOpen(null)} role="button" tabIndex={0} aria-label="Show all networks"
          onKeyDown={(k) => { if (k.key === 'Enter' || k.key === ' ') { k.preventDefault(); onOpen(null); } }}><rect width={124} height={24} rx={12} /><text x={62} y={16}>Show all networks</text></g>}
      </svg>
      {hover && <div className="fg-tip" style={{ left: Math.min(hover.x + 12, size.w - 260), top: hover.y + 12 }}>{hover.text}</div>}
    </div>
  );
}
