// Charts built by the backend from tool data (Ask Nabd). Rules followed (dataviz guidance):
// one y-axis; categorical colours in a fixed, validated order (max 4 series); 2px lines; a legend for 2+ series and
// direct labels at line ends; recessive grid; crosshair + tooltip on lines, per-bar tooltip on bars; text in text
// tokens, never series colour; a table view for screen readers and exact values.
import { useLayoutEffect, useMemo, useRef, useState } from 'react';

export type ChartSpec = {
  type: 'line' | 'bar'; title: string; y_label: string; x: (string | number)[]; x_label?: string | null;
  series: { name: string; values: (number | null)[]; dots?: boolean }[]; band?: { lo: (number | null)[]; hi: (number | null)[] } | null;
  evidence?: string[];
};

// validated palette (light surface): bronze, blue, magenta, teal; adjacent CVD ΔE ≥ 6.2 with direct labels
export const SERIES = ['#a0661c', '#2a78d6', '#d4458a', '#138a62'];

// Gridlines that always contain the data: rounded out to a "nice" step on both ends.
function niceTicks(min: number, max: number, n = 4): { ticks: number[]; step: number } {
  if (!Number.isFinite(min) || !Number.isFinite(max)) return { ticks: [0, 1], step: 1 };
  if (min === max) { const d = Math.abs(min) * 0.05 || 1; min -= d; max += d; }
  const step0 = (max - min) / n, mag = 10 ** Math.floor(Math.log10(step0));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((st) => st >= step0) ?? step0;
  const lo = Math.floor(min / step + 1e-9) * step, hi = Math.ceil(max / step - 1e-9) * step;
  const ticks = [];
  for (let v = lo; v <= hi + step * 1e-6; v += step) ticks.push(+v.toFixed(10));
  return { ticks, step };
}

const minus = (t: string) => t.replace(/^-/, '−');
const fmtNum = (v: number) => minus(Math.abs(v) >= 1000 ? v.toLocaleString('en-GB', { maximumFractionDigits: 0 }) : Math.abs(v) >= 10 ? v.toFixed(1) : v.toFixed(2));
const fmtTick = (v: number, step: number) => {
  const d = step >= 1 ? 0 : step >= 0.1 ? 1 : 2;
  return minus(Math.abs(v) >= 1000 ? v.toLocaleString('en-GB', { maximumFractionDigits: 0 }) : v.toFixed(d));
};
const isDate = (x: string | number) => /^\d{4}-\d{2}(-\d{2})?$/.test(String(x));
const toDate = (x: string | number) => new Date(String(x).length === 7 ? `${x}-01` : String(x));
// short spans read best as "12 Oct"; long spans as "Oct 26"
const fmtX = (x: string | number, spanDays = 9999) => {
  if (!isDate(x)) return String(x);
  return toDate(x).toLocaleDateString('en-GB', spanDays <= 200 && String(x).length === 10 ? { day: 'numeric', month: 'short' } : { month: 'short', year: '2-digit' });
};
const fmtXFull = (x: string | number) => (isDate(x) ? toDate(x).toLocaleDateString('en-GB', String(x).length === 10 ? { day: 'numeric', month: 'short', year: 'numeric' } : { month: 'long', year: 'numeric' }) : String(x));

function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [w, setW] = useState(420);
  useLayoutEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver(([e]) => setW(Math.max(260, e.contentRect.width)));
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);
  return [ref, w] as const;
}

function Legend({ series }: { series: ChartSpec['series'] }) {
  if (series.length < 2) return null;
  return <ul className="ch-legend">{series.map((s, i) => <li key={s.name}><i style={{ background: SERIES[i] }} />{s.name}</li>)}</ul>;
}

function Table({ c }: { c: ChartSpec }) {
  return (
    <div className="table-wrap ch-table"><table>
      <thead><tr><th>{c.x_label ?? ''}</th>{c.series.map((s) => <th key={s.name} className="r">{s.name}</th>)}</tr></thead>
      <tbody>{c.x.map((x, i) => <tr key={i}><td className="num">{String(x)}</td>{c.series.map((s) => <td key={s.name} className="r num">{s.values[i] == null ? '—' : fmtNum(s.values[i] as number)}</td>)}</tr>)}</tbody>
    </table></div>
  );
}

function LineChart({ c: full, w, h = 190 }: { c: ChartSpec; w: number; h?: number }) {
  // drop leading and trailing points where no series has a value, so the axis starts where the data does
  const c = useMemo(() => {
    const has = (i: number) => full.series.some((s) => s.values[i] != null) || (full.band?.lo[i] != null);
    let a = 0, b = full.x.length - 1;
    while (a < b && !has(a)) a++;
    while (b > a && !has(b)) b--;
    const cut = <T,>(v: T[]) => v.slice(a, b + 1);
    return { ...full, x: cut(full.x), series: full.series.map((s) => ({ ...s, values: cut(s.values) })),
      band: full.band ? { lo: cut(full.band.lo), hi: cut(full.band.hi) } : full.band };
  }, [full]);
  const [hover, setHover] = useState<number | null>(null);
  const all = [...c.series.flatMap((s) => s.values), ...(c.band?.lo ?? []), ...(c.band?.hi ?? [])].filter((v): v is number => v != null);
  const { ticks, step } = niceTicks(Math.min(...all), Math.max(...all), h < 170 ? 3 : 4);
  const y0 = ticks[0], y1 = ticks[ticks.length - 1];
  const tickW = Math.max(...ticks.map((t) => fmtTick(t, step).length)) * 6.2 + 10;
  // direct labels at line ends only when there is room; the legend always names the series
  const longest = Math.max(...c.series.map((s) => s.name.length));
  const direct = c.series.length > 1 && w >= 560;
  const labelW = direct ? Math.min(150, longest * 6.3 + 16) : 10;
  const M = { t: 10, r: labelW, b: 24, l: tickW }, H = Math.min(h, w < 480 ? 220 : h);
  const iw = Math.max(40, w - M.l - M.r), ih = H - M.t - M.b;
  const n = c.x.length;
  const x = (i: number) => M.l + (n < 2 ? iw / 2 : (i / (n - 1)) * iw);
  const y = (v: number) => M.t + ih - ((v - y0) / (y1 - y0 || 1)) * ih;
  const path = (vals: (number | null)[]) => { let d = '', pen = false; vals.forEach((v, i) => { if (v == null) { pen = false; return; } d += `${pen ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`; pen = true; }); return d; };
  const spanDays = n > 1 && isDate(c.x[0]) ? (toDate(c.x[n - 1]).getTime() - toDate(c.x[0]).getTime()) / 864e5 : 9999;
  const nx = Math.max(2, Math.min(n, Math.floor(iw / 90) + 1));
  const xt = Array.from({ length: nx }, (_, k) => Math.round((k * (n - 1)) / (nx - 1))).filter((v, i, a) => a.indexOf(v) === i);
  const maxChars = Math.max(4, Math.floor((labelW - 16) / 6.3));
  const ends = c.series.map((s, i) => { let k = s.values.length - 1; while (k > 0 && s.values[k] == null) k--; const v = s.values[k]; return { i, k, name: s.name, v, yy: v == null ? 0 : y(v) }; })
    .filter((e) => e.v != null).sort((a, b) => a.yy - b.yy);
  ends.forEach((e, k) => { if (k && e.yy - ends[k - 1].yy < 13) e.yy = ends[k - 1].yy + 13; });
  function move(ev: React.PointerEvent<SVGRectElement>) {
    const r = (ev.currentTarget as SVGRectElement).getBoundingClientRect();
    setHover(Math.max(0, Math.min(n - 1, Math.round(((ev.clientX - r.left) / r.width) * (n - 1)))));
  }
  const tipLeft = hover == null ? 0 : x(hover) > w - 190 ? Math.max(0, x(hover) - 176) : x(hover) + 12;
  return (
    <div className="ch-plot">
      <svg width={w} height={H} role="img" aria-label={c.title}>
        {ticks.map((t) => <g key={t}><line x1={M.l} x2={M.l + iw} y1={y(t)} y2={y(t)} className={Math.abs(t) < step * 1e-6 ? 'ch-zero' : 'ch-grid'} /><text x={M.l - 6} y={y(t) + 3.5} textAnchor="end" className="ch-tick">{fmtTick(t, step)}</text></g>)}
        {xt.map((i, k) => <text key={i} x={x(i)} y={H - 6} textAnchor={k === 0 ? 'start' : k === xt.length - 1 ? 'end' : 'middle'} className="ch-tick">{fmtX(c.x[i], spanDays)}</text>)}
        {c.band && <path className="ch-band" d={`${path(c.band.hi)}${c.band.lo.map((_, k) => { const i = c.band!.lo.length - 1 - k, v = c.band!.lo[i]; return v == null ? '' : `L${x(i).toFixed(1)},${y(v).toFixed(1)}`; }).join('')}Z`} />}
        {c.series.map((s, i) => <path key={s.name} d={path(s.values)} fill="none" stroke={SERIES[i]} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />)}
        {c.series.map((s, i) => s.dots ? <g key={`${s.name}-dots`}>{s.values.map((v, k) => v == null ? null : <circle key={k} cx={x(k)} cy={y(v)} r={3.5} fill={SERIES[i]} stroke="#fff" strokeWidth={1.5} />)}</g> : null)}
        {c.series.map((s, i) => n < 40 && s.values.map((v, k) => v != null && (s.values[k - 1] == null && s.values[k + 1] == null) && <circle key={`${s.name}${k}`} cx={x(k)} cy={y(v)} r={3} fill={SERIES[i]} />))}
        {ends.map((e) => <circle key={e.name} cx={x(e.k)} cy={y(e.v!)} r={3} fill={SERIES[e.i]} />)}
        {direct && ends.map((e) => <text key={e.name} x={M.l + iw + 8} y={e.yy + 3.5} className="ch-direct">{e.name.length > maxChars ? `${e.name.slice(0, maxChars - 1)}…` : e.name}<title>{e.name}</title></text>)}
        {hover != null && <g pointerEvents="none"><line x1={x(hover)} x2={x(hover)} y1={M.t} y2={M.t + ih} className="ch-cross" />
          {c.series.map((s, i) => s.values[hover] != null && <circle key={s.name} cx={x(hover)} cy={y(s.values[hover] as number)} r={4} fill={SERIES[i]} stroke="#fff" strokeWidth={2} />)}</g>}
        <rect x={M.l} y={M.t} width={iw} height={ih} fill="transparent" onPointerMove={move} onPointerDown={move} onPointerLeave={() => setHover(null)} />
      </svg>
      {hover != null && (
        <div className="ch-tip" style={{ left: tipLeft, top: 6 }}>
          <strong>{fmtXFull(c.x[hover])}{c.x_label ? ` · ${c.x_label} ${c.x[hover]}` : ''}</strong>
          {c.series.map((s, i) => <span key={s.name}><i style={{ background: SERIES[i] }} />{s.name}<b className="num">{s.values[hover] == null ? '—' : fmtNum(s.values[hover] as number)}</b></span>)}
          {c.band && c.band.lo[hover] != null && <span className="sub">70% band {fmtNum(c.band.lo[hover] as number)} to {fmtNum(c.band.hi[hover] as number)}</span>}
        </div>
      )}
    </div>
  );
}

function BarChart({ c, w }: { c: ChartSpec; w: number }) {
  const s = c.series[0], vals = s.values.map((v) => v ?? 0);
  const labelW = Math.min(150, Math.max(...c.x.map((x) => String(x).length)) * 6.4 + 8);
  const mn = Math.min(0, ...vals), mx = Math.max(0, ...vals), span = mx - mn || 1;
  // room for value labels on both sides, so a long negative bar never runs into its category label
  const padL = mn < 0 ? 44 : 0, padR = mx > 0 ? 44 : 8;
  const row = 22, H = c.x.length * row + 8, iw = w - labelW - padL - padR;
  const x = (v: number) => labelW + padL + ((v - mn) / span) * iw;
  const [hover, setHover] = useState<number | null>(null);
  return (
    <div className="ch-plot">
      <svg width={w} height={H} role="img" aria-label={c.title}>
        <line x1={x(0)} x2={x(0)} y1={0} y2={H} className="ch-zero" />
        {c.x.map((lab, i) => {
          const v = vals[i], x0 = x(Math.min(0, v)), bw = Math.max(1, Math.abs(x(v) - x(0)));
          return (
            <g key={i} onPointerEnter={() => setHover(i)} onPointerLeave={() => setHover(null)}>
              <rect x={0} y={i * row} width={w} height={row} fill="transparent" />
              <text x={labelW - 8} y={i * row + 15} textAnchor="end" className="ch-cat">{String(lab).length > 24 ? `${String(lab).slice(0, 23)}…` : String(lab)}</text>
              <rect x={x0} y={i * row + 5} width={bw} height={row - 10} rx={4} fill={SERIES[0]} opacity={hover == null || hover === i ? 1 : 0.55} />
              <text x={v < 0 ? x0 - 4 : x0 + bw + 4} y={i * row + 15} textAnchor={v < 0 ? 'end' : 'start'} className="ch-val">{fmtNum(v)}</text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

export default function Chart({ c, height }: { c: ChartSpec; height?: number }) {
  const [ref, w] = useWidth<HTMLDivElement>();
  const [table, setTable] = useState(false);
  const usable = useMemo(() => ({ ...c, series: c.series.slice(0, 4) }), [c]);
  return (
    <figure className="chart-card" ref={ref}>
      <figcaption className="ch-head">
        <span><strong>{c.title}</strong><span className="sub">{c.y_label}</span></span>
        <button type="button" className="link-btn" onClick={() => setTable((t) => !t)} aria-pressed={table}>{table ? 'Chart' : 'Table'}</button>
      </figcaption>
      {usable.type === 'line' && <Legend series={usable.series} />}
      {table ? <Table c={usable} /> : usable.type === 'line' ? <LineChart c={usable} w={w} h={height} /> : <BarChart c={usable} w={w} />}
    </figure>
  );
}
