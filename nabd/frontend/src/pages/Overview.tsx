// Overview: what markets are doing and the news that matters. Nothing else.
import { useCallback, useEffect, useMemo, useState } from 'react';
import Chart from '../components/Chart';
import { PageHeader } from '../components/Chrome';
import { api } from '../lib/api';
import { useEvent } from '../lib/stream';

type Change = { pct?: number; bp?: number } | null;
type Market = { symbol: string; name: string; group: string; kind: 'index' | 'yield' | 'price' | 'fx'; missing?: boolean;
  last?: number; as_of?: string; currency?: string | null; history_days?: number; day?: Change; month?: Change; ytd?: Change; spark?: number[] };
type Mover = { symbol: string; name: string; pct: number };
type Snapshot = { groups: { name: string; markets: Market[] }[]; movers: { as_of: string | null; up: Mover[]; down: Mover[] }; source: string; refreshed: number | null };
type Article = { url: string; title: string; source: string; ts: number; theme: string; theme_title: string; lang?: string };

const TOPICS: [string | null, string][] = [[null, 'All'], ['markets', 'Markets'], ['oil', 'Oil'], ['hormuz', 'Gulf shipping'],
  ['uae_economy', 'UAE economy'], ['fed_rates', 'Fed and rates'], ['gold', 'Gold'], ['ai_capex', 'AI and chips'], ['central_banks', 'Central banks']];
const SHORT_TOPIC: Record<string, string> = Object.fromEntries(TOPICS.filter(([k]) => k).map(([k, v]) => [k as string, v]));
const HEADLINE = ['DFMGI.AE', '^GSPC', 'BZ=F', '^TNX', 'GC=F'];

const minus = (s: string) => s.replace('-', '−');
// values are rounded for display first, so a move that shows as 0 is neutral rather than green or red
function shown(c: Change | undefined, digits: number): number | null {
  if (!c) return null;
  return c.bp != null ? Math.round(c.bp) : Number(c.pct!.toFixed(digits));
}
function fmtChange(c: Change | undefined, digits = 2): string {
  const v = shown(c, digits);
  if (v == null) return '—';
  const sign = v > 0 ? '+' : '';
  return minus(c!.bp != null ? `${sign}${v} bp` : `${sign}${v.toFixed(digits)}%`);
}
const dir = (c: Change | undefined, digits = 2) => { const v = shown(c, digits) ?? 0; return v > 0 ? 'up' : v < 0 ? 'down' : 'flat'; };
function fmtLevel(m: Market): string {
  const v = m.last!;
  if (m.kind === 'yield') return `${v.toFixed(2)}%`;
  if (m.kind === 'fx') return v.toFixed(v < 10 ? 4 : 2);
  const n = v.toLocaleString('en-GB', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return m.kind === 'price' && m.currency === 'USD' ? `$${n}` : n;
}
function ago(ts: number | null | undefined): string {
  if (!ts) return '';
  const s = Date.now() / 1000 - ts;
  return s < 90 ? 'just now' : s < 5400 ? `${Math.round(s / 60)} min ago` : s < 129600 ? `${Math.round(s / 3600)} h ago` : `${Math.round(s / 86400)} d ago`;
}

function Spark({ values }: { values: number[] }) {
  if (values.length < 5) return <span className="ov-spark empty" aria-hidden="true" />;
  const lo = Math.min(...values), hi = Math.max(...values), w = 72, h = 26;
  const pts = values.map((v, i) => `${(i / (values.length - 1)) * w},${h - 2 - ((v - lo) / (hi - lo || 1)) * (h - 4)}`).join(' ');
  return <svg className="ov-spark" viewBox={`0 0 ${w} ${h}`} aria-hidden="true"><polyline points={pts} /></svg>;
}

const RANGES: [string, number][] = [['1M', 31], ['3M', 92], ['1Y', 366]];

function Detail({ m }: { m: Market }) {
  const [range, setRange] = useState(92);
  const [rows, setRows] = useState<{ date: string; close: number }[] | null>(null);
  useEffect(() => {
    api.get<{ rows: { date: string; close: number }[] }>(`/api/data/series/${encodeURIComponent(m.symbol)}`)
      .then((r) => setRows(r.rows.filter((x) => x.close != null)), () => setRows([]));
  }, [m.symbol]);
  const shown = useMemo(() => {
    if (!rows?.length) return [];
    const cut = new Date(rows[rows.length - 1].date); cut.setDate(cut.getDate() - range);
    return rows.filter((r) => new Date(r.date) >= cut);
  }, [rows, range]);
  return (
    <div className="ov-detail">
      <dl className="ov-stats">
        <div><dt>Today</dt><dd className={`num ${dir(m.day)}`}>{fmtChange(m.day)}</dd></div>
        <div><dt>1 month</dt><dd className={`num ${dir(m.month, 1)}`}>{fmtChange(m.month, 1)}</dd></div>
        <div><dt>This year</dt><dd className={`num ${dir(m.ytd, 1)}`}>{fmtChange(m.ytd, 1)}</dd></div>
        {shown.length > 5 && <div className="segmented ov-range" role="tablist" aria-label="Chart range">
          {RANGES.map(([l, d]) => <button key={l} type="button" role="tab" aria-pressed={range === d} onClick={() => setRange(d)}>{l}</button>)}
        </div>}
      </dl>
      {rows == null ? <p className="sub">Loading…</p> : shown.length > 5 ? (
        <Chart height={150} c={{ type: 'line', title: m.name, y_label: m.kind === 'yield' ? '%' : (m.currency ?? ''), x: shown.map((r) => r.date),
          series: [{ name: m.name, values: shown.map((r) => r.close) }] }} />
      ) : <p className="sub">Yahoo publishes only today’s level for this index, so Nabd builds its history from each day’s close (day {m.history_days ?? 1} so far).</p>}
    </div>
  );
}

function Markets({ snap }: { snap: Snapshot }) {
  const [open, setOpen] = useState<string | null>(null);
  const { up, down } = snap.movers;
  return (
    <section className="card ov-markets">
      <div className="card-head"><div><h2>Markets</h2><p className="sub">Latest close or live level · select a market for its chart</p></div></div>
      <div className="scroll">
        {snap.groups.map((g) => (
          <div key={g.name} className="ov-group">
            <h3>{g.name}</h3>
            <ul>
              {g.markets.filter((m) => !m.missing).map((m) => (
                <li key={m.symbol} className={open === m.symbol ? 'on' : ''}>
                  <button type="button" className="ov-row" onClick={() => setOpen(open === m.symbol ? null : m.symbol)} aria-expanded={open === m.symbol}>
                    <span className="ov-name"><strong>{m.name}</strong><span className="sub">{m.as_of ? new Date(m.as_of).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' }) : ''}</span></span>
                    <Spark values={m.spark ?? []} />
                    <span className="ov-level num">{fmtLevel(m)}</span>
                    <span className={`ov-chg num ${dir(m.day)}`}>{fmtChange(m.day)}</span>
                  </button>
                  {open === m.symbol && <Detail m={m} />}
                </li>
              ))}
            </ul>
          </div>
        ))}
        {(up.length > 0 || down.length > 0) && (
          <div className="ov-group">
            <h3>Moving most among Nabd’s instruments</h3>
            <div className="ov-movers">
              <ul>{up.map((r) => <li key={r.symbol}><span>{r.name}</span><span className="ov-chg num up">{fmtChange({ pct: r.pct })}</span></li>)}</ul>
              <ul>{down.map((r) => <li key={r.symbol}><span>{r.name}</span><span className="ov-chg num down">{fmtChange({ pct: r.pct })}</span></li>)}</ul>
            </div>
          </div>
        )}
        <p className="sub ov-source">{snap.source}</p>
      </div>
    </section>
  );
}

function News() {
  const [topic, setTopic] = useState<string | null>(null);
  const [items, setItems] = useState<Article[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const load = useCallback(() => {
    api.get<{ articles: Article[] }>(`/api/markets/news?limit=60${topic ? `&topic=${topic}` : ''}`)
      .then((r) => { setItems(r.articles); setErr(null); }, (e) => setErr((e as Error).message));
  }, [topic]);
  useEffect(() => { setItems(null); load(); }, [load]);
  useEvent('data.refreshed', (e) => { if (e.data.source === 'news' || e.data.source === 'documents') load(); });
  return (
    <section className="card ov-news">
      <div className="card-head ov-news-head">
        <h2>News</h2>
        <div className="ov-topics" role="tablist" aria-label="Topic">
          {TOPICS.map(([k, label]) => <button key={label} type="button" role="tab" aria-pressed={topic === k} onClick={() => setTopic(k)}>{label}</button>)}
        </div>
      </div>
      <ol className="scroll ov-feed">
        {err && <li className="sub">News is unavailable right now ({err}).</li>}
        {items == null && !err && <li className="sub">Loading…</li>}
        {items?.length === 0 && <li className="sub">No headlines on this topic in the last three days.</li>}
        {items?.map((a) => (
          <li key={a.url}>
            <a href={a.url} target="_blank" rel="noopener noreferrer" dir="auto">{a.title}</a>
            <span className="sub">{a.source} · {ago(a.ts)}{!topic && a.theme ? ` · ${SHORT_TOPIC[a.theme] ?? a.theme_title}` : ''}{a.lang === 'ara' ? ' · Arabic' : ''}</span>
          </li>
        ))}
      </ol>
    </section>
  );
}

export default function Overview() {
  const [snap, setSnap] = useState<Snapshot | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const load = useCallback(() => api.get<Snapshot>('/api/markets').then((s) => { setSnap(s); setErr(null); }, (e) => setErr((e as Error).message)), []);
  useEffect(() => { load(); }, [load]);
  useEvent('data.refreshed', (e) => { if (e.data.source === 'markets' || e.data.source === 'prices') load(); });

  const all = snap?.groups.flatMap((g) => g.markets) ?? [];
  const line = HEADLINE.map((s) => all.find((m) => m.symbol === s)).filter((m): m is Market => !!m && !m.missing && !!m.day)
    .map((m) => `${m.name} ${fmtChange(m.day)}`).join(' · ');
  const today = new Date().toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long' });
  return (
    <>
      <PageHeader title="Overview" lede={<>{today}{line ? ` · ${line}` : ''}{snap?.refreshed ? <span className="sub"> · updated {ago(snap.refreshed)}</span> : null}</>} />
      <div className="fill grid ov-grid">
        {snap ? <Markets snap={snap} /> : <section className="card ov-markets"><p className="sub">{err ? `Markets are unavailable right now (${err}).` : 'Loading…'}</p></section>}
        <News />
      </div>
    </>
  );
}
