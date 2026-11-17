// One shared EventSource for /api/stream. Components subscribe by event type.
// If no event (heartbeat included) arrives for 20 s the stream is treated as stale: we reconnect and, until it
// recovers, poll /api/system/health so the UI can still show the backend's state.
import { useEffect, useRef, useState } from 'react';

export type StreamEvent = { type: string; id: string; data: Record<string, unknown> & { ts: number } };
type Listener = (e: StreamEvent) => void;
export type StreamStatus = 'connecting' | 'live' | 'polling' | 'offline';

const listeners = new Map<string, Set<Listener>>();
const statusListeners = new Set<(s: StreamStatus) => void>();
let source: EventSource | null = null;
let lastSeen = 0;
let status: StreamStatus = 'connecting';
let watchdog: number | undefined;
let poller: number | undefined;
const known = new Set<string>(['heartbeat']);

function setStatus(s: StreamStatus) {
  if (s === status) return;
  status = s;
  statusListeners.forEach((f) => f(s));
}

function attach(type: string) {
  source?.addEventListener(type, (ev) => {
    const me = ev as MessageEvent;
    lastSeen = Date.now();
    setStatus('live');
    const e: StreamEvent = { type, id: me.lastEventId, data: JSON.parse(me.data) };
    listeners.get(type)?.forEach((f) => f(e));
    listeners.get('*')?.forEach((f) => f(e));
  });
}

function connect() {
  source?.close();
  source = new EventSource('/api/stream');
  source.onopen = () => { lastSeen = Date.now(); setStatus('live'); };
  source.onerror = () => setStatus(status === 'live' ? 'connecting' : status);
  known.forEach(attach);
}

async function poll() {
  try {
    const r = await fetch('/api/system/health');
    setStatus(r.ok ? 'polling' : 'offline');
  } catch {
    setStatus('offline');
  }
}

function start() {
  if (source) return;
  connect();
  watchdog = window.setInterval(() => {
    if (Date.now() - lastSeen > 20000) {
      if (!poller) { poll(); poller = window.setInterval(poll, 5000); }
      connect();
    } else if (poller) {
      clearInterval(poller); poller = undefined;
    }
  }, 5000);
}

export function subscribe(type: string, f: Listener): () => void {
  start();
  if (type !== '*' && !known.has(type)) { known.add(type); attach(type); }
  if (!listeners.has(type)) listeners.set(type, new Set());
  listeners.get(type)!.add(f);
  return () => listeners.get(type)!.delete(f);
}

// Event types are registered up front for '*' listeners, since EventSource has no wildcard.
export function register(...types: string[]) {
  start();
  types.forEach((t) => { if (!known.has(t)) { known.add(t); attach(t); } });
}

export function useStreamStatus(): StreamStatus {
  const [s, set] = useState<StreamStatus>(status);
  useEffect(() => { start(); statusListeners.add(set); set(status); return () => { statusListeners.delete(set); }; }, []);
  return s;
}

export function useEvent(type: string, f: Listener) {
  const ref = useRef(f);
  ref.current = f;
  useEffect(() => subscribe(type, (e) => ref.current(e)), [type]);
}

void watchdog;

