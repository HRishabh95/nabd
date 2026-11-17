import { Fragment, useCallback, useEffect, useState } from 'react';
import { PageHeader } from '../components/Chrome';
import { api } from '../lib/api';

// What the Head of AI and the CRO ask: which models exist, their status and evidence, and how the AI is checked.
type Method = { label: string; precision: number; recall: number; rings_whole: number; rings: number; shown: boolean };
type Explain = { short?: string; headline?: string; what?: string; method?: string; data?: string; test?: string; result?: string; limit?: string; methods?: Method[] };
const METHOD_LABEL: Record<string, string> = { 'Combined network': 'Both together (what the Fraud page shows)', 'Machine learning on account features': 'Machine-learning score alone',
  'Rules (per account)': 'Simple rules per account (benchmark)', 'Money-trail tracing': 'Money-trail tracing alone', 'Community detection': 'Community detection (benchmark)', 'Cycle detection': 'Cycle detection alone' };
type Model = { key: string; name: string; version: string; tier: string; purpose: string; status: string; reason: string; note?: string; metric: string | null; explain?: Explain;
  lifecycle: string; last_run: { id: string; created: number } | null; recent_runs: { id: string; created: number }[] };
type Eval = {
  research: { runs: number; claims: number; removed: number; figures: number; traced: number };
  fraud_notes: { notes: number; cited: number; matched: number };
  ask: { answers: number; figures: number; traced: number };
  labels: { n: number; relevance_agree?: number; relevance_kappa?: number; both_relevant?: number; direction_exact?: number | null; direction_within_1?: number | null; direction_same_sign?: number | null };
  feedback: { by_kind: { kind: string; label: string; up: number; down: number; n: number }[]; recent: { ts: number; kind: string; ref: string; verdict: number; comment: string; reviewer: string }[] };
};
type Item = { id: string; title: string };

const pct = (a: number, b: number) => (b ? `${Math.round((a / b) * 100)}%` : '—');
const when = (t: number) => new Date(t * 1000).toLocaleString('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
const STATUS: Record<string, string> = { ok: 'green', watch: 'orange', breach: 'red', inactive: '' };
const STATUS_LABEL: Record<string, string> = { ok: 'Within its limits', watch: 'Needs review', breach: 'Outside its limits', inactive: 'Not in use' };
const ROWS: [keyof Explain, string][] = [['what', 'What it does'], ['method', 'How it works'], ['data', 'Data'], ['test', 'How it was tested'], ['result', 'What the test found'], ['limit', 'What it cannot show']];
const DIRS = [-2, -1, 0, 1, 2];

export default function Governance() {
  const [tab, setTab] = useState<'models' | 'ai'>('models');
  const [models, setModels] = useState<Model[] | null>(null);
  const [ev, setEv] = useState<Eval | null>(null);
  const [items, setItems] = useState<Item[] | null>(null);
  const [answers, setAnswers] = useState<Record<string, number | 'no'>>({});
  const [err, setErr] = useState<string | null>(null);
  const [openRow, setOpenRow] = useState<string | null>(null);

  const loadEval = useCallback(() => api.get<Eval>('/api/governance/evaluation').then(setEv, (e) => setErr(e.message)), []);
  useEffect(() => { api.get<{ models: Model[] }>('/api/monitor/models').then((r) => setModels(r.models), (e) => setErr(e.message)); loadEval(); }, [loadEval]);

  async function startLabelling() { setAnswers({}); setItems((await api.get<{ items: Item[] }>('/api/governance/labels/sample?n=10')).items); }
  async function submitLabels() {
    const body = Object.entries(answers).map(([id, a]) => ({ id, relevant: a !== 'no', direction: a === 'no' ? null : a }));
    await api.post('/api/governance/labels', body);
    setItems(null); loadEval();
  }

  const L = ev?.labels;
  return (
    <>
      <PageHeader title="Governance" lede="Every model, its status and evidence, and how the AI's work is checked · proof of concept, not yet independently validated"
        actions={<div className="segmented" role="group" aria-label="View">
          <button type="button" aria-pressed={tab === 'models'} onClick={() => setTab('models')}>Models</button>
          <button type="button" aria-pressed={tab === 'ai'} onClick={() => setTab('ai')}>AI evaluation</button></div>} />
      {err && <p className="note worse">{err}</p>}

      {tab === 'models' && (
        <div className="fill gv-scroll">
          <article className="card">
            <div className="card-head"><div><h2>Models in use</h2><p className="sub">Click a model to see its data, how it was tested and what it cannot show. None is independently validated yet; each has a pack ready for that review.</p></div></div>
            <div className="table-wrap"><table className="lb gv-table"><thead><tr><th>Model</th><th>What it does</th><th>What the test found</th><th>Status</th><th aria-label="More" /></tr></thead>
              <tbody>{(models ?? []).map((m) => {
                const on = openRow === m.key;
                return (<Fragment key={m.key}>
                  <tr className={`gv-row ${on ? 'on' : ''}`} onClick={() => setOpenRow(on ? null : m.key)} tabIndex={0} aria-expanded={on}
                    onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setOpenRow(on ? null : m.key); } }}>
                    <td><b>{m.name}</b></td>
                    <td>{m.explain?.short ?? m.purpose}</td>
                    <td>{m.explain?.headline ?? m.metric ?? '—'}</td>
                    <td><span className={`pill ${STATUS[m.status] ?? ''}`}>{STATUS_LABEL[m.status] ?? m.status}</span></td>
                    <td className="gv-chev" aria-hidden>{on ? '▾' : '▸'}</td>
                  </tr>
                  {on && (
                    <tr className="gv-more"><td colSpan={5}>
                      <dl className="gv-explain">{ROWS.filter(([k]) => m.explain?.[k]).map(([k, label]) => (
                        <div key={k}><dt>{label}</dt><dd>{m.explain![k] as string}</dd></div>))}</dl>
                      {!!m.explain?.methods?.length && (
                        <div className="gv-methods">
                          <h4>Every method tried, on the same labelled data</h4>
                          <table className="lb"><thead><tr><th>Method</th><th className="r">Flagged accounts that are real launderers</th><th className="r">Launderers found</th><th className="r">Rings found whole</th></tr></thead>
                            <tbody>{m.explain.methods.map((x) => (
                              <tr key={x.label} className={x.label === 'Combined network' ? 'on' : ''}><td>{METHOD_LABEL[x.label] ?? x.label}</td>
                                <td className="r num">{Math.round(x.precision * 100)}%</td><td className="r num">{Math.round(x.recall * 100)}%</td><td className="r num">{x.rings_whole} of {x.rings}</td></tr>))}</tbody></table>
                          <p className="sub">Requiring both methods to agree gives the fewest false alarms; following the money alone finds a few more launderers but flags more innocent accounts.</p>
                        </div>
                      )}
                      <div className="gv-card-foot"><span className="sub">{m.tier} materiality · last run {m.last_run ? when(m.last_run.created) : '—'} · {m.recent_runs.length} runs recorded · validation pending</span>
                        <a className="btn small" href={`/api/governance/pack/${m.key}`} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}>Open the validation pack</a></div>
                    </td></tr>
                  )}
                </Fragment>);
              })}</tbody></table></div>
          </article>
        </div>
      )}

      {tab === 'ai' && ev && (
        <div className="fill gv-scroll">
          <dl className="metrics gv-kpis">
            <div className="metric"><dt>Research claims verified</dt><dd className="num">{pct(ev.research.claims - ev.research.removed, ev.research.claims)}</dd>
              <span className="num">{ev.research.removed} of {ev.research.claims} claims removed as unsupported · {ev.research.traced} of {ev.research.figures} figures traced · {ev.research.runs} runs</span></div>
            <div className="metric"><dt>Fraud notes: cited transfers that exist</dt><dd className="num">{pct(ev.fraud_notes.matched, ev.fraud_notes.cited)}</dd>
              <span className="num">{ev.fraud_notes.matched} of {ev.fraud_notes.cited} across {ev.fraud_notes.notes} notes · the rest are removed before display</span></div>
            <div className="metric"><dt>Ask Nabd: figures traced to evidence</dt><dd className="num">{pct(ev.ask.traced, ev.ask.figures)}</dd>
              <span className="num">{ev.ask.traced} of {ev.ask.figures} figures in {ev.ask.answers} answers · untraced ones are flagged on the answer</span></div>
            <div className="metric"><dt>News labels: agreement with analysts</dt><dd className="num">{L?.n ? pct(Math.round((L.relevance_agree ?? 0) * L.n), L.n) : 'Not measured'}</dd>
              <span className="num">{L?.n ? `${L.n} headlines labelled by people · relevance κ ${L.relevance_kappa?.toFixed(2)} · direction within ±1: ${L.direction_within_1 != null ? Math.round(L.direction_within_1 * 100) + '%' : '—'}` : 'Label a sample below to measure it'}</span></div>
          </dl>
          <div className="grid gv-grid">
            <article className="card s6">
              <div className="card-head"><div><h2>Measure the news labels</h2><p className="sub">You label headlines without seeing the AI’s label; Nabd compares. Ten take about two minutes.</p></div>
                {!items && <button className="btn filled small" type="button" onClick={startLabelling}>Label 10 headlines</button>}</div>
              {items && (
                <>
                  <ul className="gv-label">{items.map((it) => (
                    <li key={it.id}><p dir="auto">{it.title}</p>
                      <div className="gv-opts" role="group" aria-label={`Label: ${it.title}`}>
                        <button type="button" aria-pressed={answers[it.id] === 'no'} onClick={() => setAnswers((a) => ({ ...a, [it.id]: 'no' }))}>Not about UAE activity</button>
                        {DIRS.map((d) => <button key={d} type="button" aria-pressed={answers[it.id] === d} onClick={() => setAnswers((a) => ({ ...a, [it.id]: d }))}
                          title={['Clearly weaker', 'Weaker', 'Neutral', 'Stronger', 'Clearly stronger'][d + 2]}>{d > 0 ? `+${d}` : d}</button>)}
                      </div></li>))}</ul>
                  <div className="lab-actions"><button className="btn filled small" type="button" disabled={!Object.keys(answers).length} onClick={submitLabels}>Compare with the AI ({Object.keys(answers).length} labelled)</button>
                    <button className="btn small" type="button" onClick={() => setItems(null)}>Cancel</button></div>
                  <p className="note">Direction: what the headline implies for UAE activity now, −2 clearly weaker to +2 clearly stronger.</p>
                </>
              )}
              {!items && L?.n ? <p className="note">So far: relevance agreement {pct(Math.round((L.relevance_agree ?? 0) * L.n), L.n)} (κ {L.relevance_kappa?.toFixed(2)}, where 0 is chance and 1 is perfect); where both said relevant ({L.both_relevant}), same direction sign {L.direction_same_sign != null ? Math.round(L.direction_same_sign * 100) + '%' : '—'}, exact {L.direction_exact != null ? Math.round(L.direction_exact * 100) + '%' : '—'}.</p> : null}
            </article>
            <article className="card s6">
              <div className="card-head"><div><h2>Human review</h2><p className="sub">Every AI output has 👍 / 👎 with a reason; each review is logged with who and when</p></div></div>
              {ev.feedback.by_kind.length ? (
                <table className="lb"><thead><tr><th>Output</th><th className="r">👍</th><th className="r">👎</th><th className="r">Approval</th></tr></thead>
                  <tbody>{ev.feedback.by_kind.map((k) => <tr key={k.kind}><td>{k.label}</td><td className="r num">{k.up}</td><td className="r num">{k.down}</td><td className="r num">{pct(k.up, k.n)}</td></tr>)}</tbody></table>
              ) : <p className="note">No reviews yet: use 👍 / 👎 under any research report, fraud note or Ask Nabd answer.</p>}
              {!!ev.feedback.recent.length && <ul className="gv-recent">{ev.feedback.recent.map((r, i) => (
                <li key={i}><span>{r.verdict > 0 ? '👍' : '👎'}</span><span>{r.comment || <i className="sub">no comment</i>}</span><span className="sub num">{r.reviewer} · {when(r.ts)}</span></li>))}</ul>}
            </article>
          </div>
          <p className="note gv-how">How each check works: research claims are verified against the evidence by a separate step and unsupported ones removed; every figure in research and Ask Nabd answers is matched to the tool result it cites; every transfer a fraud note cites is matched to the payment data, and the AI never sees the synthetic labels.</p>
        </div>
      )}
    </>
  );
}
