// Portfolio fit, stress, committee and monitoring stages.
import { useState } from 'react';
import { api } from '../../lib/api';
import { fmt, type Idea, type ScenarioRow } from '../../lib/invest';

const Run = ({ id }: { id?: string }) => (id ? <span className="run-id num" title="Model run id">run {id}</span> : null);

const LINE: Record<string, string> = { GLD: 'Gold', BNO: 'Brent crude', USO: 'WTI crude', UNG: 'Natural gas', CPER: 'Copper',
  DBB: 'Base metals', SLV: 'Silver', PPLT: 'Platinum', DBA: 'Agriculture', DBC: 'Broad commodities', GSG: 'S&P GSCI index',
  SHV: 'T-bills', TIP: 'Inflation-linked Treasuries', IEF: '7-10y Treasuries', TLT: 'Long Treasuries', SHY: '1-3y Treasuries' };
const lineName = (s: string) => LINE[s] ?? s;
// the same names as they read inside a sentence: common nouns lower case, proper nouns kept
const IN_TEXT: Record<string, string> = { GLD: 'gold', BNO: 'Brent crude', USO: 'WTI crude', UNG: 'natural gas', CPER: 'copper',
  DBB: 'base metals', SLV: 'silver', PPLT: 'platinum', DBA: 'agriculture', DBC: 'broad commodities', GSG: 'the S&P GSCI index',
  SHV: 'T-bills', TIP: 'inflation-linked Treasuries' };
const inText = (s: string) => IN_TEXT[s] ?? lineName(s);

export function FitPanel({ idea, onChange }: { idea: Idea; onChange: () => void }) {
  const f = idea.fit;
  const [busy, setBusy] = useState(false);
  const [more, setMore] = useState(false);
  if (!f) return null;
  const used = f.budget_used_pct.after, before = f.budget_used_pct.before;
  async function resize(m: number) { setBusy(true); try { await api.post(`/api/invest/ideas/${idea.id}/resize`, { multiple: m }); onChange(); } finally { setBusy(false); } }
  const top = f.contributions.filter((c) => c.contribution_pct > 0).slice(0, 4);
  const bought = top.filter((c) => c.active_pct > 0), trimmed = top.filter((c) => c.active_pct < 0);
  const maxC = Math.max(...top.map((c) => c.contribution_pct), 1);
  const slowest = f.liquidity.reduce((m, l) => Math.max(m, l.days_at_20pct_adv ?? 0), 0);
  const fits = used <= 100;
  const hypo = Object.entries(f.hypothetical ?? {});
  return (
    <section className="panel grow-panel">
      <div className="panel-head">
        <div><h3>Portfolio fit</h3><p className="sub">What this idea does to the book’s risk, against holding the benchmark</p></div>
        <div className="head-ctl">
          {f.max_multiple < 1 && <button className="btn small" type="button" disabled={busy} onClick={() => resize(Math.floor(f.max_multiple * 95) / 100)}>Scale to fit the budget (×{(Math.floor(f.max_multiple * 95) / 100).toFixed(2)})</button>}
        </div>
      </div>
      {!!hypo.length && <p className="hypo-note">Tested as if added: {hypo.map(([k, w]) => `${lineName(k)} ${w}%`).join(' · ')}. Hypothetical, not a trade.</p>}
      <div className="scroll fit-body">
        <div className="fit-q">
          <h4>Does it fit the risk budget?</h4>
          <p className={`fit-a ${fits ? '' : 'worse'}`}>{fits ? 'Yes' : 'No'}: it uses <b className="num">{used.toFixed(0)}%</b> of the Board’s budget</p>
          <div className="gauge-bar" role="img" aria-label={`${used.toFixed(0)}% of the active risk budget used`}>
            <i className="before" style={{ width: `${Math.min(before, 100)}%` }} />
            <i className={`after ${used > 100 ? 'over' : used > 80 ? 'warn' : ''}`} style={{ left: `${Math.min(before, 100)}%`, width: `${Math.max(0, Math.min(used, 100) - Math.min(before, 100))}%` }} />
            <span className="tick" style={{ left: '100%' }} />
          </div>
          <p className="sub">The budget is how far the book may drift from its benchmark in a year ({f.budget_bp} bp of tracking error); this idea takes {f.te_bp.after.toFixed(0)} bp{before ? `, on top of ${f.te_bp.before.toFixed(0)} bp already used` : ''}. {fits ? `It could grow to ${f.max_total_pct.toFixed(1)}% of the book before the budget is full.` : 'Scale it down to fit.'}</p>
        </div>
        <div className="fit-q">
          <h4>What could a bad day cost?</h4>
          <p className="fit-a">About <b className="num">{fmt.usd(f.active_var95_usd_mn)}</b></p>
          <p className="sub">On one trading day in twenty, the idea could cost the book more than this compared with holding the benchmark ({f.active_var95_1d_bp.toFixed(1)} bp of the book). Worse cases are on the Stress step.</p>
        </div>
        <div className="fit-q">
          <h4>What drives its risk?</h4>
          <p className="fit-a fit-a-sm">{bought.length ? <>Mostly the {bought.map((c) => inText(c.symbol)).join(' and ')} bought</> : 'The lines it changes'}{trimmed.length ? <>, and trimming {trimmed.map((c) => inText(c.symbol)).join(' and ')} to pay for it</> : null}.</p>
          <ul className="bars">{top.map((c) => (
            <li key={c.symbol}><span>{lineName(c.symbol)} <span className="sub">{c.active_pct > 0 ? 'bought' : 'trimmed'}</span></span>
              <span className="bar"><i style={{ width: `${c.contribution_pct / maxC * 100}%` }} /></span>
              <span className="num">{c.contribution_pct.toFixed(0)}%</span></li>
          ))}</ul>
          <p className="sub">Share of the idea’s risk from each line. The purchase is paid for by trimming the book’s other commodity lines in proportion, so they appear too.</p>
        </div>
        <button className="link-btn" type="button" aria-expanded={more} onClick={() => setMore((v) => !v)}>{more ? 'Hide details' : 'Details: every line, liquidity, the risk model'}</button>
        {more && (
          <div className="two">
            <div>
              <h4>Every line’s change and share of risk</h4>
              <table><thead><tr><th>Line</th><th className="r">Change</th><th className="r">Share of risk</th></tr></thead>
                <tbody>{f.contributions.map((c) => <tr key={c.symbol}><td>{lineName(c.symbol)}</td><td className="r num">{fmt.pct(c.active_pct, 2)}</td><td className="r num">{c.contribution_pct.toFixed(0)}%</td></tr>)}</tbody></table>
              {f.corr_with_existing != null && <p className="sub">Correlation with ideas already approved: {f.corr_with_existing.toFixed(2)}.</p>}
            </div>
            <div>
              <h4>Can it be traded at this size?</h4>
              <p className="sub">{slowest ? `The slowest line takes ${slowest} days to trade at 20% of its daily volume.` : 'Every line trades in under a day.'}</p>
              <table><thead><tr><th>Line</th><th className="r">Position</th><th className="r">Traded a day</th><th className="r">Days at 20%</th></tr></thead>
                <tbody>{f.liquidity.map((l) => (
                  <tr key={l.symbol}><td>{lineName(l.symbol)}</td><td className="r num">{fmt.usd(l.position_usd_mn)}</td><td className="r num">{fmt.usd(l.adv_usd_mn)}</td>
                    <td className={`r num ${(l.days_at_20pct_adv ?? 0) > 5 ? 'warn' : ''}`}>{l.days_at_20pct_adv ?? '—'}</td></tr>
                ))}</tbody></table>
              <p className="sub">Risk model: daily prices {f.data.start} to {f.data.end} <Run id={f.run_id} /></p>
            </div>
          </div>
        )}
      </div>
    </section>
  );
}

const SHOCK_NAME: Record<string, string> = { 'Hormuz closure, 30 days': 'Strait of Hormuz closed for 30 days', 'Oil collapse': 'Oil price collapses',
  'Rates +100 bp': 'Interest rates up 1 percentage point', 'Risk-off, dollar up': 'Markets sell off and the dollar rises' };

function MoneyRows({ rows, usdPerBp }: { rows: ScenarioRow[]; usdPerBp: number }) {
  const m = Math.max(...rows.map((r) => Math.abs(r.active_bp)), 1);
  return (
    <ul className="st-rows">{rows.map((r) => (
      <li key={r.name}>
        <span className="st-name">{SHOCK_NAME[r.name] ?? r.name}{r.start && <span className="sub"> {new Date(r.start).toLocaleDateString('en-GB', { month: 'short', year: 'numeric' })}</span>}</span>
        <span className="dbar"><i className={r.active_bp < 0 ? 'neg' : 'pos'} style={{ width: `${Math.abs(r.active_bp) / m * 50}%` }} /></span>
        <span className="st-val num">{r.active_bp < 0 ? 'loses ' : 'gains '}{fmt.usd(Math.abs(r.active_bp * usdPerBp))}<span className="sub"> {fmt.bp(r.active_bp)}</span></span>
      </li>))}</ul>
  );
}

export function StressPanel({ idea }: { idea: Idea }) {
  const s = idea.stress;
  if (!s) return null;
  const mc = s.monte_carlo, p = mc.active_bp_percentiles;
  const usdPerBp = (idea.fit?.notional_usd_bn ?? 25) / 10;  // 1 bp of the book in USD mn
  const usd = (bp: number) => fmt.usd(Math.abs(bp * usdPerBp));
  const hypo = Object.entries(s.hypothetical ?? {});
  const lo = Math.min(p.p5, 0), hi = Math.max(p.p95, 0), span = Math.max(hi - lo, 1e-6);
  const at = (v: number) => `${((v - lo) / span) * 100}%`;
  return (
    <section className="panel grow-panel">
      <div className="panel-head"><div><h3>Stress and scenarios</h3><p className="sub">What the idea gains or loses against the benchmark when markets turn</p></div></div>
      {!!hypo.length && <p className="hypo-note">Tested as if added: {hypo.map(([k, w]) => `${k} ${w}%`).join(' · ')}. Hypothetical, not a trade.</p>}
      <div className="scroll stress-body">
        <div className="fit-q">
          <h4>What is the worst case?</h4>
          <p className="fit-a">{s.worst.active_bp < 0 ? 'Loses' : 'Gains'} about <b className="num">{usd(s.worst.active_bp)}</b> {s.replays.some((r) => r.name === s.worst.name) ? `if the ${s.worst.name} repeated` : `if ${(SHOCK_NAME[s.worst.name] ?? s.worst.name).replace(/^./, (c) => c.toLowerCase()).replace(/^strait/, 'the Strait').replace(/^oil/, 'the oil').replace(/^interest/, 'interest')}`}</p>
          <p className="sub">That is {Math.abs(s.worst.active_bp).toFixed(0)} bp of the book, against simply holding the benchmark. <Run id={s.run_id} /></p>
        </div>
        <div className="fit-q">
          <h4>How would it have done in past crises?</h4>
          <MoneyRows rows={s.replays} usdPerBp={usdPerBp} />
          <p className="sub">Each holding is moved by what it actually did in the episode.</p>
        </div>
        <div className="fit-q">
          <h4>What if…?</h4>
          <MoneyRows rows={s.shocks} usdPerBp={usdPerBp} />
          <p className="sub">Each line is moved by its measured sensitivity to oil, rates, the dollar and market stress.</p>
        </div>
        <div className="fit-q">
          <h4>Over the next quarter?</h4>
          <p className="fit-a fit-a-sm">Typically {p.p50 < 0 ? 'loses' : 'gains'} <b className="num">{usd(p.p50)}</b>; in 9 quarters out of 10 between losing <b className="num">{usd(Math.min(p.p5, 0))}</b> and gaining <b className="num">{usd(Math.max(p.p95, 0))}</b>. It loses money in {Math.round(mc.prob_active_loss * 100)}% of them.</p>
          <div className="st-range" role="img" aria-label="Range of simulated quarterly results">
            <span className="st-band" style={{ left: at(p.p5), width: `calc(${at(p.p95)} - ${at(p.p5)})` }} />
            <span className="st-zero" style={{ left: at(0) }} /><span className="st-mid" style={{ left: at(p.p50) }} />
            <span className="st-lab" style={{ left: 0 }}>{p.p5 < 0 ? '−' : ''}{usd(p.p5)}</span>
            <span className="st-lab st-lab-r" style={{ right: 0 }}>+{usd(p.p95)}</span>
          </div>
          <p className="sub">From {mc.paths.toLocaleString('en-GB')} simulated quarters built from real {mc.horizon_days}-day stretches of history. The bar spans 9 in 10 outcomes; the dark mark is the typical result, the thin line is zero.</p>
        </div>
      </div>
    </section>
  );
}

type DeepPack = { overall?: string; confidence?: number; hypotheses?: { id: string; verdict: string; confidence: number; one_line: string }[];
  bear_case?: string; verification?: { claims: number; unsupported: number; figures_checked: number; figures_traced: number } };
const VERDICT_TONE: Record<string, string> = { supported: 'green', refuted: 'red', inconclusive: '', mixed: 'orange', positive: 'green', negative: 'red' };

/** The committee paper: what is asked, the evidence, both sides, the risk, then the decision. */
export function CommitteePanel({ idea, onChange }: { idea: Idea; onChange: () => void }) {
  const c = idea.committee;
  const [decision, setDecision] = useState('approve');
  const [conditions, setConditions] = useState('');
  const [rationale, setRationale] = useState('');
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  if (!c) return null;
  const decide = async () => {
    setBusy(true); setErr(null);
    try { await api.post(`/api/invest/ideas/${idea.id}/decision`, { decision, conditions, rationale, by: idea.thesis?.committee ?? 'MRMC' }); onChange(); }
    catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };
  const cv = c.cover;
  const deep = (c.pack as { deep_research?: DeepPack }).deep_research ?? null;
  const f = idea.fit, st = idea.stress;
  const notional = f?.notional_usd_bn ?? 25;
  const items = idea.basket?.items ?? [];
  const traded = items.filter((i) => !i.research_only && i.weight_pct);
  const studied = items.filter((i) => i.research_only);
  const total = traded.reduce((a, i) => a + i.weight_pct, 0);
  const tested = total || studied.reduce((a, i) => a + (i.test_pct ?? 1), 0);
  const usdPerBp = notional / 10;
  const worstUsd = st ? Math.abs(st.worst.active_bp * usdPerBp) : null;
  const v = deep?.verification;
  const committee = idea.thesis?.committee === 'MRMC' ? 'Market Risk Management Committee (MRMC)' : idea.thesis?.committee ?? 'Committee';
  const today = new Date().toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric' });
  return (
    <section className="panel grow-panel">
      <div className="panel-head no-print">
        <div><h3>Committee paper</h3><p className="sub">Drafted by Nabd from this idea’s own research, risk and stress results; it does not recommend a decision</p></div>
        <div className="head-ctl"><button className="btn small" type="button" onClick={() => window.print()}>Print or save as PDF</button></div>
      </div>
      <div className="scroll">
        <article className="mrmc-paper">
          <header className="mp-head">
            <p className="mp-kicker">{committee} · paper for decision · {today}</p>
            <h2>{idea.thesis?.title ?? idea.title}</h2>
            <p className="mp-ask"><span>Decision sought</span>{cv.recommendation_framing}</p>
            <p className="sub">{idea.id} · {idea.horizon === 'tactical' ? 'Tactical tilt' : 'Strategic change'} · prepared by Nabd for the {idea.owner}</p>
          </header>

          <div className="mp-facts">
            <div><span>Size</span><b className="num">{tested.toFixed(1)}% of the book</b><i className="num">about {fmt.usd(tested / 100 * notional * 1e3)}{!total && studied.length ? ' · tested size' : ''}</i></div>
            <div><span>Risk budget used</span><b className="num">{f ? `${f.budget_used_pct.after.toFixed(0)}%` : '—'}</b><i>{f ? `${f.te_bp.after.toFixed(0)} of ${f.budget_bp} bp a year` : 'fit not run'}</i></div>
            <div><span>Worst case</span><b className="num">{worstUsd != null ? `− ${fmt.usd(worstUsd)}` : '—'}</b><i>{st ? `if the ${st.worst.name} repeated` : 'stress not run'}</i></div>
            <div><span>Research verdict</span><b className={`pill ${VERDICT_TONE[deep?.overall ?? ''] ?? ''}`}>{deep?.overall ? deep.overall[0].toUpperCase() + deep.overall.slice(1) : 'No deep research'}</b><i>{deep?.confidence != null ? `${Math.round(deep.confidence * 100)}% confidence` : ''}</i></div>
          </div>

          <section className="mp-sec">
            <h3><span>1</span>The proposal</h3>
            <p>{idea.thesis?.summary}</p>
            <ul className="mp-lines">
              {traded.map((i) => <li key={i.symbol}><b className="num">{i.weight_pct > 0 ? 'Add' : 'Cut'} {Math.abs(i.weight_pct).toFixed(2)}%</b> {i.name ?? i.symbol}</li>)}
              {studied.map((i) => <li key={i.symbol}><b>Research only</b> {i.name ?? i.symbol} <span className="sub">(tested at {(i.test_pct ?? 1).toFixed(1)}%, not a trade)</span></li>)}
            </ul>
            <p className="sub">{idea.funding === 'cash' ? 'Paid for from T-bills in the liquidity sleeve.' : 'Paid for by trimming the book’s other gold and commodity lines in proportion.'}</p>
          </section>

          {deep && (
            <section className="mp-sec">
              <h3><span>2</span>What the research found</h3>
              <table className="mp-hyp"><tbody>{(deep.hypotheses ?? []).map((h) => (
                <tr key={h.id}><td className="num">{h.id}</td><td><span className={`pill ${VERDICT_TONE[h.verdict] ?? ''}`}>{h.verdict}</span></td><td>{h.one_line}</td></tr>))}</tbody></table>
              {v && <p className="sub">Checked: {v.claims - v.unsupported} of {v.claims} claims kept after verification; {v.figures_traced} of {v.figures_checked} figures traced to a source.</p>}
            </section>
          )}

          <section className="mp-sec">
            <h3><span>{deep ? 3 : 2}</span>The case for and against</h3>
            <div className="mp-two">
              <div className="mp-for"><h4>For</h4><ul>{cv.case_for.map((x) => <li key={x}>{x}</li>)}</ul></div>
              <div className="mp-against"><h4>Against</h4><ul>{cv.case_against.map((x) => <li key={x}>{x}</li>)}</ul>
                {deep?.bear_case && <p className="sub">Red team: {deep.bear_case}</p>}</div>
            </div>
          </section>

          <section className="mp-sec">
            <h3><span>{deep ? 4 : 3}</span>Risk</h3>
            <ul className="mp-risk">
              {f && <li><b>Risk budget.</b> Uses {f.budget_used_pct.after.toFixed(0)}% of the Board’s budget; it could grow to {f.max_total_pct.toFixed(1)}% of the book before the budget is full.</li>}
              {f && <li><b>A bad day.</b> On one trading day in twenty it could cost more than {fmt.usd(f.active_var95_usd_mn)} against the benchmark.</li>}
              {st && <li><b>Worst case.</b> Loses about {fmt.usd(worstUsd ?? 0)} if the {st.worst.name} repeated.</li>}
              {st && <li><b>Next quarter.</b> Loses money in {Math.round(st.monte_carlo.prob_active_loss * 100)}% of 2,000 simulated quarters.</li>}
            </ul>
            {!!cv.risk_points.length && <><h4>Points for the committee to weigh</h4><ul className="mp-plain">{cv.risk_points.map((x) => <li key={x}>{x}</li>)}</ul></>}
          </section>

          <section className="mp-sec">
            <h3><span>{deep ? 5 : 4}</span>Conditions the committee may attach</h3>
            <ul className="mp-plain">{cv.conditions_to_consider.map((x) => <li key={x}>{x}</li>)}</ul>
          </section>

          <section className="mp-sec mp-decision">
            <h3><span>{deep ? 6 : 5}</span>Decision</h3>
            {c.decision ? (
              <p className="mp-decided"><span className={`pill ${c.decision.decision === 'approve' ? 'green' : c.decision.decision === 'reject' ? 'red' : 'orange'}`}>{({ approve: 'Approved', defer: 'Deferred', reject: 'Rejected' } as Record<string, string>)[c.decision.decision] ?? c.decision.decision}</span> {c.decision.rationale}
                {c.decision.conditions && <span className="sub"> · Conditions: {c.decision.conditions}</span>}<span className="sub"> · {c.decision.by}, {fmt.date(c.decision.ts)}</span></p>
            ) : (
              <div className="mp-form no-print">
                <div className="segmented" role="group" aria-label="Decision">{['approve', 'defer', 'reject'].map((o) => <button key={o} type="button" aria-pressed={decision === o} onClick={() => setDecision(o)}>{o[0].toUpperCase() + o.slice(1)}</button>)}</div>
                <textarea rows={2} placeholder="Rationale, as minuted" value={rationale} onChange={(e) => setRationale(e.target.value)} />
                <input type="text" placeholder="Conditions (optional), e.g. cap at 1% of the book; review in 3 months" value={conditions} onChange={(e) => setConditions(e.target.value)} />
                <button className="btn filled small" type="button" disabled={busy || rationale.trim().length < 3} onClick={decide}>Record the decision</button>
                {err && <p className="note worse">{err}</p>}
              </div>
            )}
          </section>
          <p className="mp-foot">Every figure in this paper comes from Nabd’s models and recorded runs; the AI drafted the wording only. Synthetic or notional where stated.</p>
        </article>
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
