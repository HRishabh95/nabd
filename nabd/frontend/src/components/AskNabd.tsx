// Ask Nabd: a sheet available on every page. Answers stream in (tools, then text); charts are built from tool data;
// every figure is traced to the evidence it cites.
import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../lib/api';
import { register, subscribe } from '../lib/stream';
import type { EvidenceItem } from '../lib/invest';
import Review from './Review';
import Chart, { type ChartSpec } from './Chart';
import { EvidenceDetail } from '../pages/invest/Deep';
import type { PageId } from './Chrome';

type Msg = { id: string; role: 'user' | 'nabd'; content: string; status: string;
  data: { charts?: ChartSpec[]; follow_ups?: string[]; check?: { figures: number; traced: number; untraced: string[] }; evidence?: Record<string, EvidenceItem>; seconds?: number; model?: string } };
type Live = { tools: string[]; text: string };

const TOOL: Record<string, string> = {
  series_data: 'Time series', portfolio_overview: 'Portfolio', ideas_list: 'Ideas', idea_detail: 'Idea detail', alerts: 'Alerts',
  stress_portfolio: 'Portfolio stress', ranker_record: 'Ranking model record', regime_history: 'Regime history', calc: 'Calculation',
  event_study: 'Event study', conditional_returns: 'Conditional returns', analogs: 'Macro analogs', rolling_beta: 'Beta stability',
  relative_performance: 'Relative performance', macro_snapshot: 'Macro series', documents: 'Central-bank documents', read_page: 'Official page',
  web_search: 'Web search (official)', price_stats: 'Price history', macro_betas: 'Macro sensitivities', ml_rank: 'Ranking model',
  news_search: 'Headlines', news_theme: 'News theme', filings: 'SEC filings', search_memory: 'Nabd memory', market_regime: 'Market regime',
};
const SUGGEST: Record<PageId, string[]> = {
  overview: ['Why are markets moving today?', 'How has Brent moved this year?', 'What did the Fed and ECB say most recently?'],
  forecasting: ["What is Nabd's nowcast for UAE real GDP in 2026, and how does it compare with the IMF?", 'How have oil and Hormuz news moved this month?'],
  fraud: ['How did the fraud detection methods compare?', 'What does the BIS say recently about payment fraud?'],
  governance: ['Which models are in use, and how was each one tested?'],
  ask: ['How is the commodity book positioned today?', "What is Nabd's nowcast for UAE real GDP in 2026, and how does it compare with the IMF?", 'Which fraud networks look most urgent?'],
  investment: ['How much of the risk budget is in use, and where from?', 'How would the whole portfolio fare in a Hormuz closure?', 'Compare the ideas in the pipeline'],
};
const KEY = 'nabd.ask.thread';

function Text({ text, ev, open }: { text: string; ev: Record<string, EvidenceItem>; open: (id: string) => void }) {
  const blocks = text.split(/\n+/).filter((b) => b.trim());
  const render = (s: string) => s.split(/(\[?\bE\d+(?:\s*[,–-]\s*E\d+)*\]?)/g).map((p, i) => /^\[?E\d+/.test(p)
    ? <span key={i}>{p.replace(/[[\]]/g, '').split(/\s*[,–-]\s*/).filter((e) => ev[e]).map((e) => <button key={e} type="button" className="ev" onClick={() => open(e)}>{e}</button>)}</span>
    : <span key={i}>{p}</span>);
  const bullets = blocks.filter((b) => /^\s*[-•]\s/.test(b));
  return (
    <div className="ask-text">
      {blocks.map((b, i) => (/^\s*[-•]\s/.test(b) ? null : <p key={i}>{render(b)}</p>))}
      {!!bullets.length && <ul>{bullets.map((b, i) => <li key={i}>{render(b.replace(/^\s*[-•]\s/, ''))}</li>)}</ul>}
    </div>
  );
}

function Answer({ m, onAsk }: { m: Msg; onAsk: (q: string) => void }) {
  const [open, setOpen] = useState<string | null>(null);
  const ev = m.data.evidence ?? {};
  const c = m.data.check;
  if (m.status === 'failed') return <div className="ask-msg nabd"><p className="note worse">{m.content}</p></div>;
  return (
    <div className="ask-msg nabd">
      <Text text={m.content} ev={ev} open={(id) => setOpen(open === id ? null : id)} />
      {open && ev[open] && <div className="ask-ev"><div className="panel-head"><strong className="num">{open}</strong><button type="button" className="link-btn" onClick={() => setOpen(null)}>Close</button></div><EvidenceDetail e={ev[open]} /></div>}
      {(m.data.charts ?? []).map((ch, i) => <Chart key={i} c={ch} />)}
      <div className="ask-meta">
        {c && c.figures > 0 && <span className={`pill ${c.untraced.length ? 'orange' : 'green'}`} title={c.untraced.length ? `Not found in the cited evidence: ${c.untraced.join(', ')}` : 'Every figure appears in the evidence it cites'}>
          {c.traced} of {c.figures} figures traced</span>}
        <span className="sub">{Object.keys(ev).length} tool results · {m.data.seconds ?? '—'} s</span>
      </div>
      {m.id && <Review kind="ask" refId={m.id} label="Was this answer useful?" />}
      {!!m.data.follow_ups?.length && <div className="ask-follow">{m.data.follow_ups.map((q) => <button key={q} type="button" className="chip-q" onClick={() => onAsk(q)}>{q}</button>)}</div>}
    </div>
  );
}

export default function AskNabd({ open, onClose, page, embedded = false, threadId, onThread }: {
  open: boolean; onClose: () => void; page: PageId; embedded?: boolean;
  threadId?: string | null; onThread?: (id: string | null) => void;
}) {
  const [own, setOwn] = useState<string | null>(() => { try { return localStorage.getItem(KEY); } catch { return null; } });
  const controlled = threadId !== undefined;
  const thread = controlled ? threadId : own;
  const setThread = (id: string | null) => { if (controlled) onThread?.(id); else setOwn(id); };
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [live, setLive] = useState<Record<string, Live>>({});
  const [q, setQ] = useState('');
  const [ideaId, setIdeaId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const log = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);

  const load = useCallback(async (tid: string) => {
    try { const r = await api.get<{ messages: Msg[] }>(`/api/ask/threads/${tid}`); setMsgs(r.messages); }
    catch { setThread(null); setMsgs([]); }
  }, []);
  useEffect(() => { if (open && thread) load(thread); else if (open && !thread) setMsgs([]); if (open) setTimeout(() => input.current?.focus(), 50); }, [open, thread, load]);
  useEffect(() => { try { if (thread) localStorage.setItem(KEY, thread); else localStorage.removeItem(KEY); } catch { /* storage unavailable */ } }, [thread]);
  useEffect(() => {
    const f = (e: Event) => setIdeaId((e as CustomEvent).detail?.idea_id ?? null);
    addEventListener('nabd:context', f);
    return () => removeEventListener('nabd:context', f);
  }, []);
  useEffect(() => {
    register('ask.tool', 'ask.text', 'ask.done');
    const offs = [
      subscribe('ask.tool', (e) => { const id = String(e.data.message_id); const a = e.data.args as Record<string, unknown> | undefined;
        const label = `${TOOL[String(e.data.tool)] ?? e.data.tool}${a ? ` · ${Object.values(a).map((v) => (Array.isArray(v) ? v.join(' ') : String(v))).join(' · ').slice(0, 60)}` : ''}`;
        setLive((l) => ({ ...l, [id]: { tools: [...(l[id]?.tools ?? []), label], text: l[id]?.text ?? '' } })); }),
      subscribe('ask.text', (e) => { const id = String(e.data.message_id); setLive((l) => ({ ...l, [id]: { tools: l[id]?.tools ?? [], text: String(e.data.text) } })); }),
      subscribe('ask.done', (e) => { if (e.data.thread_id) load(String(e.data.thread_id)); setBusy(false); }),
    ];
    return () => offs.forEach((f) => f());
  }, [load]);
  const tail = msgs.length ? `${msgs[msgs.length - 1].id}:${msgs[msgs.length - 1].status}` : '';
  useEffect(() => {  // follow the conversation, including when an answer finishes and its chart appears
    const t = setTimeout(() => log.current?.scrollTo({ top: log.current.scrollHeight, behavior: 'smooth' }), 60);
    return () => clearTimeout(t);
  }, [tail, live]);
  useEffect(() => {
    if (!open || embedded) return;
    const k = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    addEventListener('keydown', k);
    return () => removeEventListener('keydown', k);
  }, [open, onClose]);

  async function ask(text: string) {
    const question = text.trim();
    if (!question || busy) return;
    setBusy(true); setQ('');
    const ctx = { page, idea_id: page === 'investment' ? ideaId : null };
    const r = await api.post<{ thread_id: string; question_id: string; message_id: string }>('/api/ask', { question, thread_id: thread, context: ctx });
    setThread(r.thread_id);
    setMsgs((m) => [...m, { id: r.question_id, role: 'user', content: question, status: 'done', data: {} }, { id: r.message_id, role: 'nabd', content: '', status: 'running', data: {} }]);
  }

  if (!open) return null;
  return (
    <aside className={embedded ? 'ask ask-embedded' : 'ask glass'} role={embedded ? 'region' : 'dialog'} aria-label="Ask Nabd">
      {!embedded && <header className="ask-head">
        <div><h2>Ask Nabd</h2><p className="sub">Answers from Nabd’s data, models and official sources; every figure is checked{page === 'investment' && ideaId ? ` · about ${ideaId}` : ''}</p></div>
        <div className="head-ctl">
          <a className="btn small" href="#ask" onClick={onClose}>Open full page</a>
          <button type="button" className="btn small" onClick={() => { setThread(null); setMsgs([]); }}>New thread</button>
          <button type="button" className="btn small" onClick={onClose} aria-label="Close Ask Nabd">Close</button>
        </div>
      </header>}
      <div className="ask-log scroll" ref={log} aria-live="polite">
        {!msgs.length && <p className="note">Ask about the portfolio, an idea, markets, macro or central-bank news. Nabd calls its own tools, shows each step, and draws charts from the data it computed.</p>}
        {msgs.map((m) => m.role === 'user' ? <div key={m.id} className="ask-msg user"><p>{m.content}</p></div>
          : m.status === 'running' ? (
            <div key={m.id} className="ask-msg nabd live">
              <ol className="ask-steps">{(live[m.id]?.tools ?? []).map((t, i) => <li key={i}><span className="tick ok" />{t}</li>)}{!live[m.id]?.tools?.length && <li><span className="spinner" /> Thinking</li>}</ol>
              {live[m.id]?.text && <div className="ask-text"><p>{live[m.id].text}</p></div>}
            </div>
          ) : <Answer key={m.id} m={m} onAsk={ask} />)}
      </div>
      <footer className="ask-foot">
        {!msgs.length && <div className="ask-follow">{SUGGEST[page].map((s) => <button key={s} type="button" className="chip-q" onClick={() => ask(s)}>{s}</button>)}</div>}
        <form className="ask-input" onSubmit={(e) => { e.preventDefault(); ask(q); }}>
          <textarea ref={input} rows={2} value={q} placeholder="Ask a question" aria-label="Question for Nabd"
            onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); ask(q); } }} />
          <button className="btn filled small" type="submit" disabled={busy || !q.trim()}>{busy ? 'Working…' : 'Ask'}</button>
        </form>
      </footer>
    </aside>
  );
}
