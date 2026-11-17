import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { PageHeader } from '../components/Chrome';
import CaseFlow, { ROLE, aed as aedK, eventKey, type Flow } from '../components/CaseFlow';
import ForceNetwork from '../components/ForceNetwork';
import type { NEdge, NNode } from '../components/NetworkCanvas';
import { api } from '../lib/api';
import { useEvent } from '../lib/stream';

type Eval = { flagged: number; precision: number; recall: number; f1: number; cases: number; rings: number; rings_whole: number; rings_fragmented: number; rings_missed: number; false_alarms: number; by_typology: Record<string, { caught: number; rings: number }> };
type Case = { id: string; size: number; members: string[]; banks: number; bank_list: string[]; flow_aed: number; transfers: number; pass_through_share: number; median_hold_min: number | null; first: string | null; last: string | null; score: number; truth: { laundering_accounts: number; ring: string | null; typology: string | null } };
type Method = { label: string; eval: Eval; cases: Case[]; total_cases: number };
type Run = { created: number; run_id: string; seconds: number; params: { hold_min: number; flow_min: number; min_amount: number };
  methods: Record<string, Method>; layout: { nodes: NNode[]; edges: NEdge[] };
  data: { accounts: number; transfers: number; banks: string[]; days: number; start: string; laundering_accounts: number; rings: number; source: string };
  card: { limits: string } };
type Detail = Case & { members_detail: { account: string; bank: string; kind: string; opened_days_ago: number; in_aed: number; out_aed: number; truth: { label: number; typology: string; ring: string } }[];
  timeline: { ts: string; src: string; dst: string; amount: number; cross_bank: number }[]; money_in_aed: number; money_out_aed: number; sources_outside: number; exits_outside: number; flow: Flow };

const ORDER = ['rules', 'trail', 'community', 'cycles', 'ml', 'combined'];
const SHORT: Record<string, string> = { rules: 'Rules', trail: 'Money trail', community: 'Communities', cycles: 'Cycles', ml: 'ML', combined: 'Combined' };
const TYPO: Record<string, string> = { fan_in: 'Fan-in', fan_out: 'Fan-out', cycle: 'Cycle', scatter_gather: 'Scatter-gather', gather_scatter: 'Gather-scatter', layering: 'Layering', mule_ring: 'Mule ring' };
const aed = (v: number) => (v >= 1e6 ? `AED ${(v / 1e6).toFixed(2)} m` : `AED ${(v / 1e3).toFixed(0)} k`);
const time = (s: string) => new Date(s).toLocaleString('en-GB', { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });

export default function Fraud() {
  const [run, setRun] = useState<Run | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [method, setMethod] = useState('combined');
  const [caseId, setCaseId] = useState<string | null>(null);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [truth, setTruth] = useState(false);
  const [settings, setSettings] = useState(false);
  const [hold, setHold] = useState(240);
  const [flow, setFlow] = useState(0.7);
  const [job, setJob] = useState<{ progress: number; message: string } | null>(null);
  const [view, setView] = useState<'flow' | 'network'>('flow');
  const [colourBy, setColourBy] = useState<'flag' | 'bank'>('flag');
  const [picked, setPicked] = useState<string | null>(null);
  const [step, setStep] = useState(0);
  const [active, setActive] = useState<string | null>(null);

  const load = useCallback(() => api.get<Run>('/api/fraud').then((r) => { setRun(r); setErr(null); setHold(r.params.hold_min); setFlow(r.params.flow_min); }, (e) => setErr(e.message)), []);
  useEffect(() => { load(); }, [load]);
  useEvent('job.progress', (e) => { if (e.data.kind === 'fraud') setJob({ progress: Number(e.data.progress), message: String(e.data.message) }); });
  useEvent('job.done', (e) => { if (e.data.kind === 'fraud') { setJob(null); setCaseId(null); load(); } });
  useEvent('job.failed', (e) => { if (e.data.kind === 'fraud') { setJob(null); setErr(String(e.data.error)); } });
  useEffect(() => {
    setDetail(null);
    if (caseId) api.get<Detail>(`/api/fraud/case/${method}/${caseId}`).then((d) => { setDetail(d); setStep(d.flow?.events.length ?? 0); }).catch(() => undefined);
  }, [caseId, method]);
  // open the strongest case of the chosen method, so the page starts with a story rather than the whole network
  useEffect(() => { if (run && !caseId && view === 'flow') { const top = run.methods[method]?.cases[0]; if (top) setCaseId(top.id); } }, [run, method]); // eslint-disable-line react-hooks/exhaustive-deps
  const playRow = useRef<HTMLLIElement | null>(null);
  useEffect(() => { playRow.current?.scrollIntoView({ block: 'nearest' }); }, [step]);

  const M = run?.methods[method];
  const flagged = useMemo(() => new Set((M?.cases ?? []).flatMap((c) => c.members)), [M]);
  const selected = useMemo(() => new Set(M?.cases.find((c) => c.id === caseId)?.members ?? []), [M, caseId]);
  const caseOf = useMemo(() => new Map((M?.cases ?? []).flatMap((c) => c.members.map((a) => [a, c.id] as [string, string]))), [M]);
  async function rerun() { setJob({ progress: 0, message: 'Starting' }); try { await api.post('/api/fraud/run', { hold_min: hold, flow_min: flow, min_amount: 5000 }); } catch (e) { setErr((e as Error).message); setJob(null); } }

  if (!run || !M) {
    return (<><PageHeader title="Fraud network" lede="Mule and laundering networks found by following the money" />
      <div className="fill grid"><section className="card s12"><p className="note">{err ?? 'Loading…'}</p>{err && <button className="btn filled small" type="button" onClick={rerun}>Run detection</button>}</section></div></>);
  }
  const rules = run.methods.rules.eval, best = run.methods.combined.eval;
  return (
    <>
      <PageHeader title="Fraud network" lede={`Mule and laundering networks found by following the money · ${run.data.accounts.toLocaleString('en-GB')} accounts, ${run.data.transfers.toLocaleString('en-GB')} instant payments over ${run.data.days} days, ${run.data.banks.length} banks · ${run.data.source}`}
        actions={<>
          <button className="btn small" type="button" onClick={() => setSettings((s) => !s)} aria-expanded={settings}>Settings</button>
          <button className="btn filled small" type="button" onClick={rerun} disabled={!!job}>{job ? `Running ${Math.round(job.progress * 100)}%` : 'Run detection'}</button>
        </>} />
      {settings && (
        <div className="fr-settings">
          <label>Money in and out within <b className="num">{hold} min</b><input type="range" min={30} max={720} step={30} value={hold} onChange={(e) => setHold(Number(e.target.value))} aria-label="Hold window in minutes" /></label>
          <label>Amount passed on at least <b className="num">{Math.round(flow * 100)}%</b><input type="range" min={0.5} max={0.95} step={0.05} value={flow} onChange={(e) => setFlow(Number(e.target.value))} aria-label="Share passed on" /></label>
          <span className="sub">Applies to the money trail and everything built on it. Run detection to apply.</span>
        </div>
      )}
      {view !== 'network' && <div className="fr-headline">
        <p><b>Rules</b> raise <b className="num">{rules.cases}</b> separate alerts and catch <b className="num">{rules.rings_whole}</b> of {rules.rings} rings whole. <b>Following the money</b> finds the same laundering as <b className="num">{best.cases}</b> cases, catches <b className="num">{best.rings_whole}</b> rings whole, and <b className="num">{Math.round(best.precision * 100)}%</b> of the accounts it flags are laundering (rules: {Math.round(rules.precision * 100)}%).</p>
      </div>}
      <div className={`fill grid fr-grid ${view === 'network' ? 'wide' : ''}`}>
        <section className="card fr-net">
          <div className="card-head fr-net-head">
            <div className="segmented" role="tablist" aria-label="Detection method">
              {ORDER.map((k) => <button key={k} type="button" role="tab" aria-pressed={method === k} onClick={() => { setMethod(k); setCaseId(null); }}>{SHORT[k]}</button>)}
            </div>
            <div className="fr-view">
              <div className="segmented" role="tablist" aria-label="View">
                <button type="button" role="tab" aria-pressed={view === 'flow'} disabled={!caseId} onClick={() => setView('flow')}>Money flow</button>
                <button type="button" role="tab" aria-pressed={view === 'network'} onClick={() => setView('network')}>Whole network</button>
              </div>
              {view === 'network' && <div className="segmented" role="tablist" aria-label="Colour">
                <button type="button" role="tab" aria-pressed={colourBy === 'flag'} onClick={() => setColourBy('flag')}>Risk</button>
                <button type="button" role="tab" aria-pressed={colourBy === 'bank'} onClick={() => setColourBy('bank')}>Bank</button>
              </div>}
              {view === 'network' && <label className="switch small-sw"><input type="checkbox" checked={truth} onChange={(e) => setTruth(e.target.checked)} aria-label="Show labelled laundering" /> Show labels</label>}
            </div>
          </div>
          {view === 'flow' && caseId ? (
            detail?.flow ? <>
              <p className="sub fr-flow-cap">Case {caseId}: {detail.size} accounts across {detail.banks} banks moved {aedK(detail.flow_aed)} between them{detail.median_hold_min != null ? `, holding money a median of ${detail.median_hold_min < 120 ? `${detail.median_hold_min} min` : `${(detail.median_hold_min / 60).toFixed(1)} h`} before passing it on` : ''}.{truth && detail.truth.typology ? ` Label: ${TYPO[detail.truth.typology] ?? detail.truth.typology}.` : ''}</p>
              <CaseFlow flow={detail.flow} members={detail.members_detail} active={active} onActive={setActive} step={step} onStep={setStep} />
            </> : <p className="sub">Loading the case…</p>
          ) : (
            <>
              <p className="sub fr-flow-cap">{run.layout.nodes.length} accounts the methods looked at, settling by who pays whom. Accounts that trade a lot pull together; rings show up as tight knots. Click an account to select its case.</p>
              <div className="fr-net-stage">
                <ForceNetwork nodes={run.layout.nodes} edges={run.layout.edges} flagged={flagged} selected={selected} caseOf={caseOf} showTruth={truth}
                  colourBy={colourBy} focusId={picked}
                  onPick={(id) => { setPicked(id); const c = id ? caseOf.get(id) : null; setCaseId(c ?? null); }} />
                {caseId && (() => { const c = M.cases.find((x) => x.id === caseId); return c ? (
                  <aside className="fr-float">
                    <div className="fr-float-head"><strong>Case {c.id}</strong><button type="button" className="link-btn" onClick={() => { setCaseId(null); setPicked(null); }} aria-label="Clear selection">Clear</button></div>
                    <span className="sub">{c.size} accounts · {c.banks} banks · {c.transfers} transfers inside</span>
                    <b className="num">{aed(c.flow_aed)}</b><span className="sub">moved between them{c.median_hold_min != null ? `, held a median ${c.median_hold_min < 120 ? `${c.median_hold_min} min` : `${(c.median_hold_min / 60).toFixed(1)} h`}` : ''}</span>
                    {truth && <span className="sub">Label: {c.truth.typology ? TYPO[c.truth.typology] ?? c.truth.typology : 'not laundering'}</span>}
                    <button type="button" className="btn small filled" onClick={() => setView('flow')}>See the money flow</button>
                  </aside>) : null; })()}
                {!caseId && picked && <aside className="fr-float"><strong>{picked}</strong><span className="sub">Not part of a case flagged by {SHORT[method]}. Its counterparts are highlighted.</span></aside>}
              </div>
            </>
          )}
        </section>
        {view !== 'network' && <section className="card fr-side">
          {!caseId ? (
            <>
              <div className="card-head"><div><h2>{M.label}</h2><p className="sub">{M.total_cases} cases · select one to see how the money moved</p></div></div>
              <div className="fr-score">
                <div><span className="sub">Cases to open</span><b className="num">{M.eval.cases}</b></div>
                <div><span className="sub">Rings caught whole</span><b className="num">{M.eval.rings_whole} / {M.eval.rings}</b></div>
                <div><span className="sub">Flagged that are laundering</span><b className="num">{Math.round(M.eval.precision * 100)}%</b></div>
                <div><span className="sub">Laundering found</span><b className="num">{Math.round(M.eval.recall * 100)}%</b></div>
              </div>
              <ul className="scroll fr-cases">{M.cases.slice(0, 40).map((c) => (
                <li key={c.id}><button type="button" onClick={() => { setCaseId(c.id); setView('flow'); }}>
                  <span className="fr-case-top"><strong>{c.id}</strong><span className="num">{c.size} accounts · {c.banks} banks</span><b className="num">{aed(c.flow_aed)}</b></span>
                  <span className="sub">{c.median_hold_min != null ? `money held ${c.median_hold_min < 120 ? `${c.median_hold_min} min` : `${(c.median_hold_min / 60).toFixed(1)} h`} (median)` : 'single account'}{truth && c.truth.typology ? ` · label: ${TYPO[c.truth.typology] ?? c.truth.typology}` : truth ? ' · label: not laundering' : ''}</span>
                </button></li>
              ))}</ul>
            </>
          ) : (
            <>
              <div className="card-head"><div><h2>Case {caseId}</h2><p className="sub">{detail ? `${detail.size} accounts across ${detail.banks} banks · ${detail.first ? time(detail.first) : ''} to ${detail.last ? time(detail.last) : ''}` : 'Loading…'}</p></div>
                <button className="btn small" type="button" onClick={() => setCaseId(null)}>All cases</button></div>
              {detail && (
                <div className="scroll fr-detail">
                  <div className="fr-score">
                    <div><span className="sub">Money in from outside</span><b className="num">{aed(detail.money_in_aed)}</b><span className="sub">{detail.sources_outside} senders</span></div>
                    <div><span className="sub">Moved inside the case</span><b className="num">{aed(detail.flow_aed)}</b><span className="sub">{detail.transfers} transfers</span></div>
                    <div><span className="sub">Money out to outside</span><b className="num">{aed(detail.money_out_aed)}</b><span className="sub">{detail.exits_outside} recipients</span></div>
                  </div>
                  <h4>How the money moved</h4>
                  <ol className="fr-timeline">{(detail.flow?.events ?? []).map((t, i) => {
                    const k = eventKey(t), now = i === step - 1 && step < (detail.flow?.events.length ?? 0);
                    return (
                      <li key={i} ref={now ? playRow : undefined} className={`${now ? 'now' : ''} ${active === k ? 'hot' : ''} ${i >= step ? 'later' : ''}`}
                        onPointerEnter={() => setActive(k)} onPointerLeave={() => setActive(null)} onClick={() => setStep(i + 1)}>
                        <span className="sub num">{time(t.ts)}</span>
                        <span className="num">{t.kind === 'in' ? <><span className="fr-kind in">In</span>{t.dst}</> : t.kind === 'out' ? <><span className="fr-kind out">Out</span>{t.src}</> : <>{t.src} → {t.dst}</>}</span>
                        <b className="num">{aed(t.amount)}</b>{t.kind === 'inside' && t.cross_bank ? <span className="pill small-pill">Cross-bank</span> : <span />}
                      </li>
                    );
                  })}</ol>
                  <h4>Accounts</h4>
                  <table className="fr-members"><tbody>{detail.members_detail.map((m) => (
                    <tr key={m.account}><td className="num"><strong>{m.account}</strong></td><td>{m.bank}</td><td className="sub">{(() => { const r = detail.flow?.nodes.find((n) => n.id === m.account)?.role; return r ? <><i className="fr-role" style={{ background: ROLE[r].color }} />{ROLE[r].label} · </> : null; })()}{m.kind}, opened {m.opened_days_ago} days ago</td>
                      <td className="r num">in {aed(m.in_aed)}</td><td className="r num">out {aed(m.out_aed)}</td>{truth && <td>{m.truth.label ? <span className="pill red small-pill">{TYPO[m.truth.typology] ?? m.truth.typology}</span> : <span className="pill small-pill">Not labelled</span>}</td>}</tr>
                  ))}</tbody></table>
                </div>
              )}
            </>
          )}
        </section>}
      </div>
      {err && <p className="note worse">{err}</p>}
    </>
  );
}
