// Payment network on a canvas: hundreds of accounts stay smooth. Drag to pan, scroll to zoom, hover for details.
// Colour carries one job only: highlighted (selected case) vs flagged by the method vs everything else.
import { useEffect, useLayoutEffect, useRef, useState } from 'react';

export type NNode = { id: string; x: number; y: number; bank: string; kind: string; truth: number };
export type NEdge = { s: string; d: string; amount: number; n: number };

const C = { base: 'rgba(120,120,128,0.35)', edge: 'rgba(120,120,128,0.10)', flagged: '#a0661c', sel: '#d70015',
  selEdge: 'rgba(215,0,21,0.55)', flagEdge: 'rgba(160,102,28,0.35)', truth: '#2a78d6' };

export default function NetworkCanvas({ nodes, edges, flagged, selected, showTruth, onPick }: {
  nodes: NNode[]; edges: NEdge[]; flagged: Set<string>; selected: Set<string>; showTruth: boolean; onPick?: (id: string) => void;
}) {
  const wrap = useRef<HTMLDivElement>(null);
  const cv = useRef<HTMLCanvasElement>(null);
  const [size, setSize] = useState({ w: 600, h: 400 });
  const [view, setView] = useState({ k: 1, x: 0, y: 0 });
  const [hover, setHover] = useState<{ n: NNode; px: number; py: number } | null>(null);
  const drag = useRef<{ x: number; y: number; vx: number; vy: number } | null>(null);
  const byId = useRef(new Map<string, NNode>());
  byId.current = new Map(nodes.map((n) => [n.id, n]));

  useLayoutEffect(() => {
    if (!wrap.current) return;
    const ro = new ResizeObserver(([e]) => setSize({ w: e.contentRect.width, h: e.contentRect.height }));
    ro.observe(wrap.current);
    return () => ro.disconnect();
  }, []);
  // fit the layout to the box, and zoom to the selected case when one is chosen
  const bounds = (ids?: Set<string>) => {
    const ns = ids && ids.size ? nodes.filter((n) => ids.has(n.id)) : nodes;
    const xs = ns.map((n) => n.x), ys = ns.map((n) => n.y);
    return { x0: Math.min(...xs), x1: Math.max(...xs), y0: Math.min(...ys), y1: Math.max(...ys) };
  };
  const base = bounds();
  const pad = 24;
  const sx = (size.w - 2 * pad) / (base.x1 - base.x0 || 1), sy = (size.h - 2 * pad) / (base.y1 - base.y0 || 1);
  const s0 = Math.min(sx, sy);
  const tx = (x: number) => (pad + (x - base.x0) * s0) * view.k + view.x;
  const ty = (y: number) => (pad + (y - base.y0) * s0) * view.k + view.y;
  useEffect(() => {
    if (!selected.size) { setView({ k: 1, x: 0, y: 0 }); return; }
    const b = bounds(selected);
    const cx = pad + ((b.x0 + b.x1) / 2 - base.x0) * s0, cy = pad + ((b.y0 + b.y1) / 2 - base.y0) * s0;
    const span = Math.max((b.x1 - b.x0) * s0, (b.y1 - b.y0) * s0, 60);
    const k = Math.min(6, Math.max(1, (Math.min(size.w, size.h) * 0.6) / span));
    setView({ k, x: size.w / 2 - cx * k, y: size.h / 2 - cy * k });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected, size.w, size.h, nodes]);

  useEffect(() => {
    const c = cv.current;
    if (!c) return;
    const dpr = window.devicePixelRatio || 1;
    c.width = size.w * dpr; c.height = size.h * dpr;
    const g = c.getContext('2d')!;
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, size.w, size.h);
    const m = byId.current;
    const layer = (pred: (e: NEdge) => boolean, color: string, wmul: number) => {
      g.strokeStyle = color;
      for (const e of edges) {
        if (!pred(e)) continue;
        const a = m.get(e.s), b = m.get(e.d);
        if (!a || !b) continue;
        g.lineWidth = Math.min(3, 0.4 + Math.log10(1 + e.amount) / 6) * wmul;
        g.beginPath(); g.moveTo(tx(a.x), ty(a.y)); g.lineTo(tx(b.x), ty(b.y)); g.stroke();
      }
    };
    layer((e) => !(flagged.has(e.s) && flagged.has(e.d)), C.edge, 1);
    layer((e) => flagged.has(e.s) && flagged.has(e.d) && !(selected.has(e.s) && selected.has(e.d)), C.flagEdge, 1.2);
    layer((e) => selected.has(e.s) && selected.has(e.d), C.selEdge, 1.8);
    for (const n of nodes) {
      const sel = selected.has(n.id), fl = flagged.has(n.id);
      const r = (sel ? 5 : fl ? 3.6 : 2.2) * Math.min(1.8, Math.sqrt(view.k));
      g.beginPath(); g.arc(tx(n.x), ty(n.y), r, 0, Math.PI * 2);
      g.fillStyle = sel ? C.sel : fl ? C.flagged : C.base; g.fill();
      if (showTruth && n.truth) { g.lineWidth = 1.5; g.strokeStyle = C.truth; g.beginPath(); g.arc(tx(n.x), ty(n.y), r + 2.5, 0, Math.PI * 2); g.stroke(); }
    }
  });

  function nearest(px: number, py: number) {
    let best: NNode | null = null, bd = 64;
    for (const n of nodes) { const d = (tx(n.x) - px) ** 2 + (ty(n.y) - py) ** 2; if (d < bd) { bd = d; best = n; } }
    return best;
  }
  return (
    <div className="net" ref={wrap}
      onWheel={(e) => { const r = wrap.current!.getBoundingClientRect(); const px = e.clientX - r.left, py = e.clientY - r.top; const f = e.deltaY < 0 ? 1.15 : 1 / 1.15;
        setView((v) => { const k = Math.min(12, Math.max(0.6, v.k * f)); const kk = k / v.k; return { k, x: px - (px - v.x) * kk, y: py - (py - v.y) * kk }; }); }}
      onPointerDown={(e) => { drag.current = { x: e.clientX, y: e.clientY, vx: view.x, vy: view.y }; }}
      onPointerUp={(e) => { const d = drag.current; drag.current = null; if (d && Math.abs(e.clientX - d.x) + Math.abs(e.clientY - d.y) < 4 && hover && onPick) onPick(hover.n.id); }}
      onPointerLeave={() => { drag.current = null; setHover(null); }}
      onPointerMove={(e) => { const r = wrap.current!.getBoundingClientRect(); const px = e.clientX - r.left, py = e.clientY - r.top;
        if (drag.current) { const d = drag.current; setView((v) => ({ ...v, x: d.vx + e.clientX - d.x, y: d.vy + e.clientY - d.y })); return; }
        const n = nearest(px, py); setHover(n ? { n, px, py } : null); }}>
      <canvas ref={cv} style={{ width: size.w, height: size.h }} role="img" aria-label="Payment network: flagged accounts in bronze, the selected case in red" />
      {hover && <div className="net-tip" style={{ left: Math.min(hover.px + 12, size.w - 180), top: Math.max(4, hover.py - 10) }}>
        <strong>{hover.n.id}</strong><span>{hover.n.bank} · {hover.n.kind}</span>
        {flagged.has(hover.n.id) && <span className="flag">Flagged by this method</span>}
        {showTruth && hover.n.truth ? <span className="truthy">Labelled laundering</span> : null}
      </div>}
      <ul className="net-legend"><li><i style={{ background: C.sel }} />Selected case</li><li><i style={{ background: C.flagged }} />Flagged</li><li><i style={{ background: C.base }} />Other accounts</li>{showTruth && <li><i className="ring" />Labelled laundering</li>}</ul>
    </div>
  );
}
