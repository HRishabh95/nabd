// Nabd prototype v5 — the Model room: every model as a live system, from data in to governance. Illustrative only.
// Structure follows CBUAE's Model Management Standards and the 2026 AI/ML guidance: inventory, risk rating,
// independent validation, monitoring, human oversight.
(() => {
  const D = window.NABD;
  const lanes = [
    {
      id: 'gdp', title: 'GDP nowcast and forecast', owner: 'Economic Research', route: '#forecast', status: 'Attention', tone: 'amber',
      why: 'Card data coverage has fallen below its threshold',
      data: [
        { name: 'UAEFTS settlements', vol: 'AED 142.6 bn today', ok: true },
        { name: 'Aani instant payments', vol: '1.84 m today', ok: true },
        { name: 'WPS payroll', vol: 'AED 31.2 bn, October', ok: true },
        { name: 'Card spending', vol: '81% of volume received', ok: false },
        { name: 'Dubai Land Department', vol: '1,018 deals', ok: true },
        { name: 'News, Arabic and English', vol: '2,140 articles today', ok: true, isNew: true },
      ],
      champion: { name: 'Ensemble v3.2', note: '4 models, weighted' },
      challenger: { name: 'Ensemble v3.3 with news', note: 'adds a news model trained on 1.2 m articles' },
      champErr: [0.24, 0.22, 0.23, 0.21, 0.22, 0.25, 0.27, 0.24, 0.22, 0.21, 0.22, 0.21],
      challErr: [0.23, 0.22, 0.21, 0.20, 0.21, 0.21, 0.22, 0.20, 0.19, 0.19, 0.20, 0.19],
      perf: [
        { k: 'Error, 1 quarter ahead', v: '0.21 pp', s: 'benchmark 0.55 pp', tone: 'good' },
        { k: 'Card data coverage', v: '81%', s: 'threshold 90%', tone: 'warn' },
        { k: 'Feeds current', v: '4 of 5', s: 'card acquirers a day late', tone: 'warn' },
        { k: 'News shock indicator', v: 'High', s: 'shipping and Hormuz coverage up 3.4×', tone: 'warn' },
      ],
      gov: { tier: 'Tier 1, high materiality', validated: '28 Oct 2026', next: '28 Apr 2027', approver: 'Model Committee', checks: ['In model inventory', 'Independently validated', 'Monitored daily', 'Explanations for every figure', 'Human sign-off on briefings'] },
    },
    {
      id: 'fraud', title: 'Fraud detection for the Anti-Fraud Operations Centre', owner: 'Payment Systems', route: '#fraud', status: 'Attention', tone: 'amber',
      why: 'A new scam pattern is rising faster than the model was trained for',
      data: [
        { name: 'Aani instant payments', vol: '1.84 m scored today', ok: true },
        { name: 'UAEFTS transfers', vol: '92,400 today', ok: true },
        { name: 'Confirmation of Payee results', vol: '3,412 name mismatches', ok: true },
        { name: 'Bank fraud reports', vol: '211 this week', ok: true },
        { name: 'Account opening data', vol: '18,900 new accounts', ok: true },
      ],
      champion: { name: 'Mule-ring graph model v2.4', note: 'scores in 38 ms' },
      challenger: { name: 'Graph model v2.5', note: 'adds device and Confirmation of Payee signals' },
      tradeoff: { champ: { recall: 0.78, precision: 0.86 }, chall: { recall: 0.84, precision: 0.81 } },
      perf: [
        { k: 'Rings caught (recall)', v: '78%', s: 'one bank alone: 31%', tone: 'good' },
        { k: 'Alerts that are real (precision)', v: '86%', s: 'target 80%', tone: 'good' },
        { k: 'Analyst capacity used', v: '37 of 45', s: 'alerts per day', tone: 'neutral' },
        { k: 'Impersonation scams', v: '+40%', s: 'month on month, above training range', tone: 'warn' },
      ],
      gov: { tier: 'Tier 1, high materiality', validated: '3 Nov 2026', next: '3 May 2027', approver: 'Model Committee', checks: ['In model inventory', 'Independently validated', 'Monitored hourly', 'Reasons shown on every alert', 'Human sign-off before banks are alerted'] },
    },
    {
      id: 'res', title: 'Reserves and investment', owner: 'Reserve Management, with Risk as second line', route: '#invest', status: 'Normal', tone: 'green',
      why: 'Within risk budget; two due-diligence findings open',
      data: [
        { name: 'Market prices', vol: '4,200 instruments, end of day', ok: true },
        { name: 'External manager reports', vol: '6 managers, monthly', ok: true },
        { name: 'Nabd scenarios', vol: 'run 4812, Hormuz 30 days', ok: true },
        { name: 'Manager documents and news', vol: '38 documents read', ok: true },
      ],
      champion: { name: 'Scenario risk model v1.8', note: '1,000 runs per scenario' },
      challenger: { name: 'Due-diligence document model v1.1', note: 'language model, on premise, cites every source' },
      perf: [
        { k: 'Active risk budget used', v: '62%', s: 'set by the Board', tone: 'good' },
        { k: 'Risk model backtest exceptions', v: '2 in 250 days', s: 'limit 4', tone: 'good' },
        { k: 'Figures extracted correctly', v: '94%', s: 'sample review of 200', tone: 'good' },
        { k: 'Due-diligence findings open', v: '2', s: 'Manager B', tone: 'warn' },
      ],
      gov: { tier: 'Tier 2, medium materiality', validated: '14 Oct 2026', next: '14 Oct 2027', approver: 'Monetary and Reserve Committee', checks: ['In model inventory', 'Independently validated', 'Backtested daily', 'Information barrier for Investment', 'Committee approves guidelines'] },
    },
  ];
  const inventory = { production: 8, attention: lanes.filter((l) => l.tone === 'amber').length, challengers: 2, overdue: 0 };
  Object.assign(D, { lanes, inventory });
})();
