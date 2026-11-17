// Idea, screening and research stages.
import { useCallback, useEffect, useMemo, useState } from 'react';
import { api } from '../../lib/api';
import { type Action, type Candidate, type EvidenceItem, type Idea, type Point, type ScreenView } from '../../lib/invest';
import { useEvent } from '../../lib/stream';

export function ThesisCard({ idea, compact = false }: { idea: Idea; compact?: boolean }) {
  const t = idea.thesis;
  const [more, setMore] = useState(!compact);
  if (!t) return null;
  return (
    <section className={`panel thesis ${compact ? 'compact' : ''}`}>
      <div className="panel-head">
        <h3>{t.title}</h3>
        <span className="pill tint">{t.direction === 'overweight' ? 'Overweight' : 'Underweight'} · {t.horizon === 'tactical' ? 'Tactical' : 'Strategic'} · {t.committee}</span>
      </div>
      <p className="lead">{t.summary}</p>
      <div className="chips-inline">
        {t.themes.map((x) => <span key={x} className="chip">{x}</span>)}
        {t.sectors.map((x) => <span key={x} className="chip alt">{x}</span>)}
        {t.regions.map((x) => <span key={x} className="chip alt">{x}</span>)}
        <span className="chip alt">{t.tranche}</span>
        {compact && <button type="button" className="link-btn" onClick={() => setMore((m) => !m)} aria-expanded={more}>{more ? 'Hide drivers and triggers' : 'Show drivers and triggers'}</button>}
      </div>
      {more && <div className="two">
        <div><h4>Depends on</h4><ul className="bul">{t.drivers.map((d) => <li key={d}>{d}</li>)}</ul></div>
        <div><h4>Would prove it wrong</h4><ul className="bul">{t.invalidation.map((d) => (
          <li key={d.label}>{d.label}{d.series && <span className="watch"> Watched: {d.series} {d.op} {d.value}</span>}</li>
        ))}</ul></div>
      </div>}
      {more && !!idea.memory_hits?.length && (
        <div className="memory"><h4>Nabd remembers</h4>
          {idea.memory_hits.slice(0, 3).map((m) => (
            <p key={m.idea_id + m.kind} className="sub"><strong>{m.idea_id}</strong> {m.title} · {m.decision ?? m.stage} · {m.when}{m.seeded ? ' · example record' : ''}</p>
          ))}
        </div>
      )}
    </section>
  );
}


const GROUP: Record<Action, { title: string; help: (label: string, bearish: boolean) => string }> = {
  hold_less: { title: 'Hold less of', help: (l) => `Things we own that fall when ${l} fall. A cut can only take a holding down to zero; the portfolio never shorts.` },
  protect: { title: 'Add as protection', help: (l, bear) => bear ? `Should hold up if ${l} fall. The badge shows whether they actually did on the worst days.` : 'Cushions the portfolio if the idea goes wrong.' },
  buy: { title: 'Buy', help: (l, bear) => bear ? 'Ways to put money to work that should hold up if the idea is right.' : `Direct ways to own ${l}.` },
  study: { title: 'Study first', help: () => 'What the idea is about. Send them to research to test the idea; nothing is traded.' },
};
const signed = (v: number) => `${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(v).toFixed(1)}%`;

function Facts({ c, label }: { c: Candidate; label: string }) {
  const held = c.held_direct_pct + (c.held_indirect_pct ?? 0);
  return (
    <ul className="sv-facts">
      {c.moves_with_driver != null && <li>Moves <b className="num">{(Math.abs(c.moves_with_driver) < 0.05 ? 0 : c.moves_with_driver).toFixed(1)}×</b> with {label}</li>}
      {c.on_worst_days_pct != null && <li>On their worst days <b className={`num ${c.on_worst_days_pct > 0 ? 'better' : 'worse'}`}>{signed(c.on_worst_days_pct)}</b></li>}
      {held > 0 && <li>We hold <b className="num">{held.toFixed(2)}%</b>{c.held_indirect_pct ? ' through the index funds' : ''}</li>}
      {c.risk_per_1pct_bp != null && <li>Adds <b className="num">{c.risk_per_1pct_bp.toFixed(0)} bp</b> of risk per 1%</li>}
    </ul>
  );
}

type Preview = { trades: { symbol: string; name: string; weight_pct: number }[]; research_only: { symbol: string; name: string }[]; funding: string;
  by_class: { name: string; before_pct: number; after_pct: number }[]; lines: { symbol: string; name: string; before_pct: number; after_pct: number }[];
  driver: { label: string; before_pct: number; after_pct: number } | null;
  risk: { te_bp_after: number; budget_used_before_pct: number; budget_used_after_pct: number; budget_bp: number } | null; warnings: string[] };

/** Before research starts: what will be traded, what is only studied, and what it does to the portfolio. */
function ReviewSheet({ p, busy, onBack, onStart }: { p: Preview; busy: boolean; onBack: () => void; onStart: () => void }) {
  const d = (a: number, b: number) => { const x = b - a; return Math.abs(x) < 0.005 ? 'no change' : `${x > 0 ? '+' : '−'}${Math.abs(x).toFixed(2)}`; };
  return (
    <div className="rv" role="dialog" aria-label="Review before research">
      <div className="rv-head"><h4>Before research starts</h4><button type="button" className="link-btn" onClick={onBack}>Back to the list</button></div>
      {p.warnings.map((w) => <p key={w} className="rv-warn">{w}</p>)}
      <div className="rv-cols">
        <div>
          <h5>To trade</h5>
          {p.trades.length ? <ul>{p.trades.map((t) => <li key={t.symbol}><b>{t.weight_pct < 0 ? 'Cut' : 'Add'} {Math.abs(t.weight_pct).toFixed(2)}%</b> {t.name}</li>)}</ul> : <p className="sub">Nothing.</p>}
          {!!p.research_only.length && <><h5>Research only</h5><p className="sub">{p.research_only.map((r) => r.name).join(' · ')}</p></>}
        </div>
        <div>
          <h5>Your portfolio</h5>
          <table className="rv-split"><thead><tr><th /><th className="r">Now</th><th className="r">After</th><th className="r">Change</th></tr></thead>
            <tbody>{p.by_class.map((c) => <tr key={c.name} className={Math.abs(c.after_pct - c.before_pct) >= 0.005 ? 'moved' : ''}><td>{c.name}</td><td className="r num">{c.before_pct.toFixed(2)}%</td><td className="r num">{c.after_pct.toFixed(2)}%</td><td className="r num">{d(c.before_pct, c.after_pct)}</td></tr>)}</tbody></table>
          {p.driver && <p className="sub">Moves like {p.driver.label}: <b className="num">{p.driver.before_pct.toFixed(2)}%</b> now, <b className="num">{p.driver.after_pct.toFixed(2)}%</b> after.</p>}
          {p.risk && <p className="sub">Risk budget used: <b className="num">{p.risk.budget_used_before_pct.toFixed(0)}%</b> now, <b className="num">{p.risk.budget_used_after_pct.toFixed(0)}%</b> after (of {p.risk.budget_bp.toFixed(0)} bp).</p>}
        </div>
      </div>
      <div className="rv-foot">
        <span className="sub">Deep research takes about 5 to 10 minutes and runs in the background. It will also propose how to split the selection.</span>
        <button className="btn small" type="button" onClick={onBack}>Change the selection</button>
        <button className="btn filled small" type="button" onClick={onStart} disabled={busy}>{busy ? 'Starting…' : 'Start deep research'}</button>
      </div>
    </div>
  );
}

export function ScreeningPanel({ idea, onDone }: { idea: Idea; onDone: () => void }) {
  const [data, setData] = useState<ScreenView | null>(null);
  const [pick, setPick] = useState<Record<string, number>>({}); // % of portfolio; negative = hold less
  const [research, setResearch] = useState<Set<string>>(new Set()); // to study without trading
  const [funding, setFunding] = useState<'equity' | 'cash' | 'mandate'>('equity');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [review, setReview] = useState<Preview | null>(null);

  const load = useCallback(() => {
    api.get<ScreenView>(`/api/invest/ideas/${idea.id}/screen`).then((d) => {
      setData(d);
      if (d.status === 'ready') setFunding(d.bearish ? 'cash' : 'equity');
    }, (e) => setErr((e as Error).message));
  }, [idea.id]);
  useEffect(() => { load(); }, [load]);
  useEvent('job.done', (e) => { if (e.data.kind === 'propose' && (e.data.params as { idea_id?: string })?.idea_id === idea.id) { setPick({}); setResearch(new Set()); load(); } });
  useEvent('job.failed', (e) => { if (e.data.kind === 'propose' && (e.data.params as { idea_id?: string })?.idea_id === idea.id) setErr(String(e.data.error)); });

  const ready = data?.status === 'ready' ? data : null;
  const label = ready?.driver.label ?? 'the idea';
  const cut = useMemo(() => Object.values(pick).filter((v) => v < 0).reduce((a, b) => a + b, 0), [pick]);
  const add = useMemo(() => Object.values(pick).filter((v) => v > 0).reduce((a, b) => a + b, 0), [pick]);
  const studyOnly = [...research].filter((s) => pick[s] === undefined);
  const n = Object.keys(pick).length + studyOnly.length;
  const trade = (c: Candidate) => setPick((p) => {
    const x = { ...p };
    if (x[c.symbol] !== undefined) delete x[c.symbol];
    else x[c.symbol] = c.action === 'hold_less' ? -Math.min(c.max_cut_pct, c.max_cut_pct >= 2 ? 1 : 0.1) : c.action === 'protect' ? 0.5 : c.kind === 'etf' ? 0.8 : 0.3;
    return x;
  });
  const study = (s: string) => setResearch((r) => { const x = new Set(r); if (x.has(s)) x.delete(s); else x.add(s); return x; });

  const items = () => [...Object.entries(pick).map(([symbol, weight_pct]) => ({ symbol, weight_pct })), ...studyOnly.map((symbol) => ({ symbol, research_only: true }))];
  async function check() {  // first show what the selection does to the portfolio; research starts only on confirm
    setBusy(true); setErr(null);
    try { setReview(await api.post<Preview>(`/api/invest/ideas/${idea.id}/preview`, { items: items(), funding })); }
    catch (e) { setErr((e as Error).message); }
    finally { setBusy(false); }
  }
  async function submit() {
    setBusy(true); setErr(null);
    try {
      await api.post(`/api/invest/ideas/${idea.id}/basket`, { items: items(), funding });
      onDone();
    } catch (e) { setErr((e as Error).message); setBusy(false); }
  }
  async function again() { setData({ status: 'proposing', job_id: '' }); setPick({}); setResearch(new Set()); try { await api.post(`/api/invest/ideas/${idea.id}/propose`); } catch (e) { setErr((e as Error).message); } }

  return (
    <section className="panel grow-panel screening sv">
      <div className="panel-head">
        <div>
          <h3>What to look at</h3>
          <p className="sub">{ready ? <>Nabd read this idea as a bet on <b>{label}</b>. {ready.driver.if_right}</> : 'Nabd is reading the idea and choosing what to look at. This takes about half a minute.'}</p>
        </div>
        <div className="head-ctl">
          {ready && <button className="btn small" type="button" onClick={again} title="Ask Nabd to propose again">Propose again</button>}
          <button className="btn filled small" type="button" disabled={!n || busy || !ready} onClick={check}>
            {busy ? 'Checking…' : n ? `Review ${n} and start research` : 'Pick what to research'}
          </button>
        </div>
      </div>
      {err && <p className="note worse">{err}</p>}
      {review && <ReviewSheet p={review} busy={busy} onBack={() => setReview(null)} onStart={submit} />}
      {!ready && !err && <div className="sv-wait"><span className="spinner" aria-hidden="true" /> Working out what this idea is really a bet on, then measuring every suggestion against the data.</div>}
      {ready && (
        <div className="scroll sv-body">
          <div className="sv-today">
            <p>Today about <b className="num">{ready.exposure_pct.toFixed(1)}%</b> of the portfolio moves like {label}
              {ready.worst_day_avg_pct != null && <>. On their {ready.worst_days} worst days they fell <b className="num">{Math.abs(ready.worst_day_avg_pct).toFixed(1)}%</b> on average</>}.</p>
            <p className="sub">We hold: {ready.holdings.map((h) => `${h.symbol} ${h.weight_pct.toFixed(1)}%`).join(' · ')}</p>
            {ready.source === 'rules' && <p className="sub warn">The assistant was unavailable, so this is a rules-based shortlist. Use “Propose again” when it is back.</p>}
          </div>
          {ready.groups.map((g) => (
            <div key={g.action} className={`sv-group ${g.action}`}>
              <div className="sv-group-head"><h4>{GROUP[g.action].title}</h4><p className="sub">{GROUP[g.action].help(label, ready.bearish)}</p></div>
              <ul className="sv-list">
                {g.items.map((c) => {
                  const on = pick[c.symbol] !== undefined, rs = research.has(c.symbol) || on;
                  return (
                    <li key={c.symbol} className={on ? 'on' : rs ? 'rs' : ''}>
                      <div className="sv-top">
                        {g.action !== 'study' && <input type="checkbox" checked={on} disabled={!c.tradable} onChange={() => trade(c)}
                          aria-label={`${GROUP[g.action].title} ${c.name}`} title={c.tradable ? undefined : c.note ?? undefined} />}
                        <div className="sv-name"><strong>{c.name}</strong><span className="sub">{c.symbol}{c.kind === 'etf' ? ' · index fund' : ''}{c.asset !== 'equity' ? ` · ${c.asset}` : ''}</span></div>
                        {c.check.agrees != null && <span className={`sv-check ${c.check.agrees ? 'ok' : 'no'}`} title={c.check.text}>{c.check.agrees ? 'Data agrees' : 'Data disagrees'}</span>}
                        {on && <label className="sv-amt"><span>{c.action === 'hold_less' ? 'Cut' : 'Add'}</span>
                          <input className="wt num" type="number" step={0.05} min={0.01} max={c.action === 'hold_less' ? c.max_cut_pct : 10} value={Math.abs(pick[c.symbol])}
                            onChange={(e) => { const v = Math.abs(Number(e.target.value)); setPick((p) => ({ ...p, [c.symbol]: c.action === 'hold_less' ? -Math.min(c.max_cut_pct, v) : v })); }}
                            aria-label={`Amount for ${c.symbol}, % of portfolio`} /><span>%</span></label>}
                        <button type="button" className={`rs-btn ${rs ? 'on' : ''}`} aria-pressed={rs} disabled={on} onClick={() => study(c.symbol)}
                          title={on ? 'Lines you trade are always researched' : 'Research it without trading'}>{rs ? 'In research' : 'Research'}</button>
                      </div>
                      <p className="sv-reason">{c.reason}</p>
                      <Facts c={c} label={label} />
                      {c.check.agrees === false && <p className="sv-warn">{c.check.text}: the data does not support this suggestion.</p>}
                      {c.note && <p className="sub">{c.note}</p>}
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
        </div>
      )}
      {ready && (
        <div className="sv-foot">
          <span className="sub">{n ? <>{cut < 0 && <>Hold less: <b className="num">{Math.abs(cut).toFixed(2)}%</b>. </>}{add > 0 && <>Add: <b className="num">{add.toFixed(2)}%</b>. </>}{studyOnly.length ? `${studyOnly.length} to research only.` : ''}</> : 'Tick what to trade, or press Research to study something first.'}</span>
          {cut < 0 && add + cut < 0 && <div className="segmented" role="group" aria-label="Where the money from cuts goes">
            <button type="button" aria-pressed={funding === 'cash'} onClick={() => setFunding('cash')}>Money to T-bills</button>
            <button type="button" aria-pressed={funding === 'mandate'} onClick={() => setFunding('mandate')}>Keep in equities</button>
          </div>}
          {add + cut > 0 && <div className="segmented" role="group" aria-label="Where the money for buys comes from">
            <button type="button" aria-pressed={funding === 'equity'} onClick={() => setFunding('equity')}>Pay from equities</button>
            <button type="button" aria-pressed={funding === 'cash'} onClick={() => setFunding('cash')}>Pay from cash</button>
          </div>}
        </div>
      )}
    </section>
  );
}

function EvidenceChips({ ids, evidence, onOpen }: { ids: string[]; evidence: Record<string, EvidenceItem>; onOpen: (e: EvidenceItem) => void }) {
  return <>{ids.filter((i) => evidence[i]).map((i) => <button key={i} type="button" className="ev" onClick={() => onOpen(evidence[i])}>{i}</button>)}</>;
}

// Inline references such as "[E3, E24]" in the model's text become clickable chips.
function Cited({ text, evidence, onOpen }: { text: string; evidence: Record<string, EvidenceItem>; onOpen: (e: EvidenceItem) => void }) {
  const parts = text.split(/(\[E\d+(?:\s*,\s*E\d+)*\])/g);
  return <>{parts.map((part, i) => /^\[E\d+/.test(part)
    ? <EvidenceChips key={i} ids={part.slice(1, -1).split(/\s*,\s*/)} evidence={evidence} onOpen={onOpen} />
    : <span key={i}>{part}</span>)}</>;
}

function Points({ items, evidence, onOpen }: { items: Point[]; evidence: Record<string, EvidenceItem>; onOpen: (e: EvidenceItem) => void }) {
  return <ul className="points">{items.map((p, k) => {
    const inline = new Set(p.text.match(/E\d+/g) ?? []);
    return <li key={k}><Cited text={p.text} evidence={evidence} onOpen={onOpen} /> <EvidenceChips ids={p.evidence.filter((e) => !inline.has(e))} evidence={evidence} onOpen={onOpen} /></li>;
  })}</ul>;
}

export function ResearchPanel({ idea }: { idea: Idea }) {
  const r = idea.research?.kind === 'deep' ? null : idea.research;
  const [open, setOpen] = useState<EvidenceItem | null>(null);
  if (!r) return null;
  const n = r.note;
  const stance = { supports: ['green', 'Supports'], mixed: ['orange', 'Mixed'], against: ['red', 'Against'] } as const;
  return (
    <section className="panel grow-panel research">
      <div className="panel-head"><div><h3>Research note</h3><p className="sub">{Object.keys(r.evidence).length} pieces of evidence from Nabd’s tools · {r.model} · {r.seconds} s · select an E-number to see the computation</p></div></div>
      <div className="research-body">
        <div className="scroll research-text">
          <p className="lead"><Cited text={n.summary} evidence={r.evidence} onOpen={setOpen} /></p>
          {n.instruments.map((v) => (
            <div key={v.symbol} className="inst"><h4>{v.symbol} <span className={`pill ${stance[v.stance][0]}`}>{stance[v.stance][1]}</span></h4>
              <Points items={v.points} evidence={r.evidence} onOpen={setOpen} /></div>
          ))}
          {!!n.news_read.length && <><h4>What the news says</h4><Points items={n.news_read} evidence={r.evidence} onOpen={setOpen} /></>}
          {!!n.risks.length && <><h4>Risks</h4><Points items={n.risks} evidence={r.evidence} onOpen={setOpen} /></>}
          {!!n.past_ideas.length && <><h4>From Nabd’s memory</h4><Points items={n.past_ideas} evidence={r.evidence} onOpen={setOpen} /></>}
          {!!n.answers.length && <><h4>Answers to the thesis questions</h4><Points items={n.answers} evidence={r.evidence} onOpen={setOpen} /></>}
        </div>
        <aside className="evidence-pane scroll" aria-live="polite">
          {open ? (
            <>
              <div className="panel-head"><h4>{open.id} · {open.tool}</h4><button className="btn small" type="button" onClick={() => setOpen(null)}>Close</button></div>
              <p className="sub">Arguments: {JSON.stringify(open.args)}</p>
              <pre className="json">{JSON.stringify(open.result, null, 1)}</pre>
            </>
          ) : (
            <><h4>Evidence</h4><ul className="ev-list">{Object.values(r.evidence).map((e) => (
              <li key={e.id}><button type="button" className="ev" onClick={() => setOpen(e)}>{e.id}</button> {e.tool} <span className="sub">{Object.values(e.args).join(', ')}</span></li>
            ))}</ul></>
          )}
        </aside>
      </div>
    </section>
  );
}
