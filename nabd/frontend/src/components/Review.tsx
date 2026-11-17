import { useEffect, useState } from 'react';
import { api } from '../lib/api';

// Human review of an AI output: useful or not, with an optional reason. Stored with who and when, counted on the
// Governance page, written to the audit log.
type Kind = 'research' | 'fraud_note' | 'ask' | 'thesis' | 'proposal';
type State = { up: number; down: number };

export default function Review({ kind, refId, label = 'Was this useful?' }: { kind: Kind; refId: string; label?: string }) {
  const [st, setSt] = useState<State | null>(null);
  const [mine, setMine] = useState<1 | -1 | null>(null);
  const [why, setWhy] = useState('');
  const [asking, setAsking] = useState(false);
  useEffect(() => { setMine(null); setAsking(false); api.get<State>(`/api/governance/review/${kind}/${encodeURIComponent(refId)}`).then(setSt, () => undefined); }, [kind, refId]);

  async function send(verdict: 1 | -1, comment = '') {
    setMine(verdict); setAsking(false);
    try { setSt(await api.post<State>('/api/governance/review', { kind, ref: refId, verdict, comment })); } catch { /* the review is optional */ }
  }
  return (
    <div className="fb" role="group" aria-label={label}>
      <span className="sub">{mine ? 'Thanks: recorded with your name and time.' : label}</span>
      <button type="button" className={`fb-btn ${mine === 1 ? 'on' : ''}`} aria-pressed={mine === 1} onClick={() => send(1)} disabled={!!mine} aria-label="Useful">👍</button>
      <button type="button" className={`fb-btn ${mine === -1 ? 'on' : ''}`} aria-pressed={mine === -1} onClick={() => (mine ? undefined : setAsking(true))} disabled={!!mine} aria-label="Not useful">👎</button>
      {st && (st.up + st.down > 0) && <span className="sub num">{st.up} 👍 · {st.down} 👎</span>}
      {asking && (
        <form className="fb-why" onSubmit={(e) => { e.preventDefault(); send(-1, why); }}>
          <input value={why} onChange={(e) => setWhy(e.target.value)} placeholder="What was wrong? (optional)" aria-label="What was wrong" autoFocus />
          <button className="btn small" type="submit">Send</button>
        </form>
      )}
    </div>
  );
}
