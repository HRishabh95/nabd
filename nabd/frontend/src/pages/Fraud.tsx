import { useCallback, useEffect, useMemo, useState } from 'react';
import { PageHeader } from '../components/Chrome';
import CaseFlow, { aed, type Flow } from '../components/CaseFlow';
import FraudGraph, { type Net } from '../components/FraudGraph';
import Review from '../components/Review';
import { api } from '../lib/api';

// One investigation, end to end: summary → the network (rings or money flow) → the AI's grounded note.
type Eval = { precision: number; recall: number; rings: number; rings_whole: number; cases: number };
type Case = Net & { members: string[]; score: number; first: string; last: string; median_hold_min: number | null; pass_through_share: number };
type Run = { run_id: string; created: number; data: { accounts: number; transfers: number; banks: string[]; days: number; start: string; rings: number };
  summary: { transfers: number; suspicious_transfers: number; suspicious_aed: number; networks: number; accounts_in_networks: number; high_risk_accounts: number };
  methods: { combined: { eval: Eval; cases: Case[] }; ml: { eval: Eval } } };
type Member = { account: string; bank: string; kind: string; opened_days_ago: number; in_aed: number; out_aed: number; risk: number; role: string | null };
type Detail = Case & { members_detail: Member[]; flow: Flow; money_in_aed: number; money_out_aed: number; sources_outside: number; exits_outside: number;
  bank_list: string[] };
type Note = { headline: string; why_flagged: string[]; connections?: string; pattern?: string; transfers: { ts: string; src: string; dst: string; amount: number; why: string }[];
  next_steps: string[]; caveats: string; checked: { cited: number; matched: number }; account: string | null };

const pct = (v: number) => `${Math.round(v * 100)}%`;
const when = (s: string) => new Date(s.replace(' ', 'T')).toLocaleString('en-GB', { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
const ROLE: Record<string, string> = { entry: 'Money enters here', start: 'Starts the loop', pass: 'Passes money on', exit: 'Money leaves here', single: 'Linked account' };

export default function Fraud() {
  const [run, setRun] = useState<Run | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [view, setView] = useState<'rings' | 'flow'>('rings');
  const [sel, setSel] = useState<string | null>(null);
  const [day, setDay] = useState<number | null>(null);
  const [playing, setPlaying] = useState(false);
  const [q, setQ] = useState('');
  const [found, setFound] = useState<string | null>(null);
  const [note, setNote] = useState<Note | null>(null);
  const [noteBusy, setNoteBusy] = useState(false);
  const [noteErr, setNoteErr] = useState<string | null>(null);
  const [active, setActive] = useState<string | null>(null);
  const [step, setStep] = useState(0);
  const [saw, setSaw] = useState<{ instructions: string; facts: string; characters: number; withheld: string[] } | null>(null);
  const [safety, setSafety] = useState(false);

  useEffect(() => { api.get<Run>('/api/fraud').then((r) => { setRun(r); setOpen((o) => o ?? r.methods.combined.cases[0]?.id ?? null); }, (e) => setErr(e.message)); }, []);
  useEffect(() => {
    setDetail(null); setSel(null); setNote(null); setStep(0); setActive(null); setDay(null);
    if (!open) return;
    api.get<Detail>(`/api/fraud/case/combined/${open}`).then((d) => { setDetail(d); setStep(d.flow.events.length); }, (e) => setErr(e.message));
  }, [open]);

  const loadNote = useCallback(async (caseId: string, account: string | null, generate: boolean) => {
    setNoteErr(null);
    const qs = account ? `?account=${account}` : '';
    try { setNote(await api.get<Note>(`/api/fraud/case/${caseId}/note${qs}`)); return; } catch { /* not written yet */ }
    if (!generate) { setNote(null); return; }
    setNoteBusy(true);
    try { setNote(await api.post<Note>(`/api/fraud/case/${caseId}/note${qs}`)); } catch (e) { setNoteErr((e as Error).message); } finally { setNoteBusy(false); }
  }, []);
  // the open network's note loads (or is written) automatically; an account's note only when asked
  useEffect(() => { if (open) loadNote(open, null, true); }, [open, loadNote]);

  // replay the network's growth one day at a time
  useEffect(() => {
    if (!playing || !run) return;
    const t = setTimeout(() => setDay((d) => { const n = (d ?? -1) + 1; if (n >= run.data.days) { setPlaying(false); return null; } return n; }), 700);
    return () => clearTimeout(t);
  }, [playing, day, run]);

  const cases = useMemo(() => run?.methods.combined.cases ?? [], [run]);
  const accounts = useMemo(() => (detail?.members_detail ?? []).map((m) => ({ account: m.account, bank: m.bank, risk: m.risk, role: m.role })), [detail]);
  const start = run ? new Date(`${run.data.start}T00:00:00Z`) : null;
  const cutoff = start && day != null ? new Date(start.getTime() + (day + 1) * 864e5 - 1000).toISOString().slice(0, 19).replace('T', ' ') : null;
  const member = detail?.members_detail.find((m) => m.account === sel) ?? null;

  async function search(e: React.FormEvent) {
    e.preventDefault();
    const id = q.trim().toUpperCase();
    if (!id) return;
    const c = cases.find((x) => x.members.includes(id));
    if (c) { setFound(null); setView('rings'); if (c.id !== open) { setOpen(c.id); setTimeout(() => setSel(id), 600); } else setSel(id); return; }
    try {
      const r = await api.get<{ risk: number; case: string | null }>(`/api/fraud/account/${id}`);
      setFound(`${id} is not in a detected network · ML risk ${r.risk.toFixed(2)}`);
    } catch { setFound(`${id} not found`); }
  }

  if (!run) return (<><PageHeader title="Fraud network" lede="Synthetic payments" /><div className="fill grid"><article className="card s12"><p className="note">{err ?? 'Loading…'}</p></article></div></>);
  const S = run.summary, E = run.methods.combined.eval, M = run.methods.ml.eval;

  return (
    <>
      <PageHeader title="Fraud network" lede={`Synthetic payments (AMLSim-style), not real customers: ${run.data.accounts.toLocaleString('en-GB')} accounts at ${run.data.banks.length} banks over ${run.data.days} days`} />
      <dl className="metrics fr-kpis">
        <div className="metric"><dt>Transactions analysed</dt><dd className="num">{S.transfers.toLocaleString('en-GB')}</dd><span>every account scored by the ML model</span></div>
        <div className="metric"><dt>Suspicious transactions</dt><dd className="num">{S.suspicious_transfers.toLocaleString('en-GB')}</dd><span className="num">{aed(S.suspicious_aed)} moved inside the networks</span></div>
        <div className="metric"><dt>Networks detected</dt><dd className="num">{S.networks}</dd><span className="num">{S.accounts_in_networks} accounts · {E.rings_whole} of {E.rings} planted rings caught whole</span></div>
        <div className="metric"><dt>Detection performance</dt><dd className="num">{pct(E.precision)} precise</dd><span className="num">finds {pct(E.recall)} of laundering accounts · against the synthetic labels</span></div>
      </dl>
      <div className="fill grid fr-main">
        <article className="card s8 fr-net">
          <div className="card-head">
            <div><h2>{detail ? `${detail.id} · ${detail.pattern.label}` : 'Detected networks'}</h2>
              <p className="sub">{detail ? `${detail.size} accounts at ${detail.banks} banks moved ${aed(detail.flow_aed)} between them in ${detail.transfers} transfers, ${when(detail.first)} to ${when(detail.last)}` : `${cases.length} networks found by following the money; click one to open it`}</p></div>
            <div className="head-ctl">
              <div className="segmented" role="group" aria-label="View">
                <button type="button" aria-pressed={view === 'rings'} onClick={() => setView('rings')}>Fraud rings</button>
                <button type="button" aria-pressed={view === 'flow'} onClick={() => setView('flow')} disabled={!detail}>Money flow</button>
              </div>
              <select className="popup" value={open ?? ''} onChange={(e) => setOpen(e.target.value || null)} aria-label="Network">
                <option value="">All networks</option>
                {cases.map((c) => <option key={c.id} value={c.id}>{c.id} · {c.pattern.label.split(':')[0]} · {aed(c.flow_aed)}</option>)}
              </select>
              <form onSubmit={search} className="fr-search"><input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Find account, e.g. AC04494" aria-label="Find an account" /></form>
            </div>
          </div>
          {found && <p className="note">{found}</p>}
          <div className="fr-canvas">
            {view === 'rings' || !detail
              ? <FraudGraph nets={cases} open={open} flow={detail?.flow ?? null} accounts={accounts} selected={sel} cutoff={cutoff} onOpen={(id) => { setOpen(id); setView('rings'); }} onSelect={setSel} />
              : <CaseFlow flow={detail.flow} members={detail.members_detail} active={active} onActive={setActive} step={step} onStep={setStep} lanes />}
          </div>
          <div className="fr-foot">
            {view === 'rings' ? (<>
              <button className="btn small filled fr-play" type="button" onClick={() => { if (!playing && day == null) setDay(0); setPlaying((p) => !p); }} aria-pressed={playing}>{playing ? 'Pause' : 'Play the days'}</button>
              <label className="fr-time"><span>Transfers up to <b>{day == null ? 'the end' : new Date(start!.getTime() + day * 864e5).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })}</b></span>
                <input type="range" min={0} max={run.data.days} value={day ?? run.data.days} onChange={(e) => { setPlaying(false); const v = Number(e.target.value); setDay(v >= run.data.days ? null : v); }} aria-label="Show transfers up to this day" /></label>
              <ul className="fr-legend"><li><i className="r9" />ML risk ≥ 0.9</li><li><i className="r6" />0.6–0.9</li><li><i className="r2" />0.25–0.6</li><li><i className="ring" />money enters or leaves</li><li><i className="badge">①</i>order of transfers</li><li><span className="tr-pair"><i className="tr-down" /><i className="tr-up" /></span>traced onward / back</li></ul>
            </>) : <p className="note">Left to right in time, one row per bank: a move between rows is a cross-bank transfer. Press Replay to watch the money move.</p>}
          </div>
        </article>
        <article className="card s4 fr-ai">
          <div className="card-head"><div><h2>AI investigation</h2><p className="sub">Written from this network’s transfers and the models’ results · synthetic data</p></div></div>
          <div className="scroll fr-ai-body">
            {member && (
              <section className="fr-acct">
                <div className="fr-acct-top"><b>{member.account}</b><span className={`fr-risk ${member.risk >= 0.9 ? 'hi' : member.risk >= 0.6 ? 'mid' : ''}`}>ML risk {member.risk.toFixed(2)}</span></div>
                <p className="sub">{member.bank} · {member.kind} · opened {member.opened_days_ago} days ago · {ROLE[member.role ?? 'single']}</p>
                <p className="num fr-acct-flow">In {aed(member.in_aed)} · out {aed(member.out_aed)}</p>
                {note?.account !== member.account
                  ? <button className="btn small" type="button" disabled={noteBusy} onClick={() => loadNote(open!, member.account, true)}>Explain this account</button>
                  : <button className="btn small" type="button" onClick={() => loadNote(open!, null, true)}>Back to the network note</button>}
              </section>
            )}
            {!open && <p className="note">Open a network to see why it was flagged.</p>}
            {noteBusy && <p className="note fr-busy">The AI is reading {detail ? `${detail.transfers} transfers between ${detail.size} accounts` : 'the transfers'}…</p>}
            {noteErr && <p className="note worse">{noteErr}</p>}
            {note && !noteBusy && (
              <>
                <p className="fr-lead">{note.headline}</p>
                <h3>Why it was flagged</h3>
                <ul className="fr-why">{note.why_flagged.map((w, i) => <li key={i}>{w}</li>)}</ul>
                <h3>Pattern and connections</h3>
                <p className="fr-p">{note.connections ?? note.pattern}</p>
                <h3>Suspicious transfers</h3>
                <ul className="fr-tx">{note.transfers.map((t, i) => (
                  <li key={i}><button type="button" onClick={() => { setView('rings'); setSel(t.src); }} title="Trace this account in the network">
                    <span className="num">{when(t.ts)}</span><span className="fr-tx-path">{t.src} → {t.dst}</span><b className="num">{aed(t.amount)}</b></button>
                    <p>{t.why}</p></li>))}</ul>
                <h3>What to examine next</h3>
                <ol className="fr-next">{note.next_steps.map((s, i) => <li key={i}>{s}</li>)}</ol>
                <p className="note">{note.caveats}</p>
                <Review kind="fraud_note" refId={`${run.run_id}:${open}:${note.account ?? ''}`} label="Was this note useful to an investigator?" />
                <div className="fr-ai-tools">
                  <button className="btn small" type="button" onClick={async () => setSaw(await api.get(`/api/fraud/case/${open}/facts${note.account ? `?account=${note.account}` : ''}`))}>What the AI saw</button>
                  <button className="btn small" type="button" aria-expanded={safety} onClick={() => setSafety((v) => !v)}>Real payment data: how it stays safe</button>
                </div>
                {safety && (
                  <ul className="fr-safety">
                    <li><b>Data stays inside CBUAE.</b> Detection (the ML score and following the money) is ordinary Python that runs where the data is; nothing leaves the network.</li>
                    <li><b>Accounts are codes.</b> Account and customer identifiers are replaced by keyed pseudonyms before analysis; only CBUAE holds the key to reverse them, for a case an investigator opens.</li>
                    <li><b>The AI sees only one network.</b> A note is written from that network’s transfers (amounts, times, banks, scores), never names, IDs or the wider ledger. <i>What the AI saw</i> shows the exact text.</li>
                    <li><b>The AI model runs inside the boundary.</b> In production the same gateway points to an on-premise model or Azure OpenAI in the UAE; this demo uses OpenAI through Codex and therefore synthetic data only.</li>
                    <li><b>Every note is logged and checked.</b> Who asked, when, which model; cited transfers are matched to the data before display.</li>
                  </ul>
                )}
                <p className="note fr-check">Checked: {note.checked.matched} of {note.checked.cited} cited transfers match the data{note.checked.matched < note.checked.cited ? '; the rest were removed' : ''}. The AI did not see the synthetic labels.</p>
              </>
            )}
            <p className="note fr-models">How it was found: gradient-boosted trees score each account’s behaviour (alone: {pct(M.precision)} precise, finds {pct(M.recall)}); following the money through pass-through and circular transfers groups accounts into networks, keeping those the score agrees with.</p>
          </div>
        </article>
      </div>
      {saw && (
        <div className="lab-backdrop" onClick={() => setSaw(null)}>
          <div className="lab" role="dialog" aria-modal="true" aria-label="What the AI saw" onClick={(e) => e.stopPropagation()}>
            <div className="lab-head"><div><h2>What the AI saw</h2><p className="sub">The complete input for this note: {saw.characters.toLocaleString('en-GB')} characters of facts plus the instructions</p></div>
              <button className="btn small" type="button" onClick={() => setSaw(null)} autoFocus>Close</button></div>
            <h3 className="fr-saw-h">Not sent</h3>
            <ul className="fr-why">{saw.withheld.map((w) => <li key={w}>{w}</li>)}</ul>
            <h3 className="fr-saw-h">Instructions</h3><pre className="fr-saw">{saw.instructions}</pre>
            <h3 className="fr-saw-h">Facts</h3><pre className="fr-saw">{saw.facts}</pre>
          </div>
        </div>
      )}
    </>
  );
}
