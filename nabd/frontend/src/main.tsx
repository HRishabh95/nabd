import { StrictMode, useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './design/glass.css';
import './design/app.css';
import './design/invest.css';
import './design/type.css';
import './design/ask.css';
import './design/overview.css';
import { PAGES, TabBar, type PageId } from './components/Chrome';
import Overview from './pages/Overview';
import Investment from './pages/Investment';
import Forecasting from './pages/Forecasting';
import Fraud from './pages/Fraud';
import Governance from './pages/Governance';
import AskPage from './pages/AskPage';
import AskNabd from './components/AskNabd';
import ErrorBoundary from './components/ErrorBoundary';

function currentPage(): PageId {
  const id = location.hash.slice(1);
  return (PAGES.some((p) => p.id === id) || id === 'ask' ? id : 'overview') as PageId;
}

function App() {
  const [page, setPage] = useState<PageId>(currentPage);
  const [askOpen, setAskOpen] = useState(false);
  useEffect(() => {
    const onHash = () => setPage(currentPage());
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey || /input|textarea|select/i.test((e.target as HTMLElement).tagName)) return;
      if (e.key === '/') { e.preventDefault(); setAskOpen(true); return; }
      const p = PAGES[Number(e.key) - 1];
      if (p) location.hash = `#${p.id}`;
    };
    addEventListener('hashchange', onHash);
    addEventListener('keydown', onKey);
    return () => { removeEventListener('hashchange', onHash); removeEventListener('keydown', onKey); };
  }, []);
  useEffect(() => {
    document.title = `${PAGES.find((p) => p.id === page)?.name ?? (page === "ask" ? "Ask Nabd" : "Nabd")} · Nabd · Central Bank of the UAE`;
  }, [page]);

  return (
    <div className="shell">
      <div className="main">
        <main id="content">
          <section className="page on" key={page}><ErrorBoundary name={page}>
            {page === 'overview' && <Overview />}
            {page === 'investment' && <Investment />}
            {page === 'forecasting' && <Forecasting />}
            {page === 'fraud' && <Fraud />}
            {page === 'governance' && <Governance />}
            {page === 'ask' && <AskPage />}
          </ErrorBoundary></section>
        </main>
      </div>
      <TabBar current={page} onAsk={() => setAskOpen((o) => !o)} askOpen={askOpen} />
      <AskNabd open={askOpen} onClose={() => setAskOpen(false)} page={page} />
    </div>
  );
}

createRoot(document.getElementById('root')!).render(<StrictMode><App /></StrictMode>);
