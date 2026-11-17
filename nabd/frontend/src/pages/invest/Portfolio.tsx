// Portfolio view: what the portfolio holds, and every idea tested. Selecting an idea opens its dossier: the deals,
// the research verdict, risk, the decision and monitoring, in plain language. Details live one click deeper.
import { useEffect, useMemo, useState } from 'react';
import { api } from '../../lib/api';
import { STAGE_LABEL, fmt, type Deep, type Idea, type Portfolio } from '../../lib/invest';

type Pos = { entry: number | null; last: number | null };

const STATUS: Record<string, [string, string]> = {
  position: ['green', 'Approved · monitoring'], committee: ['tint', 'At committee'], closed: ['', 'Closed'],
  stress: ['orange', 'In analysis'], fit: ['orange', 'In analysis'], research: ['orange', 'Researching'],
  screening: ['', 'Screening'], idea: ['', 'New'],
};

function status(i: Idea): [string, string] {
  if (i.status === 'rejected') return ['red', 'Rejected'];
  if (i.committee?.decision?.decision === 'defer') return ['orange', 'Deferred'];
  return STATUS[i.stage] ?? ['', STAGE_LABEL[i.stage]];
}

function Holdings({ p }: { p: Portfolio }) {
  return (
    <div className="pf-holdings">
      {p.tranches.map((t) => (
        <div key={t.name} className="pf-tranche">
          <div className="pf-tranche-head"><span>{t.name}</span><b className="num">{t.weight.toFixed(0)}%</b></div>
          <span className="pf-bar"><i style={{ width: `${t.weight}%` }} /></span>
          <span className="sub">{(p.lines ?? []).filter((l) => l.tranche === t.name).map((l) => l.symbol).join(' · ')}</span>
        </div>
      ))}
    </div>
  );
}

export function PortfolioView({ ideas, portfolio, onOpen, onWork, onDeleted, initial }: {
  ideas: Idea[]; portfolio: Portfolio | null; onOpen: (id: string) => void; onWork: (id: string) => void; onDeleted: () => void; initial?: string | null;
}) {
  const [sel, setSel] = useState<string | null>(initial ?? null);
  useEffect(() => { if (initial) setSel(initial); }, [initial]);
  const idea = useMemo(() => ideas.find((i) => i.id === sel) ?? null, [ideas, sel]);
  useEffect(() => { if (!sel && ideas.length) setSel(ideas[0].id); }, [ideas, sel]);
  const groups: [string, Idea[]][] = [
    ['Approved', ideas.filter((i) => i.stage === 'position')],
    ['In progress', ideas.filter((i) => !['position', 'closed'].includes(i.stage))],
    ['Closed or rejected', ideas.filter((i) => i.stage === 'closed')],
  ];
  return (
    <div className="fill grid pf-grid">
      <section className="card pf-left">
        <div className="card-head"><div><h2>Portfolio</h2><p className="sub">Notional USD {portfolio?.notional_usd_bn ?? '—'} bn · illustrative, not CBUAE’s holdings</p></div></div>
        {portfolio && <Holdings p={portfolio} />}
        {portfolio && (
          <div className="pf-risk">
            <span className="sub">Active risk in use</span>
            <span className="pf-bar big-bar"><i className={portfolio.risk.budget_used_pct.before > 80 ? 'warn' : ''} style={{ width: `${Math.min(100, portfolio.risk.budget_used_pct.before)}%` }} /></span>
            <span className="num"><b>{portfolio.risk.budget_used_pct.before.toFixed(0)}%</b> of the {portfolio.active_risk_budget_bp} bp budget · market regime {portfolio.regime.state}</span>
          </div>
        )}
        <div className="card-head pf-ideas-head"><div><h2>Ideas tested</h2><p className="sub">{ideas.length} ideas · select one to see its deals and research</p></div></div>
        <div className="scroll pf-list">
          {groups.filter(([, l]) => l.length).map(([g, l]) => (
            <div key={g} className="pipe-group"><h4>{g} <span className="sub num">{l.length}</span></h4>
              {l.map((i) => { const [tone, label] = status(i); return (
                <button key={i.id} type="button" className={`idea-row ${sel === i.id ? 'on' : ''}`} onClick={() => setSel(i.id)} aria-pressed={sel === i.id}>
                  <span className="idea-title">{i.thesis?.title ?? i.title}</span>
                  <span className="sub">{i.basket ? i.basket.items.map((b) => `${b.symbol} ${b.weight_pct > 0 ? '+' : ''}${b.weight_pct}%`).join(' · ') : i.id}</span>
                  <span className={`pill ${tone} idea-pill`}>{label}</span>
                </button>); })}
            </div>
          ))}
        </div>
      </section>
      {idea ? <Dossier key={idea.id} idea={idea} onWork={() => onWork(idea.id)} onOpen={() => onOpen(idea.id)} onDeleted={() => { setSel(null); onDeleted(); }} />
        : <section className="card"><p className="note">No ideas yet. Add one in the Ideas view.</p></section>}
    </div>
  );
}

function Dossier({ idea, onWork, onOpen, onDeleted }: { idea: Idea; onWork: () => void; onOpen: () => void; onDeleted: () => void }) {
  const [confirm, setConfirm] = useState(false);
  const [prices, setPrices] = useState<Record<string, Pos>>({});
  const deep = idea.research?.kind === 'deep' ? (idea.research as Deep) : null;
  const syn = deep?.synthesis;
  const [tone, label] = status(idea);
  const h = idea.position?.health;
  useEffect(() => {  // last prices for the deals, to show the move since entry
    if (!idea.basket || !idea.position) return;
    const entry = (idea.position as unknown as { entry_prices?: Record<string, number> }).entry_prices ?? {};
    Promise.all(idea.basket.items.map((b) => api.get<{ rows: { adjclose: number }[] }>(`/api/data/series/${encodeURIComponent(b.symbol)}?start=${new Date(Date.now() - 20 * 864e5).toISOString().slice(0, 10)}`)
      .then((r) => [b.symbol, { entry: entry[b.symbol] ?? null, last: r.rows.length ? r.rows[r.rows.length - 1].adjclose : null }] as const).catch(() => [b.symbol, { entry: null, last: null }] as const)))
      .then((xs) => setPrices(Object.fromEntries(xs)));
  }, [idea]);
  async function del() { await api.del(`/api/invest/ideas/${idea.id}`); onDeleted(); }
  return (
    <section className="card dossier">
      <div className="ws-head">
        <div className="ws-title"><span className="sub num">{idea.id} · {idea.horizon === 'tactical' ? 'Tactical · MRMC' : 'Strategic · SAA review'}</span><h2>{idea.thesis?.title ?? idea.title}</h2>
          <span className={`pill ${tone}`}>{label}</span></div>
        <div className="head-ctl">
          {confirm ? (<><span className="sub">Delete this idea? Its audit trail is kept.</span><button className="btn small danger" type="button" onClick={del}>Delete</button><button className="btn small" type="button" onClick={() => setConfirm(false)}>Cancel</button></>)
            : (<><button className="btn small" type="button" onClick={() => setConfirm(true)}>Delete</button><button className="btn filled small" type="button" onClick={onWork}>Open in workspace</button></>)}
        </div>
      </div>
      <div className="scroll dossier-body">
        {idea.thesis && <p className="lead">{idea.thesis.summary}</p>}
        {!!idea.thesis?.assumptions?.length && <p className="sub">How Nabd read the idea: {idea.thesis.assumptions.join(' ')}</p>}
        <div className="dossier-grid">
          <article className="dcard">
            <h3>Deals</h3>
            {idea.basket ? (
              <table className="deals"><tbody>{idea.basket.items.map((b) => { const p = prices[b.symbol]; const mv = p?.entry && p?.last ? (p.last / p.entry - 1) * 100 : null; return (
                <tr key={b.symbol}><td><strong>{b.symbol}</strong> <span className="sub">{b.name}</span></td>
                  <td className={`r num ${b.weight_pct < 0 ? 'worse' : ''}`}>{b.weight_pct > 0 ? 'Buy ' : 'Cut '}{Math.abs(b.weight_pct).toFixed(2)}%</td>
                  <td className="r num sub">{mv == null ? '' : `${mv > 0 ? '+' : ''}${mv.toFixed(1)}% since entry`}</td></tr>); })}</tbody></table>
            ) : <p className="sub">No instruments selected yet.</p>}
          </article>
          <article className="dcard">
            <h3>Research</h3>
            {syn ? (<>
              <p><span className={`pill ${syn.overall === 'supports the thesis' ? 'green' : syn.overall === 'mixed' ? 'orange' : 'red'}`}>{syn.overall[0].toUpperCase() + syn.overall.slice(1)}</span> <span className="sub num">confidence {Math.round(syn.confidence * 100)}%</span></p>
              <p>{syn.headline.replace(/\s*\[?\bE\d+(?:\s*[,–-]\s*E\d+)*\]?/g, '')}</p>
              <p className="sub">{deep?.plan?.hypotheses.length} hypotheses tested · {Object.keys(deep?.evidence ?? {}).length} pieces of evidence · {deep?.verification ? `${deep.verification.stats.figures_traced} of ${deep.verification.stats.figures_checked} figures checked` : ''}</p>
            </>) : deep ? <p className="sub">Deep research is running…</p> : idea.research ? <p className="sub">Single-pass research note (before deep research).</p> : <p className="sub">Not researched yet.</p>}
            {idea.research && <button type="button" className="link-btn" onClick={onOpen}>Open the full report</button>}
          </article>
          <article className="dcard">
            <h3>Risk</h3>
            {idea.fit ? (<>
              <p><b className="num">{idea.fit.te_bp.idea.toFixed(0)} bp</b> <span className="sub">tracking error on its own</span></p>
              <p><b className="num">{idea.fit.budget_used_pct.after.toFixed(0)}%</b> <span className="sub">of the risk budget in use with it</span></p>
            </>) : <p className="sub">Not measured yet.</p>}
            {idea.stress && <p><b className="num">{fmt.bp(idea.stress.worst.active_bp)}</b> <span className="sub">in the worst scenario ({idea.stress.worst.name})</span></p>}
          </article>
          <article className="dcard">
            <h3>Decision</h3>
            {idea.committee?.decision ? (<>
              <p><span className={`pill ${idea.committee.decision.decision === 'approve' ? 'green' : idea.committee.decision.decision === 'reject' ? 'red' : 'orange'}`}>{idea.committee.decision.decision === 'approve' ? 'Approved' : idea.committee.decision.decision === 'reject' ? 'Rejected' : 'Deferred'}</span> <span className="sub">{idea.committee.decision.by}</span></p>
              <p className="sub">{idea.committee.decision.rationale}</p>
              {idea.committee.risk_signoff && <p className="sub">Risk: {idea.committee.risk_signoff.opinion}. {idea.committee.risk_signoff.comment}</p>}
            </>) : idea.committee ? <p className="sub">Pack prepared; waiting for Risk sign-off and the decision.</p> : <p className="sub">Not at committee yet.</p>}
          </article>
          {h && (
            <article className="dcard wide">
              <h3>Monitoring</h3>
              <p><b className={`num ${h.score < 60 ? 'worse' : h.score < 85 ? 'warn' : 'better'}`}>{h.score}</b> <span className="sub">thesis health · {fmt.bp(h.active_bp)} active return since entry</span></p>
              <ul className="checks-mini">{h.checks.map((c) => <li key={c.name}><span className={`dot ${c.status}`} />{c.name}<span className="sub num"> {c.value}</span></li>)}</ul>
            </article>
          )}
        </div>
      </div>
    </section>
  );
}
