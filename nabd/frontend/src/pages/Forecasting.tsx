import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { PageHeader } from '../components/Chrome';
import Chart, { type ChartSpec } from '../components/Chart';
import { api } from '../lib/api';
import { useEvent } from '../lib/stream';
import ForecastLab from '../components/ForecastLab';

// One model, shown two ways: the Kalman nowcast on hard data, and the same model with AI news; set against the IMF.
type Variant = 'kalman' | 'kalman_ai';
type Score = { model: string; horizon: 'mid' | 'end' | 'after'; n: number; rmse: number; rmse_excl_shock: number | null; shock_error: number | null; cover70?: number };
type Step = { input: string; label: string; group: string; change: number };
type Waterfall = { from_date: string; to_date: string; from: number; to: number; steps: Step[] } | null;
type ModelNow = { value: number; sd: number; band70: [number, number]; contrib: { input: string; label: string; group: string; value: number }[] };
type Latest = { models: Partial<Record<Variant | 'kalman_tone', ModelNow>>; week: Waterfall; month: Waterfall; since_start: Waterfall };
type Fc = { quarter: string; value: number; lo70: number; hi70: number };
type Imf = { vintage: string; published: string; year: number; value: number; source: string; note: string; needed_rest: number | null };
type Annual = { year: number; official: Record<string, number>; rest: string[]; imf: Imf[];
  models: Partial<Record<Variant, { value: number; lo70: number; hi70: number; quarters: Record<string, { value: number; official: boolean }> }>> };
type Target = { label: string; pending: string; current: string; shock: string; backtest: { scores: Score[] };
  track: ({ quarter: string; actual: number | null; later?: number } & Partial<Record<Variant, number | null>>)[]; forecast: Record<Variant, Fc[]>;
  latest: Record<string, Latest>; annual: Annual[]; released: { quarter: string; value: number; release_date: string }[] };
type Month = { month: string; headlines: number; relevant: number; nonoil: number | null; up?: number; down?: number };
type Run = { today: string; run_id: string; created: number; targets: Record<string, Target>;
  signal: { months: string[]; nonoil: (number | null)[]; oil: (number | null)[] }; months: Month[]; archive: { headlines: number } };
type Headline = { title: string; source: string; url: string; date: string; relevant: boolean; sector_label: string; direction: number; reason?: string | null };

const NAME: Record<string, string> = { kalman_ai: 'Kalman + AI news', kalman: 'Kalman, hard data only', benchmark: 'Last official release' };
const pct = (v: number | null | undefined, d = 1) => (v == null ? '—' : `${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(v).toFixed(d)}%`);
const pp = (v: number) => `${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(v).toFixed(2)}`;
const qLabel = (q: string) => q.replace('Q', ' Q');
const day = (s: string) => new Date(s).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });
const monthLabel = (m: string) => new Date(`${m}-01`).toLocaleDateString('en-GB', { month: 'long', year: 'numeric' });
const DIR = ['Clearly weaker', 'Weaker', 'Neutral', 'Stronger', 'Clearly stronger'];

function quarters(from: string, to: string): string[] {
  const [y0, q0] = from.split('Q').map(Number), [y1, q1] = to.split('Q').map(Number);
  const out: string[] = [];
  for (let y = y0, q = q0; y < y1 || (y === y1 && q <= q1); q === 4 ? (y++, q = 1) : q++) out.push(`${y}Q${q}`);
  return out;
}

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
  const [sigRef, sigH] = useHeight<HTMLDivElement>();
  const [run, setRun] = useState<Run | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [target, setTarget] = useState<'non_oil' | 'real'>('real');
  const [span, setSpan] = useState<'week' | 'month' | 'since_start'>('month');
  const [month, setMonth] = useState<string | null>(null);
  const [heads, setHeads] = useState<Headline[] | null>(null);
  const [relOnly, setRelOnly] = useState(true);
  const [how, setHow] = useState(false);
  const [job, setJob] = useState<{ progress: number; message: string } | null>(null);
  const [lab, setLab] = useState(false);

  const load = useCallback(() => api.get<Run>('/api/forecast').then((r) => { setRun(r); setErr(null); }, (e) => setErr(e.message)), []);
  useEffect(() => { load(); }, [load]);
  useEvent('job.progress', (e) => { if (e.data.kind === 'nowcast') setJob({ progress: Number(e.data.progress), message: String(e.data.message) }); });
  useEvent('job.done', (e) => { if (e.data.kind === 'nowcast') { setJob(null); load(); } });
  useEvent('job.failed', (e) => { if (e.data.kind === 'nowcast') { setJob(null); setErr(String(e.data.error)); } });

  const T = run?.targets[target];
  const R = run?.targets.real;
  const months = useMemo(() => (run?.months ?? []).filter((m) => m.relevant > 0).map((m) => m.month).reverse(), [run]);
  const m = month && months.includes(month) ? month : months[0] ?? null;

  useEffect(() => {
    if (!m) return;
    setHeads(null);
    api.get<{ headlines: Headline[] }>(`/api/forecast/headlines?month=${m}`).then((r) => setHeads(r.headlines), () => setHeads([]));
  }, [m]);

  // track record (what each model said a month after each released quarter) and the forecast, on one quarterly axis
  const chart: ChartSpec | null = useMemo(() => {
    if (!T) return null;
    const fc = T.forecast.kalman_ai.length ? T.forecast.kalman_ai : T.forecast.kalman;
    if (!T.track.length || !fc.length) return null;
    const x = quarters(T.track[0].quarter, fc[fc.length - 1].quarter);
    const tr = Object.fromEntries(T.track.map((t) => [t.quarter, t]));
    const official = Object.fromEntries(T.released.map((r) => [r.quarter, r.value]));
    const f = (v: Variant) => Object.fromEntries(T.forecast[v].map((p) => [p.quarter, p]));
    const fa = f('kalman_ai'), fh = f('kalman');
    // join the last released quarter to the forecast so each model's line runs on into the future
    const lastTrack = T.track[T.track.length - 1].quarter;
    const line = (v: Variant, fx: Record<string, Fc>) => x.map((q) => fx[q]?.value ?? (tr[q]?.[v] ?? null));
    return {
      type: 'line', title: `${T.label}: track record and forecast`, x: x.map(qLabel),
      y_label: '% y/y · past: what the model said a month after the quarter · shaded: 70% band',
      series: [
        { name: NAME.kalman_ai, values: line('kalman_ai', fa) },
        { name: NAME.kalman, values: line('kalman', fh) },
        { name: 'FCSC release', values: x.map((q) => official[q] ?? tr[q]?.later ?? null), dots: true },
      ],
      band: { lo: x.map((q) => fa[q]?.lo70 ?? (q === lastTrack ? tr[q]?.kalman_ai ?? null : null)), hi: x.map((q) => fa[q]?.hi70 ?? (q === lastTrack ? tr[q]?.kalman_ai ?? null : null)) },
    };
  }, [T]);

  const sigChart: ChartSpec | null = useMemo(() => {
    const s = run?.signal;
    if (!s || !s.months.length) return null;
    // three-month average for reading; the model itself takes each month as it is published
    const avg = (v: (number | null)[]) => v.map((_, i) => { const w = v.slice(Math.max(0, i - 2), i + 1).filter((x): x is number => x != null); return w.length ? +(w.reduce((a, b) => a + b, 0) / w.length).toFixed(3) : null; });
    return { type: 'line', title: 'AI news signal, three-month average', y_label: 'balance: % of headlines saying stronger minus % weaker', x: s.months,
      series: [{ name: 'Non-oil activity', values: avg(s.nonoil) }, { name: 'Oil and gas', values: avg(s.oil) }] };
  }, [run]);

  async function start(path: string) {
    setErr(null); setJob({ progress: 0, message: 'Starting' });
    try { await api.post(path); } catch (e) { setErr((e as Error).message); setJob(null); }
  }
  const lede = 'UAE GDP from a Kalman nowcast, with and without news read by AI, set against the IMF';
  const actions = (
    <div className="fc-actions">
      <button className="btn small filled" type="button" onClick={() => setLab(true)} title="Switch inputs on and off, or score your own model on the same test">Test the nowcast</button>
      <button className="btn small" type="button" disabled={!!job} onClick={() => start('/api/forecast/run')}>{job ? `Running ${Math.round(job.progress * 100)}%` : 'Rerun nowcast'}</button>
      <button className="btn small" type="button" disabled={!!job} onClick={() => start('/api/forecast/news')} title="Fetch new headlines, have the LLM label them, then rerun the nowcast">Update AI news</button>
    </div>
  );

  if (!run || !T || !R) {
    return (<><PageHeader title="Forecasting" lede={lede} actions={actions} />
      <div className="fill grid"><article className="card s12"><div className="card-head"><div><h2>Nowcast</h2></div></div>
        <p className="note">{err ?? 'Loading…'}</p>{job && <p className="note">{job.message}</p>}</article></div></>);
  }

  const now = (t: Target, q: string, v: Variant) => t.latest[q]?.models[v];
  const pend = now(T, T.pending, 'kalman_ai'), cur = now(T, T.current, 'kalman_ai');
  const pendHard = now(T, T.pending, 'kalman'), curHard = now(T, T.current, 'kalman');
  const yr = R.annual;
  const sc = (model: string, h: string) => T.backtest.scores.find((s) => s.model === model && s.horizon === h);
  const lastOfficial = T.released[T.released.length - 1];
  const L = T.latest[T.current] ?? T.latest[T.pending];
  const wf = L?.[span] ?? null;
  const wMax = Math.max(...(wf?.steps ?? []).map((s) => Math.abs(s.change)), 0.01);
  const shown = (heads ?? []).filter((h) => !relOnly || h.relevant);
  const mInfo = run.months.find((x) => x.month === m);
  const imfNow = (a?: Annual) => a?.imf.find((i) => i.vintage.includes('October')) ?? a?.imf[0];

  return (
    <>
      <PageHeader title="Forecasting" lede={`${lede} · run ${run.run_id} · ${day(run.today)}`} actions={actions} />
      <dl className="metrics fc-metrics">
        <div className="metric"><dt>{T.label.split(',')[0]} · {qLabel(T.pending)}</dt><dd className="num">{pct(pend?.value)}</dd><span className="num">{pendHard ? `without AI ${pct(pendHard.value)}` : ''}</span></div>
        <div className="metric"><dt>{qLabel(T.current)} (in progress)</dt><dd className="num">{pct(cur?.value)}</dd><span className="num">{curHard ? `without AI ${pct(curHard.value)}` : ''}</span></div>
        {yr.map((a) => (
          <div className="metric" key={a.year}><dt>Real GDP {a.year} · Kalman + AI</dt><dd className="num">{pct(a.models.kalman_ai?.value)}</dd><span className="num">{imfNow(a) ? `IMF ${pct(imfNow(a)!.value)} (${imfNow(a)!.vintage.replace('WEO ', '')})` : ''}</span></div>
        ))}
        <div className="metric"><dt>Last official · {qLabel(lastOfficial.quarter)}</dt><dd className="num">{pct(lastOfficial.value)}</dd><span>FCSC, {day(lastOfficial.release_date)}</span></div>
      </dl>
      <div className="fill grid fc-grid2">
        <article className="card s8 fc-main">
          <div className="card-head">
            <div><h2>Track record and forecast</h2><p className="sub">The same Kalman model, with and without AI news; every past point used only data published by then</p></div>
            <div className="head-ctl">
              <div className="segmented" role="group" aria-label="Target">
                <button type="button" aria-pressed={target === 'real'} onClick={() => setTarget('real')}>Real GDP</button>
                <button type="button" aria-pressed={target === 'non_oil'} onClick={() => setTarget('non_oil')}>Non-oil</button>
              </div>
            </div>
          </div>
          <div className="fc-plot"><div className="fc-chart" ref={plotRef}>{chart && <Chart c={chart} height={Math.max(150, plotH - 74)} />}</div>
            <p className="note">Dots are FCSC’s published figures; the lines are what the model said at the time, and on the right its forecast.</p>
          </div>
        </article>
        <article className="card s4">
          <div className="card-head"><div><h2>Kalman against the IMF</h2><p className="sub">Real GDP growth for the full year, %</p></div></div>
          <div className="scroll">
            <table className="lb ai-acc"><thead><tr><th>Forecast</th>{yr.map((a) => <th key={a.year} className="r">{a.year}</th>)}</tr></thead>
              <tbody>
                {(['kalman_ai', 'kalman'] as Variant[]).map((v) => (
                  <tr key={v} className={v === 'kalman_ai' ? 'on' : ''}><td>{NAME[v]}</td>{yr.map((a) => <td key={a.year} className="r num">{pct(a.models[v]?.value)}</td>)}</tr>))}
                {[...new Set(yr.flatMap((a) => a.imf.map((i) => i.vintage)))].map((vin) => (
                  <tr key={vin}><td>IMF, {vin.replace('WEO', 'World Economic Outlook')}</td>{yr.map((a) => <td key={a.year} className="r num">{pct(a.imf.find((i) => i.vintage === vin)?.value)}</td>)}</tr>))}
              </tbody></table>
            {yr[0] && imfNow(yr[0])?.needed_rest != null && (
              <p className="note ai-insight">{yr[0].year} already has {Object.keys(yr[0].official).map((q) => `${qLabel(q).split(' ')[1]} ${pct(yr[0].official[q])}`).join(' and ')} published. For the IMF’s {pct(imfNow(yr[0])!.value)} to hold, {yr[0].rest.map((q) => qLabel(q).split(' ')[1]).join(' and ')} would have to average <b>{pct(imfNow(yr[0])!.needed_rest)}</b>; the model has {yr[0].rest.map((q) => `${pct(yr[0].models.kalman_ai?.quarters[q]?.value)}`).join(' and ')}.</p>)}
            <p className="note">Full year = average of the four quarterly rates, published quarters as released. IMF figures as reported (<a className="link-plain" href={imfNow(yr[0])?.source} target="_blank" rel="noreferrer">source</a>); the April row is derived from the revisions reported.</p>
            <p className="note">Track record, {T.label.split(',')[0].toLowerCase()} ({sc('kalman_ai', 'after')?.n ?? 0} quarters, error in points a month after each quarter): with AI {sc('kalman_ai', 'after')?.rmse.toFixed(2) ?? '—'}, without {sc('kalman', 'after')?.rmse.toFixed(2) ?? '—'}, last release {sc('benchmark', 'after')?.rmse.toFixed(2) ?? '—'}. At quarter end: {sc('kalman_ai', 'end')?.rmse.toFixed(2) ?? '—'} against {sc('kalman', 'end')?.rmse.toFixed(2) ?? '—'}. The difference comes from {qLabel(T.shock)}, the one contraction; in calm quarters the two agree.</p>
          </div>
        </article>
        <article className="card s4">
          <div className="card-head"><div><h2>Why the nowcast moved</h2><p className="sub">{wf ? `${qLabel(T.current)}, with AI: ${pct(wf.from, 2)} on ${day(wf.from_date)} → ${pct(wf.to, 2)}` : 'No change computed'}</p></div>
            <div className="segmented" role="group" aria-label="Period">
              {(['week', 'month', 'since_start'] as const).map((s) => <button key={s} type="button" aria-pressed={span === s} onClick={() => setSpan(s)}>{s === 'week' ? '1 week' : s === 'month' ? '4 weeks' : 'Quarter'}</button>)}
            </div></div>
          <ul className="bars moved ai-wf scroll">{(wf?.steps ?? []).slice(0, 9).map((s) => (
            <li key={s.input}><span>{s.label}{s.group === 'AI news' && <span className="pill tint small-pill">AI</span>}</span>
              <span className="dbar"><i className={s.change < 0 ? 'neg' : 'pos'} style={{ width: `${Math.abs(s.change) / wMax * 50}%` }} /></span>
              <span className="num">{pp(s.change)}</span></li>
          ))}{wf && !wf.steps.length && <li className="sub">No change over this period.</li>}</ul>
          <p className="note">Exact split of the revision, in percentage points: each input’s new data, plus re-estimating the model.</p>
        </article>
        <article className="card s4">
          <div className="card-head"><div><h2>AI news signal</h2><p className="sub">A diffusion index like a PMI balance: relevant UAE headlines saying activity is stronger minus those saying weaker, labelled by the LLM</p></div></div>
          <div className="fc-plot"><div className="fc-chart small" ref={sigRef}>{sigChart ? <Chart c={sigChart} height={Math.max(120, sigH - 74)} /> : <p className="note">No AI news signal yet: press Update AI news.</p>}</div></div>
        </article>
        <article className="card s4">
          <div className="card-head"><div><h2>What the AI read</h2><p className="sub">{mInfo ? `${mInfo.relevant} of ${mInfo.headlines} headlines relevant · ${mInfo.up ?? 0} stronger, ${mInfo.down ?? 0} weaker · balance ${mInfo.nonoil != null ? `${mInfo.nonoil > 0 ? '+' : ''}${mInfo.nonoil.toFixed(0)}` : '—'}` : ''}</p></div>
            <div className="head-ctl">
              <select className="popup" value={m ?? ''} onChange={(e) => setMonth(e.target.value)} aria-label="Month">{months.map((x) => <option key={x} value={x}>{monthLabel(x)}</option>)}</select>
              <label className="switch small-sw"><input type="checkbox" checked={relOnly} onChange={(e) => setRelOnly(e.target.checked)} aria-label="Relevant headlines only" /> Relevant</label>
              <button className="btn small" type="button" aria-expanded={how} onClick={() => setHow((v) => !v)}>How the AI scores</button>
            </div></div>
          {how && (
            <div className="ai-how">
              <p><b>1. Relevant or not.</b> A headline counts only if it reports something happening to UAE activity now: volumes, traffic, sales, output, lending, hiring, openings, closures, results. Conferences, plans, MoUs, opinion, consumer price tips and foreign companies that only mention the UAE do not count.</p>
              <p><b>2. Direction, −2 to +2.</b> −2 clearly weaker (closures, sharp falls, disruption) · −1 somewhat weaker · 0 mixed or unclear · +1 somewhat stronger · +2 clearly stronger (records, strong growth).</p>
              <p><b>3. Blind to dates.</b> Headlines from different months are shuffled and shown without dates or sources, so the AI judges each one on its words, not on what it knows happened later.</p>
              <p><b>4. Monthly signal.</b> Balance = 100 × (stronger − weaker) ÷ (relevant headlines + 5). The “+5” pulls months with few headlines toward zero. Oil and gas headlines form a separate signal.</p>
              <p><b>5. Checked.</b> Analysts can label a sample blind on the Governance page; Nabd reports how often the AI agrees.</p>
            </div>
          )}
          <ul className="ai-heads scroll">{heads == null ? <li className="sub">Loading…</li> : shown.map((h, i) => (
            <li key={`${h.url}-${i}`}>
              <span className={`ai-dir d${h.direction + 2}`} title={DIR[h.direction + 2]}>{h.relevant ? (h.direction > 0 ? `+${h.direction}` : h.direction) : '·'}</span>
              <div><a href={h.url} target="_blank" rel="noreferrer" dir="auto">{h.title}</a>
                {h.relevant && h.reason && <span className="ai-reason">{h.reason}</span>}
                <span className="sub">{h.relevant ? h.sector_label : 'Not relevant'} · {h.source} · {day(h.date)}</span></div>
            </li>))}{heads && !shown.length && <li className="sub">No headlines.</li>}</ul>
        </article>
      </div>
      {job && <p className="note">{job.message}</p>}
      {err && <p className="note worse">{err}</p>}
      {lab && <ForecastLab target={target} onClose={() => setLab(false)} />}
    </>
  );
}
