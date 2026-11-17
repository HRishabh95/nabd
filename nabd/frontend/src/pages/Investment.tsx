import { useCallback, useEffect, useState } from 'react';
import { PageHeader } from '../components/Chrome';
import AgentTrace from '../components/AgentTrace';
import { api } from '../lib/api';
import { STAGES, STAGE_LABEL, fmt, type Alert, type Idea, type IdeaEvent, type Portfolio, type Stage } from '../lib/invest';
import { useEvent } from '../lib/stream';
import { ResearchPanel, ScreeningPanel, ThesisCard } from './invest/Early';
import { CommitteePanel, FitPanel, MonitorPanel, StressPanel } from './invest/Late';
import { DeepLive, DeepReport } from './invest/Deep';
import { PortfolioView } from './invest/Portfolio';

type Job = { kind: string; job_id: string };
const JOB_TITLE: Record<string, string> = {
  thesis: 'Reading the idea and writing the thesis', research: 'Researching the selected instruments',
  deep_research: 'Deep research',
  stress: 'Running replays, shocks and simulations', committee: 'Drafting the committee cover note', close: 'Writing the lesson',
};

function Composer({ onCreated }: { onCreated: (id: string) => void }) {
  const [text, setText] = useState('');
  const [horizon, setHorizon] = useState<'tactical' | 'strategic'>('tactical');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  async function submit(e: React.FormEvent) {
    e.preventDefault(); setBusy(true); setErr(null);
    try { const r = await api.post<{ idea: Idea }>('/api/invest/ideas', { text, horizon }); setText(''); onCreated(r.idea.id); }
    catch (x) { setErr((x as Error).message); }
    setBusy(false);
  }
  return (
    <form className="composer" onSubmit={submit}>
      <textarea rows={3} value={text} onChange={(e) => setText(e.target.value)} aria-label="New idea"
        placeholder="An idea in your own words, e.g. “Japanese banks benefit as the BoJ normalises; overweight for 6 months”" />
      <div className="composer-row">
        <div className="segmented" role="group" aria-label="Horizon">
          <button type="button" aria-pressed={horizon === 'tactical'} onClick={() => setHorizon('tactical')}>Tactical · MRMC</button>
          <button type="button" aria-pressed={horizon === 'strategic'} onClick={() => setHorizon('strategic')}>Strategic · SAA</button>
        </div>
        <button className="btn filled small" type="submit" disabled={busy || text.trim().length < 3}>{busy ? 'Adding…' : 'Add idea'}</button>
      </div>
      {err && <p className="note worse">{err}</p>}
    </form>
  );
}

function Stepper({ idea, view, setView }: { idea: Idea; view: Stage; setView: (s: Stage) => void }) {
  const cur = STAGES.indexOf(idea.stage);
  const has: Record<Stage, boolean> = {
    idea: true, screening: !!idea.thesis, research: !!idea.research, fit: !!idea.fit, stress: !!idea.stress,
    committee: !!idea.committee, position: !!idea.position, closed: idea.stage === 'closed',
  };
  return (
    <ol className="stepper" aria-label="Lifecycle">
      {STAGES.filter((s) => s !== 'closed' || idea.stage === 'closed').map((s, i) => (
        <li key={s} className={`${i < cur ? 'done' : i === cur ? 'now' : ''} ${view === s ? 'view' : ''}`}>
          <button type="button" disabled={!has[s] && i !== cur} onClick={() => setView(s)} aria-current={view === s ? 'step' : undefined}
            aria-label={`${STAGE_LABEL[s]}${i < cur ? ', done' : i === cur ? ', current stage' : ''}`}>
            <span className="dot num">{i < cur ? '✓' : i + 1}</span><span>{STAGE_LABEL[s]}</span>
          </button>
        </li>
      ))}
    </ol>
  );
}

function NextAction({ idea, job, act }: { idea: Idea; job: Job | null; act: (path: string) => void }) {
  if (job) return null;
  const map: Partial<Record<Stage, [string, string]>> = {
    fit: ['fit', 'Check portfolio fit'], stress: ['stress', 'Run stress tests'], committee: ['committee', idea.committee ? 'Rebuild committee pack' : 'Prepare committee pack'],
  };
  if (idea.stage === 'research' && !idea.research) return <button className="btn filled small" type="button" onClick={() => act('research')}>Run research</button>;
  const a = map[idea.stage];
  if (!a || (idea.stage === 'committee' && idea.committee?.decision)) return null;
  if (idea.stage === 'committee' && idea.committee) return <button className="btn small" type="button" onClick={() => act(a[0])}>{a[1]}</button>;
  return <button className="btn filled small" type="button" onClick={() => act(a[0])}>{a[1]}</button>;
}

// Show the newest result; the button at the top right offers the next step.
function latestView(i: Idea): Stage {
  if (i.stage === 'closed') return 'closed';
  if (i.position) return 'position';
  if (i.committee) return 'committee';
  if (i.stress) return 'stress';
  if (i.fit) return 'fit';
  if (i.research) return 'research';  // includes deep research still running
  if (i.thesis) return 'screening';
  return 'idea';
}

function Audit({ events }: { events: IdeaEvent[] }) {
  return (
    <ol className="audit scroll">
      {[...events].reverse().map((e) => (
        <li key={e.id}><span className="sub num">{fmt.date(e.ts)}</span> <strong>{e.action}</strong> <span className="sub">· {e.actor}</span></li>
      ))}
    </ol>
  );
}

/** What was sent on from screening: lines to trade (add or cut, % of the portfolio) and names to research only. */
function Selected({ idea }: { idea: Idea }) {
  const items = idea.basket?.items ?? [];
  const trades = items.filter((b) => !b.research_only && b.weight_pct), study = items.filter((b) => b.research_only || !b.weight_pct);
  const net = trades.reduce((a, b) => a + b.weight_pct, 0);
  const money = net > 0 ? `Paid for from ${idea.funding === 'cash' ? 'cash (money market)' : 'the equity mandates, pro rata'}.`
    : net < 0 ? `The money from cuts ${idea.funding === 'mandate' ? 'stays in the equity mandates' : 'goes to Treasury bills'}.` : '';
  return (<>
    <h4>To trade</h4>
    {trades.length ? <ul className="bul">{trades.map((b) => <li key={b.symbol}><strong>{b.weight_pct < 0 ? 'Cut' : 'Add'} {Math.abs(b.weight_pct).toFixed(2)}%</strong> {b.name} ({b.symbol})</li>)}</ul>
      : <p className="sub">Nothing: every name was sent to research only, so fit and stress have nothing to test yet.</p>}
    {money && <p className="sub">{money}</p>}
    {!!study.length && <><h4>Research only</h4><p className="sub">{study.map((b) => `${b.name} (${b.symbol})`).join(' · ')}. Studied in deep research; not traded, so not in fit or stress.</p></>}
  </>);
}

function Workspace({ ideaId, job, onJob, initial, onDeleted }: { ideaId: string; job: Job | null; onJob: (j: Job) => void; initial?: Stage; onDeleted: () => void }) {
  const [idea, setIdea] = useState<Idea | null>(null);
  const [events, setEvents] = useState<IdeaEvent[]>([]);
  const [view, setView] = useState<Stage>('idea');
  const [tab, setTab] = useState<'work' | 'audit'>('work');
  const [err, setErr] = useState<string | null>(null);
  const [confirmDel, setConfirmDel] = useState(false);

  const load = useCallback(async (follow = false) => {
    const r = await api.get<{ idea: Idea; events: IdeaEvent[] }>(`/api/invest/ideas/${ideaId}`);
    setIdea(r.idea); setEvents(r.events);
    if (follow) setView(latestView(r.idea));
  }, [ideaId]);
  useEffect(() => { load(true).then(() => { if (initial) setView(initial); }); }, [load, initial]);
  useEvent('idea.updated', (e) => { if (e.data.idea_id === ideaId) load(true); });
  useEvent('idea.health', (e) => { if (e.data.idea_id === ideaId) load(false); });
  useEvent('deep.progress', (e) => { if (e.data.idea_id === ideaId) load(false); });

  async function remove() {
    setErr(null);
    try { await api.del(`/api/invest/ideas/${ideaId}`); onDeleted(); } catch (e) { setErr((e as Error).message); setConfirmDel(false); }
  }

  async function act(path: string) {
    setErr(null);
    try {
      const r = await api.post<{ job_id?: string }>(`/api/invest/ideas/${ideaId}/${path}`);
      if (r.job_id) onJob({ kind: path, job_id: r.job_id });
      await load(true);
    } catch (e) { setErr((e as Error).message); }
  }

  if (!idea) return <section className="card ws"><p className="note">Loading…</p></section>;
  const showTrace = job && (['thesis', 'stress', 'committee', 'close'].includes(job.kind));
  const deep = idea.research?.kind === 'deep' ? idea.research : null;
  const deepRunning = !!deep && deep.stage !== 'done' || job?.kind === 'deep_research';
  const ran: Record<Stage, boolean> = { idea: true, screening: true, research: !!idea.research, fit: !!idea.fit,
    stress: !!idea.stress, committee: !!idea.committee, position: !!idea.position, closed: !!idea.position };
  return (
    <section className="card ws">
      <div className="ws-head">
        <div className="ws-title">
          <span className="sub num">{idea.id} · {idea.horizon === 'tactical' ? 'Tactical' : 'Strategic'} · {idea.owner}</span>
          <h2>{idea.thesis?.title ?? idea.title}</h2>
        </div>
        <div className="head-ctl">
          {confirmDel ? (<>
            <span className="sub">Delete this idea? It leaves the pipeline; its audit trail is kept.</span>
            <button className="btn small danger" type="button" onClick={remove}>Delete</button>
            <button className="btn small" type="button" onClick={() => setConfirmDel(false)}>Cancel</button>
          </>) : (<>
            <div className="segmented" role="tablist" aria-label="Workspace view">
              <button type="button" role="tab" aria-pressed={tab === 'work'} onClick={() => setTab('work')}>Work</button>
              <button type="button" role="tab" aria-pressed={tab === 'audit'} onClick={() => setTab('audit')}>Audit trail · {events.length}</button>
            </div>
            <button className="btn small" type="button" onClick={() => setConfirmDel(true)} title="Delete this idea">Delete</button>
            <NextAction idea={idea} job={job} act={act} />
          </>)}
        </div>
      </div>
      <Stepper idea={idea} view={view} setView={(s) => { setView(s); setTab('work'); }} />
      {err && <p className="note worse">{err}</p>}
      <div className="ws-body">
        {tab === 'audit' ? <Audit events={events} /> : showTrace && job ? (
          <AgentTrace ideaId={idea.id} step={job.kind === 'thesis' ? 'thesis' : job.kind} title={JOB_TITLE[job.kind] ?? 'Working'} />
        ) : (
          <>
            {view === 'idea' && (
              <section className="panel scroll"><h3>The idea as written</h3><p className="lead">{idea.text}</p>
                {idea.thesis ? <ThesisCard idea={idea} /> : <p className="note">Waiting for the thesis.</p>}</section>
            )}
            {view === 'screening' && idea.thesis && (idea.stage === 'screening' ? (
              <div className="stack-ws"><ThesisCard idea={idea} compact /><ScreeningPanel idea={idea} onDone={() => load(true)} /></div>
            ) : (
              <section className="panel scroll"><ThesisCard idea={idea} /><Selected idea={idea} /></section>
            ))}
            {view === 'research' && (deepRunning ? <DeepLive idea={idea} /> : deep ? <DeepReport idea={idea} onRerun={() => load(true)} /> : <ResearchPanel idea={idea} />)}
            {view === 'fit' && <FitPanel idea={idea} onChange={() => load(false)} />}
            {view === 'stress' && <StressPanel idea={idea} />}
            {view === 'committee' && <CommitteePanel key={idea.updated} idea={idea} onChange={() => load(true)} />}
            {(view === 'position' || view === 'closed') && <MonitorPanel idea={idea} onChange={() => load(true)} />}
            {!ran[view] && !(view === 'research' && deepRunning) && (
              <section className="panel"><p className="note">Not run yet. Use the button at the top right.</p></section>
            )}
          </>
        )}
      </div>
    </section>
  );
}

export default function Investment() {
  const [ideas, setIdeas] = useState<Idea[]>([]);
  const [sel, setSel] = useState<string | null>(null);
  const [portfolio, setPortfolio] = useState<Portfolio | null>(null);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [jobs, setJobs] = useState<Record<string, Job>>({}); // idea id -> running job
  const [toast, setToast] = useState<string | null>(null);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [mode, setMode] = useState<'portfolio' | 'ideas'>('portfolio');
  const [initial, setInitial] = useState<Stage | undefined>(undefined);

  const load = useCallback(async () => {
    const [i, p, a] = await Promise.all([
      api.get<{ ideas: Idea[] }>('/api/invest/ideas'), api.get<Portfolio>('/api/invest/portfolio'), api.get<{ alerts: Alert[] }>('/api/invest/alerts'),
    ]);
    setIdeas(i.ideas); setPortfolio(p); setAlerts(a.alerts); setLoadErr(null);
    setSel((s) => s ?? i.ideas[0]?.id ?? null);
  }, []);
  useEffect(() => { load().catch((e) => setLoadErr((e as Error).message)); }, [load]);
  useEffect(() => { dispatchEvent(new CustomEvent('nabd:context', { detail: { idea_id: sel } })); }, [sel]);
  useEffect(() => {  // opened from a link to one idea: show that idea's dossier
    try {
      const id = sessionStorage.getItem('nabd.openIdea');
      if (id) { sessionStorage.removeItem('nabd.openIdea'); setSel(id); setMode('portfolio'); }
    } catch { /* storage unavailable */ }
  }, []);
  useEffect(() => {  // pick up jobs already running (e.g. after a reload)
    api.get<{ jobs: { id: string; kind: string; status: string; params: { idea_id?: string } }[] }>('/api/data/jobs').then((r) => {
      const run: Record<string, Job> = {};
      r.jobs.filter((j) => j.status === 'running' && j.params?.idea_id).forEach((j) => { run[j.params.idea_id!] = { kind: j.kind, job_id: j.id }; });
      setJobs(run);
    }).catch(() => undefined);
  }, []);

  useEvent('idea.updated', () => { load().catch(() => undefined); });
  useEvent('job.started', (e) => {
    const id = (e.data.params as { idea_id?: string })?.idea_id;
    if (id) setJobs((j) => ({ ...j, [id]: { kind: String(e.data.kind), job_id: String(e.data.job_id) } }));
  });
  const endJob = (e: { data: Record<string, unknown> }, failed: boolean) => {
    const id = (e.data.params as { idea_id?: string })?.idea_id;
    if (!id) return;
    setJobs((j) => { const n = { ...j }; delete n[id]; return n; });
    if (failed) setToast(`${id}: ${String(e.data.error ?? 'the step failed')}`);
    load().catch(() => undefined);
  };
  useEvent('job.done', (e) => endJob(e, false));
  useEvent('job.failed', (e) => endJob(e, true));
  useEvent('alert', (e) => { setToast(`Alert · ${String(e.data.title)}`); load().catch(() => undefined); });
  useEvent('research.done', (e) => { setToast(`Deep research ready · ${String(e.data.title)}: ${String(e.data.overall)}`); load().catch(() => undefined); });
  useEffect(() => { if (!toast) return; const t = setTimeout(() => setToast(null), 6000); return () => clearTimeout(t); }, [toast]);

  const byStage = STAGES.map((s) => [s, ideas.filter((i) => i.stage === s)] as const).filter(([, l]) => l.length);
  return (
    <>
      <PageHeader title="Investment" lede="Ideas judged as tilts against the Strategic Asset Allocation, inside the Board’s risk budget"
        actions={<div className="segmented" role="tablist" aria-label="Investment view">
          <button type="button" role="tab" aria-pressed={mode === 'portfolio'} onClick={() => setMode('portfolio')}>Portfolio</button>
          <button type="button" role="tab" aria-pressed={mode === 'ideas'} onClick={() => { setInitial(undefined); setMode('ideas'); }}>Ideas{alerts.filter((a) => a.status === 'open').length ? ` · ${alerts.filter((a) => a.status === 'open').length} alerts` : ''}</button>
        </div>} />
      {loadErr && !ideas.length && <p className="note worse" role="alert">Could not reach Nabd’s server ({loadErr}). It reconnects automatically; the badge at the top right shows when it is back.</p>}
      {mode === 'portfolio' ? (
        <PortfolioView ideas={ideas} portfolio={portfolio} initial={sel}
          onWork={(id) => { setSel(id); setInitial(undefined); setMode('ideas'); }}
          onOpen={(id) => { setSel(id); setInitial('research'); setMode('ideas'); }}
          onDeleted={() => { setSel(null); load().catch(() => undefined); }} />
      ) : (
      <div className="fill grid iv-grid2">
        <section className="card pipe">
          <div className="card-head"><div><h2>Ideas</h2><p className="sub">{ideas.length} in the pipeline</p></div></div>
          <Composer onCreated={(id) => { setSel(id); setInitial(undefined); load(); }} />
          <div className="scroll pipe-list">
            {byStage.map(([s, list]) => (
              <div key={s} className="pipe-group">
                <h4>{STAGE_LABEL[s]} <span className="num sub">{list.length}</span></h4>
                {list.map((i) => (
                  <button key={i.id} type="button" className={`idea-row ${sel === i.id ? 'on' : ''}`} onClick={() => setSel(i.id)}
                    aria-pressed={sel === i.id} aria-label={`${i.thesis?.title ?? i.title}, ${i.id}, ${STAGE_LABEL[i.stage]}${i.position?.health ? `, health ${i.position.health.score}` : ''}`}>
                    <span className="idea-title">{i.thesis?.title ?? i.title}</span>
                    <span className="sub num">{i.id}{i.basket ? ` · ${i.basket.total_pct}%` : ''}{jobs[i.id] ? ' · working…' : ''}</span>
                    {i.position?.health && <span className={`hscore num ${i.position.health.score < 60 ? 'worse' : i.position.health.score < 85 ? 'warn' : 'better'}`}>{i.position.health.score}</span>}
                  </button>
                ))}
              </div>
            ))}
            {!ideas.length && <p className="note">No ideas yet. Write one above; Nabd turns it into a thesis and screens the universe.</p>}
          </div>
        </section>
        {sel ? <Workspace key={sel} ideaId={sel} initial={initial} job={jobs[sel] ?? null} onJob={(j) => setJobs((m) => ({ ...m, [sel]: j }))}
          onDeleted={() => { try { sessionStorage.removeItem('nabd.openIdea'); } catch { /* storage unavailable */ } setSel(null); load().catch(() => undefined); }} /> : <section className="card ws"><p className="note">Select or add an idea.</p></section>}
      </div>
      )}
      <div className={`toast glass ${toast ? 'show' : ''}`} role="status" aria-live="polite">{toast}</div>
    </>
  );
}
