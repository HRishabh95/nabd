import { useEffect, useRef, useState } from 'react';
import { api } from '../lib/api';
import Chart, { type ChartSpec } from './Chart';

// Test the nowcast: switch inputs on and off (refit and re-scored in seconds), and score CBUAE's own model on the
// same test, next to Kalman + AI news and the average of the two.
type Opts = { groups: Record<string, string[]>; labels: Record<string, string>; default: Record<string, string[]>;
  meta?: Record<string, { source: string; series: string; lag_days: number; transform: string }> };
type Sc = { rmse: number; rmse_excl_shock: number | null };
type Score = { horizon: 'mid' | 'end' | 'after'; n: number } & Record<string, Sc | number | string>;
type Result = { ok: boolean; message: string | null; inputs: string[]; scores: Score[]; cover70: Record<string, number>;
  track?: { quarter: string; actual: number; mine: number | null; default: number | null }[];
  forecast: { quarter: string; mine: number | null; default: number | null; lo70: number | null; hi70: number | null; contrib: Record<string, number> | null }[] };
type Own = { name: string; rows: number; skipped: number; scores: Score[] };

const HZ: Record<string, string> = { mid: 'Mid-quarter', end: 'Quarter end', after: 'Month after' };
const pct = (v: number | null | undefined) => (v == null ? '—' : `${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(v).toFixed(1)}%`);
const rm = (s: Score, k: string) => (s[k] as Sc | undefined)?.rmse;

export default function ForecastLab({ target, onClose }: { target: 'real' | 'non_oil'; onClose: () => void }) {
  const [tab, setTab] = useState<'inputs' | 'own'>('inputs');
  const [opts, setOpts] = useState<Opts | null>(null);
  const [on, setOn] = useState<Set<string>>(new Set());
  const [res, setRes] = useState<Result | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [own, setOwn] = useState<Own | null>(null);
  const [name, setName] = useState('CBUAE model');
  const panel = useRef<HTMLDivElement>(null);

  useEffect(() => { api.get<Opts>('/api/forecast/inputs').then((o) => { setOpts(o); setOn(new Set(o.default[target])); }); }, [target]);
  useEffect(() => { panel.current?.focus(); const k = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); }; window.addEventListener('keydown', k); return () => window.removeEventListener('keydown', k); }, [onClose]);

  async function run() {
    setBusy(true); setErr(null);
    try { setRes(await api.post<Result>('/api/forecast/inputs', { target, inputs: [...on] })); } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  }
  async function upload(f: File) {
    setBusy(true); setErr(null);
    try { setOwn(await api.post<Own>('/api/forecast/own', { target, csv: await f.text(), name })); } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  }
  const toggle = (k: string) => setOn((s) => { const n = new Set(s); if (n.has(k)) n.delete(k); else n.add(k); return n; });
  const isDefault = opts && on.size === opts.default[target].length && opts.default[target].every((k) => on.has(k));
  const label = target === 'real' ? 'real GDP' : 'non-oil GDP';

  return (
    <div className="lab-backdrop" onClick={onClose}>
      <div className="lab" role="dialog" aria-modal="true" aria-label="Test the nowcast" tabIndex={-1} ref={panel} onClick={(e) => e.stopPropagation()}>
        <div className="lab-head">
          <div><h2>Test the nowcast</h2><p className="sub">{label} · every test uses only data published at the time, scored against FCSC first releases</p></div>
          <button className="btn small" type="button" onClick={onClose}>Close</button>
        </div>
        <div className="segmented" role="group" aria-label="What to test">
          <button type="button" aria-pressed={tab === 'inputs'} onClick={() => setTab('inputs')}>Switch inputs</button>
          <button type="button" aria-pressed={tab === 'own'} onClick={() => setTab('own')}>Score your own model</button>
        </div>
        {err && <p className="note worse" role="alert">{err}</p>}

        {tab === 'inputs' && opts && (
          <div className="lab-body">
            <p className="note">Turn inputs on or off and press <b>Re-test</b>: the Kalman model is refitted at every past date and scored again, next to the model on the page (Kalman + AI news).</p>
            <div className="lab-groups">
              {Object.entries(opts.groups).map(([g, ks]) => (
                <fieldset key={g}><legend>{g}</legend>
                  {ks.map((k) => (
                    <label key={k} className="lab-check"><input type="checkbox" checked={on.has(k)} onChange={() => toggle(k)} />
                      <span>{opts.labels[k] ?? k}{opts.default[target].includes(k) && <i className="lab-def">in the page model</i>}
                        {opts.meta?.[k] && <i className="lab-meta">{opts.meta[k].source} · {opts.meta[k].transform} · published ~{opts.meta[k].lag_days} days after</i>}</span></label>
                  ))}
                </fieldset>
              ))}
            </div>
            <div className="lab-actions">
              <button className="btn filled small" type="button" disabled={busy || !on.size} onClick={run}>{busy ? 'Re-testing…' : 'Re-test'}</button>
              {!isDefault && <button className="btn small" type="button" onClick={() => setOn(new Set(opts.default[target]))}>Back to the page model</button>}
            </div>
            {res && !res.ok && <p className="note worse">{res.message}</p>}
            {res?.ok && (() => {
              const after = res.scores.find((x) => x.horizon === 'after');
              const a = after ? rm(after, 'mine') : undefined, b = after ? rm(after, 'default') : undefined;
              const verdict = a == null || b == null ? null : a < b - 0.1 ? 'better than' : a > b + 0.1 ? 'worse than' : 'about the same as';
              const tr = res.track ?? [];
              const x = [...tr.map((t) => t.quarter), ...res.forecast.map((f) => f.quarter).filter((q) => !tr.some((t) => t.quarter === q))];
              const tq = Object.fromEntries(tr.map((t) => [t.quarter, t])), fq = Object.fromEntries(res.forecast.map((f) => [f.quarter, f]));
              const chart: ChartSpec = { type: 'line', title: 'Your inputs against the page model', y_label: '% y/y · past: said a month after each quarter · right: forecast',
                x: x.map((q) => q.replace('Q', ' Q')),
                series: [{ name: 'Your inputs', values: x.map((q) => tq[q]?.mine ?? fq[q]?.mine ?? null) },
                  { name: 'Page model', values: x.map((q) => tq[q]?.default ?? fq[q]?.default ?? null) },
                  { name: 'FCSC first release', values: x.map((q) => tq[q]?.actual ?? null), dots: true }] };
              return (
              <>
                {verdict && <p className={`lab-verdict ${verdict.startsWith('better') ? 'better' : verdict.startsWith('worse') ? 'worse' : ''}`}>Your choice is <b>{verdict}</b> the page model: a month after each quarter it misses FCSC’s first figure by <b className="num">{a!.toFixed(1)}</b> points on average, against <b className="num">{b!.toFixed(1)}</b>.</p>}
                <Chart c={chart} height={230} />
                <p className="note">Dots are what FCSC published. The closer a line runs to the dots, the better that set of inputs did; on the right is what each would forecast now.</p>
                <h3>Error against first releases (percentage points, lower is better)</h3>
                <table className="lb lab-table"><thead><tr><th>When the nowcast was made</th><th className="r">Your inputs</th><th className="r">Page model</th><th className="r">Without Q2 2026</th><th className="r">70% band held</th></tr></thead>
                  <tbody>{res.scores.map((s) => {
                    const a = rm(s, 'mine'), b = rm(s, 'default');
                    return (<tr key={s.horizon}><td>{HZ[s.horizon]} <span className="sub">({s.n} quarters)</span></td>
                      <td className={`r num ${a != null && b != null ? (a < b - 0.05 ? 'better' : a > b + 0.05 ? 'worse' : '') : ''}`}>{a?.toFixed(2) ?? '—'}</td>
                      <td className="r num">{b?.toFixed(2) ?? '—'}</td>
                      <td className="r num">{(s.mine as Sc).rmse_excl_shock?.toFixed(2) ?? '—'} vs {(s.default as Sc).rmse_excl_shock?.toFixed(2) ?? '—'}</td>
                      <td className="r num">{res.cover70[s.horizon] ?? '—'}/{s.n}</td></tr>);
                  })}</tbody></table>
                <h3>Forecast with your inputs</h3>
                <table className="lb lab-table"><thead><tr><th>Quarter</th><th className="r">Your inputs</th><th className="r">70% band</th><th className="r">Page model</th></tr></thead>
                  <tbody>{res.forecast.map((f) => (
                    <tr key={f.quarter}><td>{f.quarter.replace('Q', ' Q')}</td><td className="r num">{pct(f.mine)}</td><td className="r num sub">{f.lo70 != null ? `${pct(f.lo70)} to ${pct(f.hi70)}` : '—'}</td><td className="r num">{pct(f.default)}</td></tr>
                  ))}</tbody></table>
                {res.forecast.find((f) => f.contrib) && (
                  <><h3>What drives the current quarter (percentage points)</h3>
                    <ul className="lab-contrib">{Object.entries(res.forecast.find((f) => f.contrib)!.contrib!).sort((x, y) => Math.abs(y[1]) - Math.abs(x[1])).map(([k, v]) => (
                      <li key={k}><span>{k === 'gdp' ? 'Past GDP releases' : opts.labels[k] ?? k}</span><b className={`num ${v < 0 ? 'worse' : v > 0 ? 'better' : ''}`}>{v > 0 ? '+' : ''}{v.toFixed(2)}</b></li>))}</ul></>
                )}
              </>
              ); })()}
          </div>
        )}

        {tab === 'own' && (
          <div className="lab-body">
            <p className="note">Upload the nowcasts your own model made in the past. Nabd scores each one against FCSC’s first release on the same dates as Kalman + AI news, and shows the <b>average of the two</b>: the standard way to add a new signal to an existing model. Your file stays on this machine.</p>
            <ol className="lab-steps">
              <li><a className="link-plain" href={`/api/forecast/own/template?target=${target}`} download>Download the template</a>: the released quarters, at the three dates Nabd scores.</li>
              <li>Fill the <i>value</i> column with what your model said on each date (% y/y). Extra rows on other dates are fine.</li>
              <li>Name it and upload: <input className="lab-name" value={name} onChange={(e) => setName(e.target.value)} aria-label="Name of your model" />
                <label className="btn small filled lab-file">Choose CSV<input type="file" accept=".csv,text/csv" onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} hidden /></label></li>
            </ol>
            {busy && <p className="note">Scoring…</p>}
            {own && (
              <>
                <h3>{own.name}: error against first releases (percentage points)</h3>
                <p className="sub">{own.rows} nowcasts scored{own.skipped ? `, ${own.skipped} skipped (no first release yet, or made after it was published)` : ''}</p>
                <table className="lb lab-table"><thead><tr><th>When</th><th className="r">{own.name}</th><th className="r">Kalman + AI news</th><th className="r">Average of the two</th></tr></thead>
                  <tbody>{own.scores.map((s) => {
                    const vals = ['yours', 'kalman_ai', 'average'].map((k) => rm(s, k) ?? Infinity);
                    const best = Math.min(...vals);
                    return (<tr key={s.horizon}><td>{HZ[s.horizon]} <span className="sub">({s.n})</span></td>
                      {vals.map((v, i) => <td key={i} className={`r num ${v === best ? 'best' : ''}`}>{Number.isFinite(v) ? v.toFixed(2) : '—'}</td>)}</tr>);
                  })}</tbody></table>
                <p className="note">If the average beats your model, the AI news signal is adding information your model does not have. With about ten quarters, treat differences under 20% as noise.</p>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
