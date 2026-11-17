import type { ReactNode } from 'react';
import { useStreamStatus } from '../lib/stream';

export type PageId = 'overview' | 'investment' | 'forecasting' | 'fraud' | 'governance' | 'ask';

export const PAGES: { id: PageId; name: string; short?: string; icon: ReactNode }[] = [
  { id: 'overview', name: 'Overview', icon: <><rect x="3.5" y="4.5" width="17" height="15" rx="2.5" /><path d="M7 9h6M7 12.5h10M7 16h10" /><path d="M15.5 8.2l1.4-1.4 1.6 1.6" /></> },
  { id: 'investment', name: 'Investment', short: 'Invest', icon: <><path d="M4 20h16" /><path d="M6 20V10M10 20V6M14 20v-8M18 20V8" /></> },
  { id: 'forecasting', name: 'Forecasting', short: 'Forecast', icon: <><path d="M3.5 17.5 9 12l4 3.5 7.5-8" /><path d="M15.5 7.5h5v5" /></> },
  { id: 'fraud', name: 'Fraud network', short: 'Fraud', icon: <><circle cx="6" cy="6" r="2.5" /><circle cx="18" cy="7" r="2.5" /><circle cx="12" cy="18" r="2.5" /><path d="M8.3 7.1 15.6 7M7.3 8.3 10.9 15.8M16.8 9.3 13.3 15.9" /></> },
  { id: 'governance', name: 'Governance', short: 'Models', icon: <><path d="M12 3.5 19 6v5.5c0 4.2-3 7.6-7 9-4-1.4-7-4.8-7-9V6l7-2.5z" /><path d="m8.8 12 2.2 2.2 4.2-4.4" /></> },
];

const LIVE_TEXT = { live: 'Live', connecting: 'Connecting…', polling: 'Reconnecting · polling', offline: 'Backend offline' } as const;

export function LiveBadge() {
  const s = useStreamStatus();
  return <span className={`tb-live live-${s}`} role="status">{LIVE_TEXT[s]}</span>;
}

export function PageHeader({ title, lede, actions }: { title: string; lede: ReactNode; actions?: ReactNode }) {
  return (
    <div className="large-title">
      <a className="pt-brand" href="#overview" aria-label="Nabd, Central Bank of the UAE">
        <img src="/cbuae-logo.png" alt="Central Bank of the U.A.E." />
      </a>
      <div className="pt-text"><h1>{title}</h1><p>{lede}</p></div>
      <div className="pt-actions"><LiveBadge />{actions}</div>
    </div>
  );
}

export function TabBar({ current, onAsk, askOpen }: { current: PageId; onAsk: () => void; askOpen: boolean }) {
  return (
    <nav className="dock glass" aria-label="Pages">
      {PAGES.map((p, i) => (
        <a key={p.id} className="tab" href={`#${p.id}`} data-page={p.id} title={`${p.name} (${i + 1})`}
          aria-current={p.id === current ? 'page' : undefined}>
          <svg viewBox="0 0 24 24" aria-hidden="true">{p.icon}</svg><span className="tab-long">{p.name}</span><span className="tab-short" aria-hidden="true">{p.short ?? p.name}</span>
        </a>
      ))}
      <span className="dock-sep" aria-hidden="true" />
      <button type="button" className={`tab ask-tab ${askOpen ? 'on' : ''}`} onClick={onAsk} aria-pressed={askOpen} title="Ask Nabd (/)">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4.5 6.5a2 2 0 0 1 2-2h11a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H11l-4 3.5v-3.5h-.5a2 2 0 0 1-2-2z" /><path d="M8.5 9.5h7M8.5 12.5h4.5" /></svg>
        <span>Ask Nabd</span>
      </button>
    </nav>
  );
}

export function Card({ title, sub, head, className = '', children }: {
  title: string; sub?: ReactNode; head?: ReactNode; className?: string; children: ReactNode;
}) {
  return (
    <article className={`card ${className}`}>
      <div className="card-head"><div><h2>{title}</h2>{sub && <p className="sub">{sub}</p>}</div>{head}</div>
      {children}
    </article>
  );
}
