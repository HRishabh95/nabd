import { useEffect, useRef, useState } from 'react';
import { register, subscribe } from '../lib/stream';

const EVENTS = ['agent.tool.start', 'agent.tool.result', 'agent.text.delta', 'job.progress', 'job.done', 'job.failed'];
const TOOL_LABEL: Record<string, string> = {
  price_stats: 'Price history', macro_betas: 'Macro sensitivities', ml_rank: 'Ranking model', news_search: 'Headlines',
  news_theme: 'News theme', filings: 'SEC filings', search_memory: 'Nabd memory', market_regime: 'Market regime',
};

type Line = { id: string; text: string; ok?: boolean };

// Live view of what Nabd is doing for an idea: each tool call as it happens, then the structured answer streaming in.
export default function AgentTrace({ ideaId, step, title }: { ideaId: string; step: string; title: string }) {
  const [lines, setLines] = useState<Line[]>([]);
  const [chars, setChars] = useState(0);
  const [status, setStatus] = useState<string>('Starting');
  const box = useRef<HTMLOListElement>(null);

  useEffect(() => {
    register(...EVENTS);
    const mine = (d: Record<string, unknown>) => d.idea_id === ideaId && (d.step === step || d.step === undefined);
    const offs = [
      subscribe('agent.tool.start', (e) => {
        if (!mine(e.data)) return;
        const args = Object.values((e.data.args as Record<string, unknown>) ?? {}).join(', ');
        setLines((l) => [...l, { id: String(e.data.call_id), text: `${TOOL_LABEL[String(e.data.tool)] ?? e.data.tool}${args ? ` · ${args}` : ''}` }]);
        setStatus('Gathering evidence');
      }),
      subscribe('agent.tool.result', (e) => {
        if (!mine(e.data)) return;
        setLines((l) => l.map((x) => (x.id === String(e.data.call_id) ? { ...x, ok: Boolean(e.data.ok) } : x)));
      }),
      subscribe('agent.text.delta', (e) => {
        if (!mine(e.data)) return;
        setChars((c) => c + String(e.data.delta ?? '').length);
        setStatus('Writing');
      }),
      subscribe('job.progress', (e) => {
        const p = e.data.params as { idea_id?: string } | undefined;
        if (p?.idea_id === ideaId && e.data.message) setStatus(String(e.data.message));
      }),
    ];
    return () => offs.forEach((f) => f());
  }, [ideaId, step]);

  useEffect(() => { box.current?.scrollTo({ top: box.current.scrollHeight }); }, [lines.length]);

  return (
    <div className="trace-live" aria-live="polite">
      <div className="trace-head"><span className="spinner" aria-hidden="true" /><strong>{title}</strong><span className="sub">{status}{chars ? ` · ${chars.toLocaleString('en-GB')} characters` : ''}</span></div>
      <ol className="trace-lines scroll" ref={box}>
        {!lines.length && <li className="sub">Nabd’s tools only; every figure will come from a tool result.</li>}
        {lines.map((l) => <li key={l.id}><span className={`tick ${l.ok === undefined ? 'run' : l.ok ? 'ok' : 'bad'}`} aria-hidden="true" />{l.text}</li>)}
      </ol>
    </div>
  );
}
