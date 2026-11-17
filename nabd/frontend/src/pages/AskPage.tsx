import { useCallback, useEffect, useState } from 'react';
import AskNabd from '../components/AskNabd';
import { PageHeader } from '../components/Chrome';
import { api } from '../lib/api';
import { subscribe } from '../lib/stream';

// Ask Nabd as a full page: conversations on the left, the chat in the middle, and who is asking on the right
// (a persona that shapes emphasis, and a memory the user controls).
type Thread = { id: string; title: string; updated: number };
type Mem = { id: string; ts: number; text: string };
type Profile = { role: string; label: string; style: string; personas: Record<string, string>; memory: Mem[] };

const ago = (t: number) => {
  const d = (Date.now() / 1000 - t) / 86400;
  return d < 1 ? 'today' : d < 2 ? 'yesterday' : new Date(t * 1000).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' });
};

export default function AskPage() {
  const [threads, setThreads] = useState<Thread[]>([]);
  const [thread, setThread] = useState<string | null>(() => { try { return localStorage.getItem('nabd.ask.thread'); } catch { return null; } });
  const [find, setFind] = useState('');
  const [prof, setProf] = useState<Profile | null>(null);
  const [mem, setMem] = useState('');

  const loadThreads = useCallback(() => api.get<{ threads: Thread[] }>('/api/ask/threads').then((r) => setThreads(r.threads), () => undefined), []);
  useEffect(() => {
    loadThreads();
    api.get<Profile>('/api/ask/profile').then(setProf, () => undefined);
    return subscribe('ask.done', () => loadThreads());
  }, [loadThreads]);
  useEffect(() => { try { if (thread) localStorage.setItem('nabd.ask.thread', thread); } catch { /* storage unavailable */ } }, [thread]);

  async function role(r: string) { setProf(await api.put<Profile>('/api/ask/profile', { role: r })); }
  async function remember(e: React.FormEvent) {
    e.preventDefault();
    if (mem.trim().length < 3) return;
    const r = await api.post<{ memory: Mem[] }>('/api/ask/memory', { text: mem.trim() });
    setProf((p) => (p ? { ...p, memory: r.memory } : p)); setMem('');
  }
  async function forget(id: string) {
    const r = await api.del<{ memory: Mem[] }>(`/api/ask/memory/${id}`);
    setProf((p) => (p ? { ...p, memory: r.memory } : p));
  }
  const shown = threads.filter((t) => !find || (t.title || '').toLowerCase().includes(find.toLowerCase()));

  return (
    <>
      <PageHeader title="Ask Nabd" lede="Questions in plain words, answered from Nabd’s data, models and official sources; every figure is traced to its source" />
      <div className="fill ap-grid">
        <nav className="card ap-side" aria-label="Conversations">
          <button className="btn filled small" type="button" onClick={() => setThread(null)}>New conversation</button>
          <input className="ap-find" value={find} onChange={(e) => setFind(e.target.value)} placeholder="Search conversations" aria-label="Search conversations" />
          <ul className="ap-threads scroll">{shown.map((t) => (
            <li key={t.id}><button type="button" aria-current={t.id === thread} onClick={() => setThread(t.id)}>
              <span className="ap-title">{t.title || 'Untitled'}</span><span className="sub">{ago(t.updated)}</span></button></li>
          ))}{!shown.length && <li className="sub">No conversations yet.</li>}</ul>
        </nav>
        <section className="card ap-chat">
          <AskNabd open onClose={() => undefined} page="ask" embedded threadId={thread} onThread={(id) => { setThread(id); loadThreads(); }} />
        </section>
        <aside className="card ap-me" aria-label="About you">
          <h2>About you</h2>
          <p className="sub">Your role shapes what answers lead with, never the evidence or a figure.</p>
          {prof && (
            <>
              <select className="popup" value={prof.role} onChange={(e) => role(e.target.value)} aria-label="Your role">
                {Object.entries(prof.personas).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
              <p className="ap-style">{prof.style}</p>
              <h3>What Nabd remembers</h3>
              <p className="sub">Only what you save here. Sent with each question; delete any item at any time.</p>
              <ul className="ap-mem">{prof.memory.map((m) => (
                <li key={m.id}><span>{m.text}</span><button type="button" className="link-btn" onClick={() => forget(m.id)} aria-label={`Forget: ${m.text}`}>Forget</button></li>
              ))}{!prof.memory.length && <li className="sub">Nothing saved yet.</li>}</ul>
              <form onSubmit={remember} className="ap-add">
                <input value={mem} onChange={(e) => setMem(e.target.value)} placeholder="e.g. I sit on the MRMC; show amounts in AED" aria-label="Something for Nabd to remember" />
                <button className="btn small" type="submit" disabled={mem.trim().length < 3}>Remember</button>
              </form>
            </>
          )}
        </aside>
      </div>
    </>
  );
}
