export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const r = await fetch(path, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail ?? msg; } catch { /* not json */ }
    throw new ApiError(r.status, msg);
  }
  return r.json() as Promise<T>;
}

export const api = {
  get: <T>(p: string) => call<T>('GET', p),
  post: <T>(p: string, b?: unknown) => call<T>('POST', p, b),
  del: <T>(p: string) => call<T>('DELETE', p),
  put: <T>(p: string, b?: unknown) => call<T>('PUT', p, b),
};

export type Check = { name: string; ok: boolean; level: 'ok' | 'warn' | 'fail'; detail: string; fix: string | null };
export type Health = { ok: boolean; uptime_s: number; llm_provider: string; subscribers: number };
export type SmokeResult = {
  run_id: string; model: string; ms: number;
  answer: { answer: string; figure_usd_bn: number; source: string };
  tool_calls: { tool: string; args: Record<string, unknown>; ok: boolean; ms: number }[];
};
