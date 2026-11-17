// Types for the investment API (only the fields the UI reads).
export type Stage = 'idea' | 'screening' | 'research' | 'fit' | 'stress' | 'committee' | 'position' | 'closed';
export const STAGES: Stage[] = ['idea', 'screening', 'research', 'fit', 'stress', 'committee', 'position', 'closed'];
export const STAGE_LABEL: Record<Stage, string> = {
  idea: 'Idea', screening: 'Screening', research: 'Research', fit: 'Portfolio fit', stress: 'Stress',
  committee: 'Committee', position: 'Monitoring', closed: 'Closed',
};

export type Invalidation = { label: string; series: string | null; op: '>' | '<' | null; value: number | null };
export type Thesis = {
  title: string; summary: string; direction: 'overweight' | 'underweight'; horizon: 'tactical' | 'strategic';
  committee: string; tranche: string; themes: string[]; sectors: string[]; regions: string[]; asset_classes: string[];
  prefer_index: boolean; drivers: string[]; invalidation: Invalidation[]; questions: string[];
  implementation?: 'add' | 'reduce' | 'hedge'; hedge_themes?: string[]; assumptions?: string[];
};
export type BasketItem = { symbol: string; weight_pct: number; name?: string; research_only?: boolean };
export type Point = { text: string; evidence: string[] };
export type EvidenceItem = { id: string; tool: string; args: Record<string, unknown>; result: unknown };
export type Research = {
  note: { summary: string; instruments: { symbol: string; stance: 'supports' | 'mixed' | 'against'; points: Point[] }[];
    news_read: Point[]; risks: Point[]; past_ideas: Point[]; answers: Point[] };
  evidence: Record<string, EvidenceItem>; model: string; seconds: number;
};
export type Fit = {
  te_bp: { before: number; after: number; idea: number }; budget_bp: number;
  budget_used_pct: { before: number; after: number }; contributions: { symbol: string; active_pct: number; contribution_pct: number }[];
  corr_with_existing: number | null; active_var95_1d_bp: number; active_var95_usd_mn: number; total_var99_1d_pct: number;
  var_backtest: { exceptions_250d: number; expected: number; limit: number };
  max_multiple: number; max_total_pct: number; tilt: Record<string, number>; active: Record<string, number>;
  liquidity: { symbol: string; position_usd_mn: number; adv_usd_mn: number; days_at_20pct_adv: number | null }[];
  non_sri_lines: string[]; run_id: string; data: { start: string; end: string; shrinkage: number };
};
export type ScenarioRow = { name: string; active_bp: number; active_usd_mn: number; portfolio_pct: number; proxied?: string[]; moves?: Record<string, number>; start?: string; end?: string };
export type Stress = {
  replays: ScenarioRow[]; shocks: ScenarioRow[]; worst: { name: string; active_bp: number; active_usd_mn: number };
  monte_carlo: { paths: number; horizon_days: number; active_bp_percentiles: Record<string, number>; prob_active_loss: number;
    active_es95_bp: number; histogram: { edges_bp: number[]; counts: number[] } };
  run_id: string;
};
export type ExitPlan = { target_active_bp: number; stop_active_bp: number; review_by: string; invalidation: Invalidation[]; rebalance: string };
export type Committee = {
  pack: Record<string, unknown>;
  cover: { recommendation_framing: string; case_for: string[]; case_against: string[]; risk_points: string[]; conditions_to_consider: string[] };
  risk_signoff: null | { opinion: string; comment: string; by: string; ts: number };
  decision: null | { decision: string; conditions: string; rationale: string; by: string; ts: number };
};
export type Check = { name: string; value: string; limit: string; status: 'ok' | 'watch' | 'breach' | 'target' | 'unknown'; series?: string };
export type Position = {
  entry_date: string; health: null | { score: number; checks: Check[]; active_bp: number | null; ts: number };
  history: { ts: number; score: number; active_bp: number | null }[];
  closed?: { reason: string; lesson: { outcome: string; lesson: string } };
};
export type MemoryHit = { idea_id: string; title: string; stage: string; kind: string; decision: string | null; when: string; snippet: string; seeded: boolean };
export type Idea = {
  id: string; title: string; text: string; horizon: string; owner: string; stage: Stage; stage_label: string; status: string;
  created: number; updated: number; funding: string; thesis: Thesis | null; basket: { items: BasketItem[]; total_pct: number } | null;
  research: (Research & { kind?: undefined }) | Deep | null; fit: Fit | null; stress: Stress | null; committee: Committee | null; exit_plan: ExitPlan | null;
  position: Position | null; memory_hits: MemoryHit[] | null;
};
export type IdeaEvent = { id: number; ts: number; actor: string; stage: string; action: string };
export type ScreenRow = {
  symbol: string; name: string; kind: string; asset: string; sector: string; region: string; sri: boolean; fit: number;
  reasons: string[]; mom_12_1_pct: number; mom_3m_pct: number; vol_1y_pct: number; max_dd_1y_pct: number; adv_usd_mn: number;
  ml_rank_pct: number | null; beta_to_theme?: number | null; corr_with_holdings?: number | null; te_per_1pct_bp?: number;
  held_direct_pct?: number; held_indirect_pct?: number | null; max_underweight_pct?: number;
};
export type Holding = { symbol: string; name: string; weight_pct: number; source: string; beta_to_theme: number | null; theme_exposure_pct: number | null; max_cut_pct?: number; te_per_1pct_cut_bp?: number };
export type Protect = { symbol: string; name: string; asset: string; kind: string; sri: boolean; type?: string; avg_on_theme_worst_days_pct: number; beta_to_theme: number | null; corr_with_holdings: number | null; vol_1y_pct: number; te_per_1pct_bp: number };
export type Screen = { rows: ScreenRow[]; considered: number; matched: number; implementation: 'add' | 'reduce' | 'hedge';
  holdings: Holding[]; theme_basket: string[]; theme_exposure_pct: number; theme_worst_days: number; theme_worst_day_avg_pct: number | null;
  reduce: Holding[]; protect: Protect[];
  lookthrough?: Record<string, { loaded: boolean; as_of?: string; holdings?: number; file?: string; error?: string; source?: string | null }>;
  ranker: { run_id: string; as_of: string; metrics: { months: number; mean_ic: number; ic_t_stat: number; hit_rate: number; top_minus_bottom_quintile_3m_pct: number } } };
export type Action = 'buy' | 'hold_less' | 'protect' | 'study';
export type Candidate = { symbol: string; action: Action; reason: string; name: string; asset: string; kind: string; sector: string; sri: boolean;
  moves_with_driver: number | null; on_worst_days_pct: number | null; held_direct_pct: number; held_indirect_pct: number | null; max_cut_pct: number;
  tradable: boolean; note: string | null; check: { agrees: boolean | null; text: string }; risk_per_1pct_bp: number | null;
  corr_with_holdings: number | null; vol_1y_pct: number | null; adv_usd_mn: number | null; ml_rank_pct: number | null };
export type ScreenView = { status: 'ready'; source: 'llm' | 'rules'; created: number | null; driver: { label: string; symbols: string[]; if_right: string };
  bearish: boolean; holdings: (Holding & { moves_with_driver: number | null })[]; exposure_pct: number; worst_days: number; worst_day_avg_pct: number | null;
  groups: { action: Action; items: Candidate[] }[]; lookthrough_loaded: boolean } | { status: 'proposing'; job_id: string };
export type Alert = { id: number; ts: number; idea_id: string | null; rule: string; severity: string; title: string; status: string };
export type Portfolio = {
  notional_usd_bn: number; active_risk_budget_bp: number; tranches: { name: string; weight: number }[];
  lines: { symbol: string; tranche: string; weight: number; role: string }[];
  risk: { te_bp: { before: number }; budget_used_pct: { before: number }; total_var99_1d_pct: number; run_id: string };
  regime: { state: string; current: Record<string, number>; as_of: string; run_id: string };
  positions: Idea[]; disclaimer: string;
};

export const fmt = {
  bp: (v: number | null | undefined) => (v == null ? '—' : `${v > 0 ? '+' : ''}${v.toFixed(1)} bp`),
  pct: (v: number | null | undefined, d = 1) => (v == null ? '—' : `${v > 0 ? '+' : ''}${v.toFixed(d)}%`),
  usd: (mn: number | null | undefined) => (mn == null ? '—' : Math.abs(mn) >= 1000 ? `USD ${(mn / 1000).toFixed(2)} bn` : `USD ${mn.toFixed(0)} mn`),
  date: (ts: number) => new Date(ts * 1000).toLocaleString('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }),
};

// ---------- deep research ----------
export type Verdict = 'supported' | 'refuted' | 'inconclusive';
export type DeepPoint = Point & { check?: 'supported' | 'partly' | 'unsupported' | null };
export type Finding = { id: string; verdict: Verdict; confidence: number; summary: string; evidence_for: DeepPoint[];
  evidence_against: DeepPoint[]; caveats: string[]; tool_calls?: number; error?: string };
export type ClaimCheck = { id: string; text: string; status: 'supported' | 'partly' | 'unsupported'; note: string;
  numbers: number; untraced: string[]; missing_evidence: string[]; auto_linked?: string[] };
export type Deep = {
  kind: 'deep'; stage: 'plan' | 'investigate' | 'challenge' | 'verify' | 'synthesise' | 'done'; started: number;
  finished?: number; seconds?: number; as_of: string | null; web: boolean; tool_calls?: number;
  calls: Record<string, number>;
  plan: null | { framing: string; hypotheses: { id: string; statement: string; why_it_matters: string; test: string }[] };
  findings: Record<string, Finding>;
  red_team: null | { bear_case: string; points: Point[]; breaks_if: string[] };
  verification: null | { stats: { claims: number; supported: number; partly: number; unsupported: number; figures_checked: number;
    figures_traced: number; auto_linked?: number; evidence_items: number; web_searches: number; non_official_urls: string[] }; claims: ClaimCheck[] };
  synthesis: null | { headline: string; overall: string; confidence: number; summary: string;
    hypotheses: { id: string; verdict: Verdict; confidence: number; one_line: string }[]; portfolio_view: string;
    what_would_change_our_mind: string[]; proposed_triggers: Invalidation[]; open_questions: string[] };
  evidence: Record<string, EvidenceItem>;
  split?: { lines: { symbol: string; name: string; weight_pct: number; why: string; selected_pct: number; research_only_before: boolean }[]; notes: string[];
    check: null | { by_class: { name: string; before_pct: number; after_pct: number }[]; driver: { label: string; before_pct: number; after_pct: number } | null;
      risk: { budget_used_before_pct: number; budget_used_after_pct: number; budget_bp: number } | null; warnings: string[] } };
};
