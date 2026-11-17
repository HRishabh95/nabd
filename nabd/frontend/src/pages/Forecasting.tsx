import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { Card, PageHeader } from '../components/Chrome';
import Chart, { type ChartSpec } from '../components/Chart';
import { api } from '../lib/api';
import { useEvent } from '../lib/stream';

type Band = [number, number] | null;
type ModelVal = { value: number; band70: Band; band90: Band };
type Score = { model: string; horizon: 'mid' | 'end' | 'after'; n: number; rmse: number; mae: number; rel_rmse: number | null; direction: number };
type Moved = { input: string; label: string; now: number | null; change: number };
type Target = {
  label: string; pending: string; current: string; champion: Score | null;
  backtest: { scores: Score[]; rows: { quarter: string; horizon: string; model: string; nowcast: number; actual: number }[] };
  paths: Record<string, Record<string, number | string | null>[]>;
  latest: Record<string, { horizon: string; models: Record<string, ModelVal>; observed_months: Record<string, number>; train_quarters: number; moved_4w: Moved[] }>;
  released: { quarter: string; value: number; release_date: string; source: string; source_type: string }[];
};
type Input = { name: string; label: string; unit: string; last_month: string; last_level: number; last_value: number | null; value_3m_ago: number | null; lag_days: number };
type Run = { created: number; today: string; run_id: string; seconds: number; targets: Record<string, Target>; inputs: Input[];
  card: { name: string; method: string; limits: string; validation: string } };
type ScenarioOut = { quarter: string; base: Record<string, number>; scenario: Record<string, number> };

const MODEL_NAME: Record<string, string> = { benchmark: 'Last release (benchmark)', factor: 'Dynamic factor model', midas: 'MIDAS on the factor', bridge: 'Bridge regression', news: 'News model', ensemble: 'Ensemble' };
const ORDER = ['ensemble', 'bridge', 'factor', 'midas', 'news', 'benchmark'];
const HORIZON: Record<string, string> = { mid: 'Mid-quarter', end: 'Quarter end', after: 'A month after' };
const pct = (v: number | null | undefined, d = 1) => (v == null ? '—' : `${v > 0 ? '+' : ''}${v.toFixed(d)}%`);
const qLabel = (q: string) => q.replace('Q', ' Q');
const day = (s: string) => new Date(s).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });

// Height available to the chart inside its card, so the plot fills the card without scrolling.
function useHeight<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [h, setH] = useState(220);
  useLayoutEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver(([e]) => setH(e.contentRect.height));
    ro.observe(ref.current);
    return () => ro.disconnect();
  });
  return [ref, h] as const;
}

export default function Forecasting() {
  const [plotRef, plotH] = useHeight<HTMLDivElement>();
  const [run, setRun] = useState<Run | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [target, setTarget] = useState<'non_oil' | 'real'>('non_oil');
  const [quarter, setQuarter] = useState<string | null>(null);
  const [model, setModel] = useState('ensemble');
  const [compare, setCompare] = useState(false);
  const [horizon, setHorizon] = useState<'mid' | 'end' | 'after'>('after');
  const [job, setJob] = useState<{ progress: number; message: string } | null>(null);
  const [hormuz, setHormuz] = useState(20);
  const [brent, setBrent] = useState(90);
  const [scen, setScen] = useState<ScenarioOut | null>(null);
  const [scenBusy, setScenBusy] = useState(false);

  const load = useCallback(() => api.get<Run>('/api/forecast').then((r) => { setRun(r); setErr(null); }, (e) => setErr(e.message)), []);
  useEffect(() => { load(); }, [load]);
  useEvent('job.progress', (e) => { if (e.data.kind === 'nowcast') setJob({ progress: Number(e.data.progress), message: String(e.data.message) }); });
  useEvent('job.done', (e) => { if (e.data.kind === 'nowcast') { setJob(null); load(); } });
  useEvent('job.failed', (e) => { if (e.data.kind === 'nowcast') { setJob(null); setErr(String(e.data.error)); } });

  const T = run?.targets[target] ?? run?.targets.non_oil;
  const q = quarter && T?.paths[quarter] ? quarter : T?.current ?? null;
  const latestQ = q && T?.latest[q];
  const official = useMemo(() => T?.released.find((r) => r.quarter === q), [T, q]);

  const chart: ChartSpec | null = useMemo(() => {
    if (!T || !q) return null;
    const pts = T.paths[q] ?? [];
    if (!pts.length) return null;
    // compare what a committee asks about: the ensemble, the champion, the model in view and the naive benchmark
    const champKey = T.champion?.model;
    const keys = compare
      ? [...new Set(['ensemble', champKey, model, 'benchmark', 'bridge', 'factor', 'midas', 'news'])]
          .filter((k): k is string => !!k && pts.some((p) => p[k] != null)).slice(0, official ? 3 : 4)
      : [model];
    const series = keys.map((k) => ({ name: `${MODEL_NAME[k]}${compare && k === champKey ? ' (champion)' : ''}`, values: pts.map((p) => (p[k] == null ? null : Number(p[k]))) }));
    if (official && series.length < 4) series.push({ name: `Official first release (${day(official.release_date)})`, values: pts.map(() => official.value) });
    const sc = T.backtest.scores.find((s) => s.model === model && s.horizon === horizon);
    const band = !compare && sc ? { lo: series[0].values.map((v) => (v == null ? null : +(v - 1.036 * sc.rmse).toFixed(2))), hi: series[0].values.map((v) => (v == null ? null : +(v + 1.036 * sc.rmse).toFixed(2))) } : null;
    return { type: 'line', title: `${qLabel(q)} ${T.label.charAt(0).toLowerCase()}${T.label.slice(1)}: the nowcast week by week`, y_label: band ? '% y/y · band holds 70% of past errors' : '% y/y', x: pts.map((p) => String(p.as_of)), series, band };
  }, [T, q, model, compare, official, horizon]);

  async function runNow() { setErr(null); setJob({ progress: 0, message: 'Starting' }); try { await api.post('/api/forecast/run'); } catch (e) { setErr((e as Error).message); setJob(null); } }
  async function runScenario() {
    setScenBusy(true);
    try { setScen(await api.post<ScenarioOut>('/api/forecast/scenario', { target, hormuz_ships: hormuz, brent })); } finally { setScenBusy(false); }
  }

  if (!run || !T || !q) {
    return (<><PageHeader title="Forecasting" lede="UAE GDP nowcast from shipping, markets and news, before FCSC publishes" />
      <div className="fill grid"><Card title="Nowcast" className="s12">{err ? <><p className="note">{err}</p><button className="btn filled small" type="button" onClick={runNow}>Run nowcast</button></> : <p className="note">Loading…</p>}</Card></div></>);
  }
  const champ = T.champion;
  const bench = T.backtest.scores.find((s) => s.model === 'benchmark' && s.horizon === 'after');
  const lastOfficial = T.released[T.released.length - 1];
  const hz = run.inputs.find((i) => i.name === 'hormuz');
  const pendingV = T.latest[T.pending]?.models[model] ?? T.latest[T.pending]?.models.ensemble;
  const currentV = T.latest[T.current]?.models[model] ?? T.latest[T.current]?.models.ensemble;
  const scores = T.backtest.scores.filter((s) => s.horizon === horizon).sort((a, b) => ORDER.indexOf(a.model) - ORDER.indexOf(b.model));
  const moved = latestQ ? latestQ.moved_4w.slice(0, 6) : [];
  const mMax = Math.max(...moved.map((m) => Math.abs(m.change)), 0.01);
  const quarters = Object.keys(T.paths);

  return (
    <>
      <PageHeader title="Forecasting" lede={`UAE GDP nowcast from shipping, markets and news, before FCSC publishes · run ${run.run_id} · ${day(run.today)}`}
        actions={<button className="btn small" type="button" onClick={runNow} disabled={!!job}>{job ? `Running ${Math.round(job.progress * 100)}%` : 'Run backtest'}</button>} />
      <dl className="metrics fc-metrics">
        <div className="metric"><dt>Nowcast {qLabel(T.pending)} · {MODEL_NAME[model].toLowerCase()}</dt><dd className={`num ${(pendingV?.value ?? 0) < 0 ? 'worse' : ''}`}>{pct(pendingV?.value)}</dd><span className="num">{pendingV?.band70 ? `70% band ${pct(pendingV.band70[0])} to ${pct(pendingV.band70[1])}` : ''}</span></div>
        <div className="metric"><dt>Nowcast {qLabel(T.current)} (in progress)</dt><dd className={`num ${(currentV?.value ?? 0) < 0 ? 'worse' : ''}`}>{pct(currentV?.value)}</dd><span className="num">{currentV?.band70 ? `70% band ${pct(currentV.band70[0])} to ${pct(currentV.band70[1])}` : ''}</span></div>
        <div className="metric"><dt>Last official · {qLabel(lastOfficial.quarter)}</dt><dd className={`num ${lastOfficial.value < 0 ? 'worse' : ''}`}>{pct(lastOfficial.value)}</dd><span>FCSC, published {day(lastOfficial.release_date)}</span></div>
        <div className="metric"><dt>Champion model</dt><dd>{champ ? MODEL_NAME[champ.model].replace(' regression', '') : '—'}</dd><span className="num">{champ && bench ? `error ${champ.rmse.toFixed(2)} pts vs ${bench.rmse.toFixed(2)} for the benchmark` : ''}</span></div>
        <div className="metric"><dt>Hormuz transits</dt><dd className="num worse">{hz ? `${hz.last_level.toFixed(1)}/day` : '—'}</dd><span className="num">{hz ? `${pct(hz.last_value, 0)} on a year earlier · ${hz.last_month}` : ''}</span></div>
      </dl>
      <div className="fill grid fc-grid2">
        <article className="card s8 fc-main">
          <div className="card-head">
            <div><h2>Nowcast path</h2><p className="sub">{latestQ ? `${latestQ.train_quarters} official quarters to learn from · inputs observed: ${Object.values(latestQ.observed_months).length ? Math.max(...Object.values(latestQ.observed_months)) : 0} of 3 months` : ''}</p></div>
            <div className="head-ctl">
              <div className="segmented" role="group" aria-label="Target">
                <button type="button" aria-pressed={target === 'non_oil'} onClick={() => setTarget('non_oil')}>Non-oil</button>
                <button type="button" aria-pressed={target === 'real'} onClick={() => setTarget('real')} disabled={!run.targets.real}>Real GDP</button>
              </div>
              <div className="segmented" role="group" aria-label="Quarter">
                {quarters.map((k) => <button key={k} type="button" aria-pressed={k === q} onClick={() => setQuarter(k)}>{qLabel(k)}{T.released.some((r) => r.quarter === k) ? ' · test' : ''}</button>)}
              </div>
              <select className="popup" value={model} onChange={(e) => setModel(e.target.value)} aria-label="Model">{ORDER.filter((k) => T.latest[T.current]?.models[k]).map((k) => <option key={k} value={k}>{MODEL_NAME[k]}</option>)}</select>
              <label className="switch small-sw"><input type="checkbox" checked={compare} onChange={(e) => setCompare(e.target.checked)} aria-label="Compare all models" /> Compare</label>
            </div>
          </div>
          <div className="fc-plot" ref={plotRef}>{chart && <Chart c={chart} height={Math.max(150, plotH - 74)} />}
            {official && <p className="note">{qLabel(q)} is a test quarter: each point is what the model said on that date, using only data published by then. FCSC published {pct(official.value)} on {day(official.release_date)} (<a className="link-plain" href={official.source} target="_blank" rel="noreferrer">source</a>).</p>}
          </div>
        </article>
        <article className="card s4">
          <div className="card-head"><div><h2>Model leaderboard</h2><p className="sub">Error against FCSC first releases, percentage points</p></div>
            <div className="segmented" role="group" aria-label="Horizon">{(['mid', 'end', 'after'] as const).map((h) => <button key={h} type="button" aria-pressed={horizon === h} onClick={() => setHorizon(h)}>{HORIZON[h].replace('A month after', 'After')}</button>)}</div></div>
          <div className="table-wrap scroll">
            <table className="lb"><thead><tr><th>Model</th><th className="r">RMSE</th><th className="r">vs benchmark</th><th className="r">Quarters</th></tr></thead>
              <tbody>{scores.map((s) => (
                <tr key={s.model} className={`pick ${model === s.model ? 'on' : ''}`} onClick={() => s.model !== 'benchmark' && setModel(s.model)}>
                  <td>{MODEL_NAME[s.model]}{champ?.model === s.model && <span className="pill green small-pill">Champion</span>}</td>
                  <td className="r num">{s.rmse.toFixed(2)}</td>
                  <td className={`r num ${s.rel_rmse != null && s.rel_rmse < 1 ? 'better' : s.rel_rmse != null && s.rel_rmse > 1 ? 'worse' : ''}`}>{s.model === 'benchmark' ? '—' : s.rel_rmse == null ? '—' : `${s.rel_rmse < 1 ? '−' : '+'}${Math.abs((1 - s.rel_rmse) * 100).toFixed(0)}%`}</td>
                  <td className="r num">{s.n}</td>
                </tr>
              ))}</tbody></table>
            <p className="note">Champion: lowest error a month after the quarter ends. Pseudo real-time: each nowcast used only data published by its date. {run.card.limits}.</p>
          </div>
        </article>
        <article className="card s4">
          <div className="card-head"><div><h2>What moved the nowcast</h2><p className="sub">{qLabel(q)}, change over the last 4 weeks, percentage points</p></div></div>
          <ul className="bars moved scroll">{moved.map((m) => (
            <li key={m.input}><span>{m.label}</span><span className="dbar"><i className={m.change < 0 ? 'neg' : 'pos'} style={{ width: `${Math.abs(m.change) / mMax * 50}%` }} /></span><span className="num">{m.change > 0 ? '+' : ''}{m.change.toFixed(2)}</span></li>
          ))}{!moved.length && <li className="sub">No change computed for this quarter.</li>}</ul>
        </article>
        <article className="card s4">
          <div className="card-head"><div><h2>Inputs</h2><p className="sub">Latest month, change on a year earlier</p></div></div>
          <div className="table-wrap scroll"><table className="inputs"><thead><tr><th>Indicator</th><th className="r">Month</th><th className="r">Now</th><th className="r">3 months ago</th></tr></thead>
            <tbody>{run.inputs.filter((i) => i.last_value != null).map((i) => (
              <tr key={i.name} title={`${i.unit} · published with a ${i.lag_days}-day lag`}><td>{i.label}</td><td className="r num">{i.last_month}</td>
                <td className={`r num ${i.unit.includes('%') && (i.last_value ?? 0) < -20 ? 'worse' : ''}`}>{i.unit === 'level' ? i.last_value?.toFixed(1) : i.unit.includes('%') ? pct(i.last_value, 0) : (i.last_value ?? 0).toFixed(2)}</td>
                <td className="r num sub">{i.value_3m_ago == null ? '—' : i.unit === 'level' ? i.value_3m_ago.toFixed(1) : i.unit.includes('%') ? pct(i.value_3m_ago, 0) : i.value_3m_ago.toFixed(2)}</td></tr>
            ))}</tbody></table></div>
        </article>
        <article className="card s4">
          <div className="card-head"><div><h2>Scenario</h2><p className="sub">If these hold for the rest of {qLabel(T.current)}</p></div></div>
          <div className="scen-form">
            <label><span>Hormuz transits <b className="num">{hormuz} ships/day</b></span><input type="range" min={0} max={80} value={hormuz} aria-label="Hormuz transits, ships per day" onChange={(e) => setHormuz(Number(e.target.value))} /></label>
            <label><span>Brent <b className="num">USD {brent}</b></span><input type="range" min={40} max={160} step={5} value={brent} aria-label="Brent, US dollars per barrel" onChange={(e) => setBrent(Number(e.target.value))} /></label>
            <button className="btn filled small" type="button" onClick={runScenario} disabled={scenBusy}>{scenBusy ? 'Computing…' : 'Compute nowcast'}</button>
          </div>
          {scen && (
            <div className="scroll"><table className="scen-out"><thead><tr><th>Model</th><th className="r">Now</th><th className="r">Scenario</th></tr></thead>
              <tbody>{ORDER.filter((k) => scen.scenario[k] != null && k !== 'benchmark').map((k) => (
                <tr key={k}><td>{MODEL_NAME[k]}</td><td className="r num">{pct(scen.base[k])}</td><td className={`r num ${scen.scenario[k] > scen.base[k] ? 'better' : scen.scenario[k] < scen.base[k] ? 'worse' : ''}`}>{pct(scen.scenario[k])}</td></tr>
              ))}</tbody></table></div>
          )}
          {!scen && <p className="note">In 2019 about 69 ships a day used the strait. The scenario changes only the months not yet observed.</p>}
        </article>
      </div>
      {err && <p className="note worse">{err}</p>}
    </>
  );
}
