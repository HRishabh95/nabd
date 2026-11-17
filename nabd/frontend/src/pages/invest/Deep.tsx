// Deep research: the live view while it runs in the background, and the verified report.
import { useEffect, useState } from 'react';
import { api } from '../../lib/api';
import { register, subscribe } from '../../lib/stream';
import type { Deep, DeepPoint, EvidenceItem, Idea, Verdict } from '../../lib/invest';

const STAGES = [['plan', 'Plan'], ['investigate', 'Investigate'], ['challenge', 'Red team'], ['verify', 'Verify'], ['synthesise', 'Report']] as const;
const VERDICT: Record<Verdict, [string, string]> = { supported: ['green', 'Supported'], refuted: ['red', 'Refuted'], inconclusive: ['orange', 'Inconclusive'] };
const TOOL: Record<string, string> = {
  event_study: 'Event study', conditional_returns: 'Conditional returns', analogs: 'Macro analogs', rolling_beta: 'Beta stability',
  relative_performance: 'Relative performance', macro_snapshot: 'Macro series', documents: 'Central-bank documents',
  web_search: 'Web search (official sources)', price_stats: 'Price history', macro_betas: 'Macro sensitivities', ml_rank: 'Ranking model',
  news_search: 'Headlines', news_theme: 'News theme', filings: 'SEC filings', search_memory: 'Nabd memory', market_regime: 'Market regime',
};

function mins(s: number) { const m = Math.floor(s / 60); return `${m}:${String(Math.floor(s % 60)).padStart(2, '0')}`; }

// ---------------------------------------------------------------- live
/** Long links break the layout and say little: show them as "sec.gov › d291965dex991.htm". */
function shortLinks(text: string): string {
  return text.replace(/https?:\/\/[^\s]+/g, (u) => {
    try {
      const url = new URL(u);
      const last = url.pathname.split('/').filter(Boolean).pop() ?? '';
      return `${url.hostname.replace(/^www\./, '')}${last ? ` › ${last.length > 28 ? `${last.slice(0, 27)}…` : last}` : ''}`;
    } catch { return u; }
  });
}

export function DeepLive({ idea }: { idea: Idea }) {
  const d = (idea.research?.kind === 'deep' ? idea.research : null) as Deep | null;
  const [last, setLast] = useState<Record<string, string>>({});
  const [calls, setCalls] = useState<Record<string, number>>({});
  const [now, setNow] = useState(Date.now() / 1000);
  useEffect(() => {
    register('agent.tool.start');
    const off = subscribe('agent.tool.start', (e) => {
      if (e.data.idea_id !== idea.id) return;
      const step = String(e.data.step);
      const args = Object.values((e.data.args as Record<string, unknown>) ?? {}).map((v) => (Array.isArray(v) ? v.join(', ') : shortLinks(String(v)))).join(' · ');
      setLast((l) => ({ ...l, [step]: `${TOOL[String(e.data.tool)] ?? e.data.tool}${args ? ` · ${args}` : ''}` }));
      setCalls((c) => ({ ...c, [step]: (c[step] ?? 0) + 1 }));
    });
    const t = setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => { off(); clearInterval(t); };
  }, [idea.id]);
  const stage = d?.stage ?? 'plan';
  const si = STAGES.findIndex(([k]) => k === stage);
  const n = (step: string) => Math.max(calls[step] ?? 0, d?.calls?.[step] ?? 0);
  return (
    <section className="panel grow-panel deep-live">
      <div className="panel-head">
        <div><h3><span className="spinner" aria-hidden="true" /> Deep research running in the background</h3>
          <p className="sub">You can leave this page; Nabd keeps working and alerts you when the report is ready{d?.as_of ? ` · as of ${d.as_of}` : ''}{d?.web ? ' · web search limited to official sources' : ''}</p></div>
        <span className="num sub">{d ? mins(now - d.started) : '0:00'}</span>
      </div>
      <ol className="deep-stages">{STAGES.map(([k, label], i) => <li key={k} className={i < si ? 'done' : i === si ? 'now' : ''}>{label}</li>)}</ol>
      <div className="scroll">
        {d?.plan && <p className="lead">{d.plan.framing}</p>}
        <div className="hyp-grid">
          {(d?.plan?.hypotheses ?? []).map((h) => {
            const f = d?.findings?.[h.id];
            return (
              <article key={h.id} className={`hyp ${f ? 'done' : n(h.id) ? 'run' : ''}`}>
                <div className="hyp-head"><strong>{h.id}</strong>
                  {f ? <span className={`pill ${VERDICT[f.verdict][0]}`}>{VERDICT[f.verdict][1]} · {Math.round(f.confidence * 100)}%</span>
                    : n(h.id) ? <span className="pill tint">Investigating · {n(h.id)} tools</span> : <span className="pill">Queued</span>}</div>
                <p>{h.statement}</p>
                {f ? <p className="sub clamp">{f.summary.replace(/\s*\[?E\d+(?:\s*,\s*E\d+)*\]?/g, '')}</p> : <p className="sub mono">{last[h.id] ?? h.test}</p>}
              </article>
            );
          })}
          {si >= 2 && (
            <article className={`hyp ${d?.red_team ? 'done' : 'run'}`}>
              <div className="hyp-head"><strong>Red team</strong><span className={`pill ${d?.red_team ? 'red' : 'tint'}`}>{d?.red_team ? 'Bear case ready' : `Arguing against · ${n('red_team')} tools`}</span></div>
              {d?.red_team ? <p className="sub clamp">{d.red_team.bear_case}</p> : <p className="sub mono">{last.red_team ?? 'Building the strongest case against the idea'}</p>}
            </article>
          )}
          {si >= 3 && (
            <article className={`hyp ${d?.verification ? 'done' : 'run'}`}>
              <div className="hyp-head"><strong>Verification</strong><span className="pill tint">{d?.verification ? `${d.verification.stats.supported} of ${d.verification.stats.claims} claims supported` : 'Checking every claim and figure'}</span></div>
              <p className="sub">Each figure must appear in its cited evidence; an independent checker judges each claim.</p>
            </article>
          )}
        </div>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------- charts for evidence
function Line({ xs, ys, lo, hi, zero = true, label }: { xs: (string | number)[]; ys: (number | null)[]; lo?: (number | null)[]; hi?: (number | null)[]; zero?: boolean; label: string }) {
  const W = 300, H = 120, P = 4;
  const all = [...ys, ...(lo ?? []), ...(hi ?? []), ...(zero ? [0] : [])].filter((v): v is number => v != null);
  const mn = Math.min(...all), mx = Math.max(...all), r = mx - mn || 1;
  const x = (i: number) => P + (i / Math.max(1, xs.length - 1)) * (W - 2 * P);
  const y = (v: number) => H - P - ((v - mn) / r) * (H - 2 * P);
  const path = (vs: (number | null)[]) => vs.map((v, i) => (v == null ? '' : `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`)).join('');
  const band = lo && hi ? `${path(hi)}${lo.map((v, i) => (v == null ? '' : `L${x(lo.length - 1 - i).toFixed(1)},${y(lo[lo.length - 1 - i] ?? 0).toFixed(1)}`)).join('')}Z` : '';
  return (
    <figure className="ev-chart">
      <svg viewBox={`0 0 ${W} ${H + 14}`} role="img" aria-label={label}>
        {band && <path d={band} className="band" />}
        {zero && mn < 0 && mx > 0 && <line x1={P} x2={W - P} y1={y(0)} y2={y(0)} className="zero" />}
        <path d={path(ys)} className="line" />
        <text x={P} y={H + 12}>{String(xs[0])}</text><text x={W - P} y={H + 12} textAnchor="end">{String(xs[xs.length - 1])}</text>
        <text x={W - P} y={10} textAnchor="end">{mx.toFixed(1)}</text><text x={W - P} y={H - 2} textAnchor="end">{mn.toFixed(1)}</text>
      </svg>
      <figcaption className="sub">{label}</figcaption>
    </figure>
  );
}

export function EvidenceDetail({ e }: { e: EvidenceItem }) {
  const r = e.result as Record<string, unknown> & { chart?: Record<string, unknown[]> };
  const c = r && typeof r === 'object' ? r.chart : undefined;
  let chart = null;
  if (c && e.tool === 'event_study') chart = <Line xs={c.days as number[]} ys={c.mean as number[]} lo={c.lo as number[]} hi={c.hi as number[]} label="Mean market-adjusted return around events, %, with 95% band (day 0 = event)" />;
  if (c && e.tool === 'rolling_beta') chart = <Line xs={c.months as string[]} ys={c.beta as number[]} label="Rolling beta, monthly" />;
  if (c && e.tool === 'relative_performance') chart = <Line xs={c.dates as string[]} ys={c.rel_index as number[]} zero={false} label="Basket against funding leg, index = 100" />;
  if (c && e.tool === 'conditional_returns') chart = (
    <figure className="ev-chart"><ul className="bars">{(c.labels as string[]).map((l, i) => {
      const v = (c.values as number[])[i] ?? 0, m = Math.max(...(c.values as number[]).map(Math.abs), 0.01);
      return <li key={l}><span>{l}</span><span className="bar"><i className={v < 0 ? 'neg-red' : ''} style={{ width: `${Math.abs(v) / m * 100}%` }} /></span><span className="num">{v.toFixed(2)}%</span></li>;
    })}</ul><figcaption className="sub">Mean forward relative return</figcaption></figure>
  );
  const rest = r && typeof r === 'object' && !Array.isArray(r) ? Object.fromEntries(Object.entries(r).filter(([k]) => k !== 'chart')) : r;
  return (
    <>
      <p className="sub ev-args">{TOOL[e.tool] ?? e.tool} · {Object.entries(e.args).map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(', ') : shortLinks(String(v))}`).join(' · ')}</p>
      {chart}
      {e.tool === 'web_search' && Array.isArray((r as { results?: unknown[] }).results) && (
        <ul className="ev-list">{((r as { results: { title?: string; url?: string }[] }).results).map((x, i) => <li key={i}><a href={x.url} target="_blank" rel="noreferrer">{x.title ?? x.url}</a></li>)}</ul>
      )}
      <pre className="json">{JSON.stringify(rest, null, 1)}</pre>
    </>
  );
}

// ---------------------------------------------------------------- report
function Chips({ ids, ev, open }: { ids: string[]; ev: Record<string, EvidenceItem>; open: (e: EvidenceItem) => void }) {
  return <>{ids.filter((i) => ev[i]).map((i) => <button key={i} type="button" className="ev" onClick={() => open(ev[i])}>{i}</button>)}</>;
}

function Cited({ text, ev, open }: { text: string; ev: Record<string, EvidenceItem>; open: (e: EvidenceItem) => void }) {
  const parts = text.split(/(\[?\bE\d+(?:\s*[,–-]\s*E\d+)*\]?)/g);
  return <>{parts.map((p, i) => /^\[?E\d+/.test(p) ? <Chips key={i} ids={p.replace(/[[\]]/g, '').split(/\s*[,–-]\s*/)} ev={ev} open={open} /> : <span key={i}>{p}</span>)}</>;
}

function PointList({ items, ev, open }: { items: DeepPoint[]; ev: Record<string, EvidenceItem>; open: (e: EvidenceItem) => void }) {
  return <ul className="points">{items.map((p, k) => {
    const inline = new Set(p.text.match(/E\d+/g) ?? []);
    return <li key={k} className={p.check === 'partly' ? 'partly' : ''}>
      <Cited text={p.text} ev={ev} open={open} /> <Chips ids={p.evidence.filter((e) => !inline.has(e))} ev={ev} open={open} />
      {p.check === 'partly' && <span className="check-note">partly supported</span>}
    </li>;
  })}</ul>;
}

function Confidence({ v }: { v: number }) {
  return <span className="conf" title={`${Math.round(v * 100)}% confidence`}><i style={{ width: `${v * 100}%` }} /></span>;
}

/** The split research proposes for the selection, with Nabd's check of what it does to the portfolio. */
function SplitView({ idea, split, onUsed }: { idea: Idea; split: NonNullable<Deep['split']>; onUsed: () => void }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const c = split.check;
  const size = (w: number) => (w ? `${w < 0 ? 'Cut' : 'Add'} ${Math.abs(w).toFixed(2)}%` : 'Leave out');
  async function use() {
    setBusy(true); setErr(null);
    try { await api.post(`/api/invest/ideas/${idea.id}/use-split`); onUsed(); } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  }
  return (
    <div className="split-view">
      <div className="split-head"><h4>Proposed split</h4>
        <button className="btn small filled" type="button" disabled={busy} onClick={use}>{busy ? 'Applying…' : 'Use this split'}</button></div>
      <p className="sub">Proposed by the research from its verified findings; the limits are enforced and the effect computed by Nabd. Using it replaces the selection and reruns portfolio fit.</p>
      <ul className="split-lines">{split.lines.map((l) => (
        <li key={l.symbol}><b className="num">{size(l.weight_pct)}</b><span><strong>{l.name}</strong> <span className="sub">({l.symbol}) · selected: {l.research_only_before ? 'research only' : size(l.selected_pct)}</span></span><span className="sub">{l.why}</span></li>
      ))}</ul>
      {!!split.notes.length && <p className="sub warn">Nabd adjusted: {split.notes.join('; ')}.</p>}
      {c && <div className="split-check">
        {c.warnings.map((w) => <p key={w} className="rv-warn">{w}</p>)}
        <table className="rv-split"><thead><tr><th /><th className="r">Now</th><th className="r">With this split</th></tr></thead>
          <tbody>{c.by_class.map((x) => <tr key={x.name} className={Math.abs(x.after_pct - x.before_pct) >= 0.005 ? 'moved' : ''}><td>{x.name}</td><td className="r num">{x.before_pct.toFixed(2)}%</td><td className="r num">{x.after_pct.toFixed(2)}%</td></tr>)}</tbody></table>
        {c.driver && <p className="sub">Moves like {c.driver.label}: <b className="num">{c.driver.before_pct.toFixed(2)}%</b> now, <b className="num">{c.driver.after_pct.toFixed(2)}%</b> with this split.</p>}
        {c.risk && <p className="sub">Risk budget used: <b className="num">{c.risk.budget_used_before_pct.toFixed(0)}%</b> now, <b className="num">{c.risk.budget_used_after_pct.toFixed(0)}%</b> with this split.</p>}
      </div>}
      {err && <p className="note worse">{err}</p>}
    </div>
  );
}

export function DeepReport({ idea, onRerun }: { idea: Idea; onRerun: () => void }) {
  const d = idea.research as unknown as Deep;
  const [tab, setTab] = useState<'report' | 'hyp' | 'bear' | 'verify'>('report');
  const [open, setOpen] = useState<EvidenceItem | null>(null);
  const [asOf, setAsOf] = useState('');
  const [busy, setBusy] = useState(false);
  const s = d.synthesis!, v = d.verification?.stats;
  const ev = d.evidence;
  const removed = (d.verification?.claims ?? []).filter((c) => c.status === 'unsupported');
  const kept = (id: string, side: 'evidence_for' | 'evidence_against') => {
    const tag = side === 'evidence_for' ? 'for' : 'against';
    const st = Object.fromEntries((d.verification?.claims ?? []).map((c) => [c.id, c.status]));
    return (d.findings[id]?.[side] ?? []).map((p, i) => ({ ...p, check: st[`${id}.${tag}.${i}`] as DeepPoint['check'] })).filter((p) => p.check !== 'unsupported');
  };
  async function rerun() {
    setBusy(true);
    try { await api.post(`/api/invest/ideas/${idea.id}/research`, asOf ? { as_of: asOf, web: d.web } : { web: d.web }); onRerun(); } finally { setBusy(false); }
  }
  const overallTone = s.overall === 'supports the thesis' ? 'green' : s.overall === 'mixed' ? 'orange' : 'red';
  return (
    <section className="panel grow-panel deep">
      <div className="deep-head">
        <div className="deep-title">
          <span className="sub">Deep research{d.as_of ? ` as of ${d.as_of}` : ''} · {d.plan?.hypotheses.length} hypotheses · {Object.keys(ev).length} pieces of evidence · {v?.web_searches ?? 0} official web searches · {Math.round((d.seconds ?? 0) / 60)} min</span>
          <h3>{s.headline.replace(/\s*\[?\bE\d+(?:\s*[,–-]\s*E\d+)*\]?/g, '').replace(/\s+([.,;])/g, '$1')}</h3>
          <div className="deep-badges">
            <span className={`pill ${overallTone}`}>{s.overall[0].toUpperCase() + s.overall.slice(1)}</span>
            <span className="sub">confidence</span><Confidence v={s.confidence} /><span className="num sub">{Math.round(s.confidence * 100)}%</span>
            {v && <span className="sub verified">Verified: {v.supported + v.partly} of {v.claims} claims kept, {v.unsupported} removed · {v.figures_traced} of {v.figures_checked} figures traced to evidence</span>}
          </div>
        </div>
        <div className="head-ctl">
          <input type="date" className="date-in" value={asOf} onChange={(e) => setAsOf(e.target.value)} aria-label="Rerun as of date" />
          <button className="btn small" type="button" disabled={busy} onClick={rerun}>{asOf ? 'Rerun as of date' : 'Rerun'}</button>
        </div>
      </div>
      <div className="segmented deep-tabs" role="tablist" aria-label="Report sections">
        {([['report', 'Report'], ['hyp', `Hypotheses · ${d.plan?.hypotheses.length ?? 0}`], ['bear', 'Bear case'], ['verify', `Verification${removed.length ? ` · ${removed.length} removed` : ''}`]] as const).map(([k, l]) => (
          <button key={k} type="button" role="tab" aria-pressed={tab === k} onClick={() => setTab(k)}>{l}</button>
        ))}
      </div>
      <div className="research-body">
        <div className="scroll research-text">
          {tab === 'report' && (
            <>
              <p className="lead"><Cited text={s.summary} ev={ev} open={setOpen} /></p>
              <table className="verdicts"><tbody>{s.hypotheses.map((h) => (
                <tr key={h.id}><td><strong>{h.id}</strong></td><td><span className={`pill ${VERDICT[h.verdict][0]}`}>{VERDICT[h.verdict][1]}</span></td>
                  <td><Confidence v={h.confidence} /></td><td>{h.one_line}</td></tr>
              ))}</tbody></table>
              <h4>For the portfolio</h4><p><Cited text={s.portfolio_view} ev={ev} open={setOpen} /></p>
              {d.split && d.split.lines.length > 0 && <SplitView idea={idea} split={d.split} onUsed={onRerun} />}
              <div className="two">
                <div><h4>What would change our mind</h4><ul className="bul">{s.what_would_change_our_mind.map((x) => <li key={x}>{x}</li>)}</ul></div>
                <div><h4>Open questions</h4><ul className="bul">{s.open_questions.map((x) => <li key={x}>{x}</li>)}</ul></div>
              </div>
              {!!s.proposed_triggers.length && <><h4>Proposed monitoring triggers (added to the exit plan when the pack is prepared)</h4>
                <ul className="bul">{s.proposed_triggers.map((t) => <li key={t.label}>{t.label}{t.series && <span className="watch">{t.series} {t.op} {t.value}</span>}</li>)}</ul></>}
            </>
          )}
          {tab === 'hyp' && (d.plan?.hypotheses ?? []).map((h) => {
            const f = d.findings[h.id];
            if (!f) return null;
            return (
              <article key={h.id} className="hyp-full">
                <div className="hyp-head"><strong>{h.id}</strong><span className={`pill ${VERDICT[f.verdict][0]}`}>{VERDICT[f.verdict][1]}</span><Confidence v={f.confidence} /><span className="sub num">{f.tool_calls ?? 0} tool calls</span></div>
                <p className="hyp-statement">{h.statement}</p>
                <p className="sub">Test: {h.test}</p>
                <p className="lead"><Cited text={f.summary} ev={ev} open={setOpen} /></p>
                <div className="two">
                  <div><h4>Evidence for</h4><PointList items={kept(h.id, 'evidence_for')} ev={ev} open={setOpen} /></div>
                  <div><h4>Evidence against</h4><PointList items={kept(h.id, 'evidence_against')} ev={ev} open={setOpen} /></div>
                </div>
                {!!f.caveats.length && <p className="sub">Limits: {f.caveats.join(' · ')}</p>}
              </article>
            );
          })}
          {tab === 'bear' && d.red_team && (
            <>
              <p className="lead">{d.red_team.bear_case}</p>
              <PointList items={d.red_team.points.map((p, i) => ({ ...p, check: (d.verification?.claims.find((c) => c.id === `RT.${i}`)?.status ?? null) as DeepPoint['check'] })).filter((p) => p.check !== 'unsupported')} ev={ev} open={setOpen} />
              <h4>The idea loses money if</h4><ul className="bul">{d.red_team.breaks_if.map((x) => <li key={x}>{x}</li>)}</ul>
            </>
          )}
          {tab === 'verify' && d.verification && (
            <>
              <dl className="kv">
                <div><dt>Claims checked</dt><dd className="num">{v!.claims}</dd></div>
                <div><dt>Supported · partly · removed</dt><dd className="num">{v!.supported} · {v!.partly} · {v!.unsupported}</dd></div>
                <div><dt>Figures traced to evidence</dt><dd className="num">{v!.figures_traced} of {v!.figures_checked}</dd></div>
                <div><dt>Uncited claims linked to pages · outside allowlist</dt><dd className="num">{v!.auto_linked ?? 0} · {v!.non_official_urls.length}</dd></div>
              </dl>
              <table className="claims"><thead><tr><th>Claim</th><th>Check</th><th>Note</th></tr></thead><tbody>
                {d.verification.claims.map((c) => (
                  <tr key={c.id} className={c.status}><td><span className="sub num">{c.id}</span> {c.text}{!!c.untraced.length && <span className="check-note"> figures not in evidence: {c.untraced.join(', ')}</span>}
                    {!!c.auto_linked?.length && <span className="check-note linked"> cited nothing; linked to {c.auto_linked.join(', ')}, which contains its figures</span>}</td>
                    <td><span className={`pill ${c.status === 'supported' ? 'green' : c.status === 'partly' ? 'orange' : 'red'}`}>{c.status === 'unsupported' ? 'removed' : c.status}</span></td>
                    <td className="sub">{c.note}</td></tr>
                ))}</tbody></table>
            </>
          )}
        </div>
        <aside className="evidence-pane scroll" aria-live="polite">
          {open ? (
            <><div className="panel-head"><h4>{open.id}</h4><button className="btn small" type="button" onClick={() => setOpen(null)}>Close</button></div><EvidenceDetail e={open} /></>
          ) : (
            <><h4>Evidence · {Object.keys(ev).length}</h4><ul className="ev-list">{Object.values(ev).map((e) => (
              <li key={e.id}><button type="button" className="ev" onClick={() => setOpen(e)}>{e.id}</button> {TOOL[e.tool] ?? e.tool} <span className="sub">{Object.values(e.args).map((x) => (Array.isArray(x) ? x.join(' ') : String(x))).join(' · ').slice(0, 60)}</span></li>
            ))}</ul></>
          )}
        </aside>
      </div>
    </section>
  );
}
