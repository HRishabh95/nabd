// Portfolio fit, stress, committee and monitoring stages.
import { useState } from 'react';
import { api } from '../../lib/api';
import { fmt, type ExitPlan, type Idea, type ScenarioRow } from '../../lib/invest';

const Run = ({ id }: { id?: string }) => (id ? <span className="run-id num" title="Model run id">run {id}</span> : null);

export function FitPanel({ idea, onChange }: { idea: Idea; onChange: () => void }) {
  const f = idea.fit;
  const [busy, setBusy] = useState(false);
  if (!f) return null;
  const used = f.budget_used_pct.after, before = f.budget_used_pct.before;
  async function resize(m: number) { setBusy(true); try { await api.post(`/api/invest/ideas/${idea.id}/resize`, { multiple: m }); onChange(); } finally { setBusy(false); } }
  const maxC = Math.max(...f.contributions.map((c) => Math.abs(c.contribution_pct)), 1);
  return (
    <section className="panel grow-panel">
      <div className="panel-head">
        <div><h3>Portfolio fit</h3><p className="sub">The tilt on top of the SAA benchmark{f.corr_with_existing != null ? ' and the ideas already approved' : ''}; risk model on {f.data.start} to {f.data.end} <Run id={f.run_id} /></p></div>
        <div className="head-ctl">
          {f.max_multiple < 1 && <button className="btn small" type="button" disabled={busy} onClick={() => resize(Math.floor(f.max_multiple * 95) / 100)}>Scale to fit the budget (×{(Math.floor(f.max_multiple * 95) / 100).toFixed(2)})</button>}
        </div>
      </div>
      <div className="scroll fit-body">
        <div className="gauge">
          <div className="gauge-row"><span>Tracking error against the SAA</span><strong className="num">{f.te_bp.after.toFixed(1)} bp</strong><span className="sub num">budget {f.budget_bp} bp a year</span></div>
          <div className="gauge-bar" role="img" aria-label={`${used}% of the active risk budget used`}>
            <i className="before" style={{ width: `${Math.min(before, 100)}%` }} />
            <i className={`after ${used > 100 ? 'over' : used > 80 ? 'warn' : ''}`} style={{ left: `${Math.min(before, 100)}%`, width: `${Math.max(0, Math.min(used, 100) - Math.min(before, 100))}%` }} />
            <span className="tick" style={{ left: '100%' }} />
          </div>
          <p className="sub num">{used.toFixed(1)}% of the Board’s active risk budget after this idea{before ? `, ${before.toFixed(1)}% before` : ''}. Largest size that fits: {f.max_total_pct.toFixed(2)}% of the portfolio (×{f.max_multiple.toFixed(2)} the proposal).</p>
        </div>
        <dl className="kv">
          <div><dt>Idea’s own tracking error</dt><dd className="num">{f.te_bp.idea.toFixed(1)} bp</dd></div>
          <div><dt>Active VaR, 95%, 1 day</dt><dd className="num">{f.active_var95_1d_bp.toFixed(1)} bp · {fmt.usd(f.active_var95_usd_mn)}</dd></div>
          <div><dt>Correlation with approved ideas</dt><dd className="num">{f.corr_with_existing == null ? 'None approved yet' : f.corr_with_existing.toFixed(2)}</dd></div>
          <div><dt>Portfolio VaR, 99%, 1 day</dt><dd className="num">{f.total_var99_1d_pct.toFixed(2)}% · backtest {f.var_backtest.exceptions_250d} exceptions in 250 days (limit {f.var_backtest.limit})</dd></div>
        </dl>
        <div className="two">
          <div>
            <h4>Where the tracking error comes from</h4>
            <ul className="bars">{f.contributions.slice(0, 8).map((c) => (
              <li key={c.symbol}><span className="num"><strong>{c.symbol}</strong> {fmt.pct(c.active_pct, 2)}</span>
                <span className="bar"><i className={c.contribution_pct < 0 ? 'neg' : ''} style={{ width: `${Math.abs(c.contribution_pct) / maxC * 100}%` }} /></span>
                <span className="num">{c.contribution_pct.toFixed(0)}%</span></li>
            ))}</ul>
          </div>
          <div>
            <h4>Liquidity at central-bank size</h4>
            <table><thead><tr><th>Line</th><th className="r">Position</th><th className="r">Traded/day</th><th className="r">Days at 20%</th></tr></thead>
              <tbody>{f.liquidity.map((l) => (
                <tr key={l.symbol}><td><strong>{l.symbol}</strong></td><td className="r num">{fmt.usd(l.position_usd_mn)}</td><td className="r num">{fmt.usd(l.adv_usd_mn)}</td>
                  <td className={`r num ${(l.days_at_20pct_adv ?? 0) > 5 ? 'warn' : ''}`}>{l.days_at_20pct_adv ?? '—'}</td></tr>
              ))}</tbody></table>
            {!!f.non_sri_lines.length && <p className="note warn">Not SRI-screened: {f.non_sri_lines.join(', ')}. New passive mandates are often benchmarked to SRI-screened indices.</p>}
          </div>
        </div>
      </div>
    </section>
  );
}

function ScenarioTable({ rows, label }: { rows: ScenarioRow[]; label: string }) {
  const m = Math.max(...rows.map((r) => Math.abs(r.active_bp)), 1);
  return (
    <table className="scen"><thead><tr><th>{label}</th><th className="r">Idea, active</th><th style={{ width: '28%' }} /><th className="r">USD</th><th className="r">Whole portfolio</th></tr></thead>
      <tbody>{rows.map((r) => (
        <tr key={r.name} title={r.start ? `${r.start} to ${r.end}${r.proxied?.length ? ` · proxied: ${r.proxied.join(', ')}` : ''}` : Object.entries(r.moves ?? {}).map(([k, v]) => `${k} ${v}`).join(', ')}>
          <td>{r.name}{r.start && <span className="sub"> {r.start.slice(0, 7)}</span>}</td>
          <td className={`r num ${r.active_bp < 0 ? 'worse' : 'better'}`}>{fmt.bp(r.active_bp)}</td>
          <td><span className="dbar"><i className={r.active_bp < 0 ? 'neg' : 'pos'} style={{ width: `${Math.abs(r.active_bp) / m * 50}%` }} /></span></td>
          <td className="r num">{fmt.usd(r.active_usd_mn)}</td>
          <td className={`r num ${r.portfolio_pct < 0 ? 'worse' : ''}`}>{fmt.pct(r.portfolio_pct, 2)}</td>
        </tr>
      ))}</tbody></table>
  );
}

function Histogram({ edges, counts }: { edges: number[]; counts: number[] }) {
  const W = 420, H = 120, max = Math.max(...counts, 1), lo = edges[0], hi = edges[edges.length - 1];
  const x = (v: number) => ((v - lo) / (hi - lo)) * W;
  return (
    <svg className="hist" viewBox={`0 0 ${W} ${H + 18}`} role="img" aria-label="Distribution of simulated 3-month active returns">
      {counts.map((c, i) => (
        <rect key={i} x={x(edges[i]) + 0.5} y={H - (c / max) * H} width={Math.max(1, x(edges[i + 1]) - x(edges[i]) - 1)} height={(c / max) * H}
          className={edges[i + 1] <= 0 ? 'neg' : 'pos'} />
      ))}
      {lo < 0 && hi > 0 && <line x1={x(0)} x2={x(0)} y1={0} y2={H} className="zero" />}
      <text x={0} y={H + 14}>{lo.toFixed(0)} bp</text><text x={W} y={H + 14} textAnchor="end">{hi.toFixed(0)} bp</text>
      {lo < 0 && hi > 0 && <text x={x(0)} y={H + 14} textAnchor="middle">0</text>}
    </svg>
  );
}

export function StressPanel({ idea }: { idea: Idea }) {
  const s = idea.stress;
  if (!s) return null;
  const mc = s.monte_carlo, p = mc.active_bp_percentiles;
  return (
    <section className="panel grow-panel">
      <div className="panel-head"><div><h3>Stress and scenarios</h3><p className="sub">Worst case for the idea: {s.worst.name}, {fmt.bp(s.worst.active_bp)} ({fmt.usd(s.worst.active_usd_mn)}) <Run id={s.run_id} /></p></div></div>
      <div className="scroll stress-body">
        <div><h4>Replays of what actually happened</h4><ScenarioTable rows={s.replays} label="Episode" /></div>
        <div><h4>Factor shocks through each line’s macro betas</h4><ScenarioTable rows={s.shocks} label="Shock" /></div>
        <div className="mc">
          <h4>{mc.paths.toLocaleString('en-GB')} simulated quarters (block bootstrap, {mc.horizon_days} trading days)</h4>
          <Histogram edges={mc.histogram.edges_bp} counts={mc.histogram.counts} />
          <p className="sub num">Median {fmt.bp(p.p50)} · 5th percentile {fmt.bp(p.p5)} · 95th {fmt.bp(p.p95)} · chance of an active loss {Math.round(mc.prob_active_loss * 100)}% · expected shortfall at 95% {mc.active_es95_bp.toFixed(1)} bp</p>
        </div>
      </div>
    </section>
  );
}

export function CommitteePanel({ idea, onChange }: { idea: Idea; onChange: () => void }) {
  const c = idea.committee;
  const [plan, setPlan] = useState<ExitPlan | null>(idea.exit_plan);
  const [opinion, setOpinion] = useState('no objection');
  const [comment, setComment] = useState('');
  const [decision, setDecision] = useState('approve');
  const [conditions, setConditions] = useState('');
  const [rationale, setRationale] = useState('');
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  if (!c) return null;
  const act = async (fn: () => Promise<unknown>) => { setBusy(true); setErr(null); try { await fn(); onChange(); } catch (e) { setErr((e as Error).message); } finally { setBusy(false); } };
  const savePlan = () => act(() => api.post(`/api/invest/ideas/${idea.id}/exit-plan`, plan));
  const signoff = () => act(() => api.post(`/api/invest/ideas/${idea.id}/risk-signoff`, { opinion, comment, by: 'Risk Management' }));
  const decide = () => act(() => api.post(`/api/invest/ideas/${idea.id}/decision`, { decision, conditions, rationale, by: 'MRMC' }));
  const cv = c.cover;
  return (
    <section className="panel grow-panel">
      <div className="panel-head"><div><h3>Committee pack · {idea.thesis?.committee}</h3><p className="sub">Drafted by Nabd from the pack’s own figures; it does not recommend a decision</p></div></div>
      <div className="committee-body">
        <div className="scroll">
          <p className="lead">{cv.recommendation_framing}</p>
          <div className="two">
            <div><h4>Case for</h4><ul className="bul">{cv.case_for.map((x) => <li key={x}>{x}</li>)}</ul></div>
            <div><h4>Case against</h4><ul className="bul">{cv.case_against.map((x) => <li key={x}>{x}</li>)}</ul></div>
          </div>
          <h4>For the Risk function</h4><ul className="bul">{cv.risk_points.map((x) => <li key={x}>{x}</li>)}</ul>
          <h4>Conditions the committee may attach</h4><ul className="bul">{cv.conditions_to_consider.map((x) => <li key={x}>{x}</li>)}</ul>
        </div>
        <div className="scroll forms">
          {plan && (
            <fieldset><legend>Exit plan</legend>
              <div className="form-row"><label>Target<input type="number" value={plan.target_active_bp} onChange={(e) => setPlan({ ...plan, target_active_bp: Number(e.target.value) })} /> bp</label>
                <label>Stop<input type="number" value={plan.stop_active_bp} onChange={(e) => setPlan({ ...plan, stop_active_bp: Number(e.target.value) })} /> bp</label>
                <label>Review by<input type="date" value={plan.review_by} onChange={(e) => setPlan({ ...plan, review_by: e.target.value })} /></label></div>
              <ul className="bul small">{plan.invalidation.map((t) => <li key={t.label}>{t.label} <span className="watch">{t.series} {t.op} {t.value}</span></li>)}</ul>
              <button className="btn small" type="button" disabled={busy || !!c.decision} onClick={savePlan}>Save exit plan</button>
            </fieldset>
          )}
          <fieldset disabled={!!c.decision}><legend>Risk sign-off (second line)</legend>
            {c.risk_signoff ? <p><span className={`pill ${c.risk_signoff.opinion === 'objection' ? 'red' : c.risk_signoff.opinion === 'conditional' ? 'orange' : 'green'}`}>{c.risk_signoff.opinion}</span> {c.risk_signoff.comment} <span className="sub">· {c.risk_signoff.by}, {fmt.date(c.risk_signoff.ts)}</span></p> : (
              <>
                <div className="segmented" role="group" aria-label="Risk opinion">{['no objection', 'conditional', 'objection'].map((o) => <button key={o} type="button" aria-pressed={opinion === o} onClick={() => setOpinion(o)}>{o[0].toUpperCase() + o.slice(1)}</button>)}</div>
                <textarea rows={2} placeholder="Comment" value={comment} onChange={(e) => setComment(e.target.value)} />
                <button className="btn small" type="button" disabled={busy} onClick={signoff}>Record sign-off</button>
              </>
            )}
          </fieldset>
          <fieldset disabled={!c.risk_signoff || !!c.decision}><legend>Decision</legend>
            {c.decision ? <p><span className={`pill ${c.decision.decision === 'approve' ? 'green' : c.decision.decision === 'reject' ? 'red' : 'orange'}`}>{c.decision.decision}</span> {c.decision.rationale} {c.decision.conditions && <span className="sub">Conditions: {c.decision.conditions}</span>}</p> : (
              <>
                <div className="segmented" role="group" aria-label="Decision">{['approve', 'defer', 'reject'].map((o) => <button key={o} type="button" aria-pressed={decision === o} onClick={() => setDecision(o)}>{o[0].toUpperCase() + o.slice(1)}</button>)}</div>
                <textarea rows={2} placeholder="Rationale" value={rationale} onChange={(e) => setRationale(e.target.value)} />
                <input type="text" placeholder="Conditions (optional)" value={conditions} onChange={(e) => setConditions(e.target.value)} />
                <button className="btn filled small" type="button" disabled={busy || !c.risk_signoff} onClick={decide}>Record decision</button>
                {!c.risk_signoff && <p className="sub">Needs the Risk sign-off first.</p>}
              </>
            )}
          </fieldset>
          {err && <p className="note worse">{err}</p>}
        </div>
      </div>
    </section>
  );
}

function Spark({ values }: { values: number[] }) {
  if (values.length < 2) return null;
  const W = 220, H = 40, lo = Math.min(...values, 0), hi = Math.max(...values, 100);
  const pts = values.map((v, i) => `${(i / (values.length - 1)) * W},${H - ((v - lo) / (hi - lo || 1)) * H}`).join(' ');
  return <svg className="spark" viewBox={`0 0 ${W} ${H}`} aria-hidden="true"><polyline points={pts} /></svg>;
}

export function MonitorPanel({ idea, onChange }: { idea: Idea; onChange: () => void }) {
  const p = idea.position;
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  if (!p) return null;
  const h = p.health;
  const tone = (s: string) => ({ ok: 'green', target: 'green', watch: 'orange', breach: 'red', unknown: '' }[s] ?? '');
  const label = (s: string) => ({ ok: 'OK', target: 'Target', watch: 'Watch', breach: 'Breach', unknown: 'No data' }[s] ?? s);
  async function close() { setBusy(true); try { await api.post(`/api/invest/ideas/${idea.id}/close`, { reason }); onChange(); } finally { setBusy(false); } }
  if (p.closed) {
    return (
      <section className="panel"><div className="panel-head"><h3>Closed</h3></div>
        <p>{p.closed.reason}</p><h4>Outcome</h4><p>{p.closed.lesson.outcome}</p><h4>Lesson kept in Nabd’s memory</h4><p className="lead">{p.closed.lesson.lesson}</p></section>
    );
  }
  return (
    <section className="panel grow-panel">
      <div className="panel-head">
        <div><h3>Monitoring since {p.entry_date}</h3><p className="sub">Checked after every data refresh; a breach raises an alert on every open page</p></div>
        <div className="head-ctl"><button className="btn small" type="button" onClick={() => api.post('/api/invest/monitor/run').then(onChange)}>Check now</button></div>
      </div>
      <div className="monitor-body">
        <div className="health">
          <span className={`big num ${h && h.score < 60 ? 'worse' : h && h.score < 85 ? 'warn' : 'better'}`}>{h?.score ?? '—'}</span>
          <span className="sub">thesis health</span>
          <Spark values={p.history.map((x) => x.score)} />
          <span className="mid num">{fmt.bp(h?.active_bp)}</span><span className="sub">active return since entry</span>
        </div>
        <ul className="list scroll hchecks">
          {(h?.checks ?? []).map((c) => (
            <li key={c.name}><span className="t">{c.name}</span><span className="d num">{c.value} · {c.limit}</span><span className="v"><span className={`pill ${tone(c.status)}`}>{label(c.status)}</span></span></li>
          ))}
        </ul>
      </div>
      <div className="close-row"><input type="text" placeholder="Reason to close (target reached, thesis broken, time stop…)" value={reason} onChange={(e) => setReason(e.target.value)} />
        <button className="btn small" type="button" disabled={busy || reason.length < 3} onClick={close}>Close and write the lesson</button></div>
    </section>
  );
}
