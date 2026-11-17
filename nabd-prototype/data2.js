// Nabd prototype v4 — forecasting models, investment portfolio and mandates, fraud detection system. Illustrative only.
(() => {
  const D = window.NABD;

  // ---------- forecasting: quarterly history and the ensemble's forecast ----------
  const hist = D.quarters.map((q) => ({ label: q.label, value: q.official ?? q.nabd, official: q.official != null }));
  const fcst = [
    { label: 'Q4 2026', value: 1.4, h70: 0.5, h90: 0.9 },
    { label: 'Q1 2027', value: 2.1, h70: 0.8, h90: 1.4 },
    { label: 'Q2 2027', value: 3.0, h70: 1.0, h90: 1.8 },
    { label: 'Q3 2027', value: 3.6, h70: 1.2, h90: 2.1 },
  ];
  const models = [
    { name: 'Gradient-boosted trees', kind: 'Machine learning on 214 payment features', weight: 34, h1: 0.24, h4: 0.71, trained: '15 Nov 22:00' },
    { name: 'Mixed-frequency regression', kind: 'Daily payments to quarterly GDP', weight: 28, h1: 0.27, h4: 0.78, trained: '15 Nov 22:00' },
    { name: 'Dynamic factor model', kind: 'Statistical, 38 series', weight: 24, h1: 0.29, h4: 0.74, trained: '15 Nov 22:00' },
    { name: 'Temporal neural network', kind: 'Deep learning on daily sequences', weight: 14, h1: 0.31, h4: 0.83, trained: '14 Nov 22:00' },
  ];
  console.assert(models.reduce((a, m) => a + m.weight, 0) === 100, 'ensemble weights sum to 100');
  const ensemble = { name: 'Nabd ensemble', h1: 0.21, h4: 0.66 };
  const benchmarks = [{ name: 'Standard PMI and oil model', h1: 0.55, h4: 1.12 }, { name: 'Simple autoregression', h1: 0.71, h4: 1.30 }];
  const horizons = ['Now', '1 quarter', '2 quarters', '3 quarters', '4 quarters'];
  const horizonErr = [
    { name: 'Nabd ensemble', values: [0.20, 0.21, 0.38, 0.52, 0.66], main: true },
    { name: 'Standard PMI and oil model', values: [0.55, 0.55, 0.74, 0.95, 1.12] },
    { name: 'Simple autoregression', values: [0.68, 0.71, 0.92, 1.12, 1.30] },
  ];
  const features = [
    { name: 'UAEFTS contractor payments', v: 0.31 }, { name: 'WPS payroll growth', v: 0.27 }, { name: 'Card spending', v: 0.22 },
    { name: 'Freight and port payments', v: 0.19 }, { name: 'Brent crude', v: 0.15 }, { name: 'Dubai Land Department deals', v: 0.12 },
    { name: 'Aani merchant payments', v: 0.09 }, { name: 'Purchasing managers’ index', v: 0.06 },
  ];

  // ---------- investment: a notional portfolio (AED 100 bn) and the mandate pipeline ----------
  const notional = 100; // AED bn, notional, not CBUAE's reserves
  const allocation = [
    { name: 'Developed-market government bonds', w: 45, hormuz30: 0.6 },
    { name: 'Supranational and agency bonds', w: 14, hormuz30: 0.4 },
    { name: 'Equities, external managers', w: 12, hormuz30: -6.1 },
    { name: 'Gold', w: 9, hormuz30: 5.8 },
    { name: 'Cash and deposits', w: 8, hormuz30: 0.0 },
    { name: 'Emerging-market government bonds', w: 7, hormuz30: -3.2 },
    { name: 'Other', w: 5, hormuz30: -1.0 },
  ];
  console.assert(allocation.reduce((a, x) => a + x.w, 0) === 100, 'allocation sums to 100');
  const stages = ['Screening', 'Due diligence', 'Investment committee', 'Approved', 'Monitoring'];
  const mandates = [
    { id: 'M-118', name: 'Asia ex-Japan equity mandate', aed: 2.5, stage: 0, next: '11 managers responding', owner: 'Equities team' },
    { id: 'M-121', name: 'Private credit pilot', aed: 0.5, stage: 0, next: 'Policy review, 2 Dec', owner: 'Strategy team' },
    { id: 'M-112', name: 'Emerging-market local-currency debt mandate', aed: 3.0, stage: 1, next: '3 managers shortlisted; 2 findings open', owner: 'Fixed income team', dd: true },
    { id: 'M-109', name: 'Green and sustainability bond mandate', aed: 2.0, stage: 2, next: 'Committee meets 24 Nov', owner: 'Fixed income team' },
    { id: 'M-104', name: 'Gold allocation rebalance', aed: 1.5, stage: 3, next: 'Executing over 6 weeks', owner: 'Reserves team' },
    { id: 'M-097', name: 'US Treasury duration overlay', aed: 4.0, stage: 4, next: 'Within risk budget', owner: 'Reserves team' },
  ];
  const ddFindings = [
    { sev: 'high', text: 'Manager B reports assets under management of US$ 41.2 bn in its questionnaire; its audited 2025 report says US$ 38.0 bn, a difference of 8%.', src: 'Questionnaire p. 12 · audited annual report 2025 p. 7' },
    { sev: 'high', text: 'Manager B’s lead portfolio manager left in February 2026; the questionnaire still lists them as lead.', src: 'Questionnaire p. 4 · press report, 18 Feb 2026' },
    { sev: 'warn', text: 'Under scenario run 4812 the mandate’s benchmark falls 3.2%, breaching the risk budget in 38% of the 1,000 runs.', src: 'Nabd scenario engine, run 4812' },
    { sev: 'ok', text: 'Sanctions and adverse-media screening is clear across 214 related entities for all three managers.', src: 'Screening run, 15 Nov 2026' },
    { sev: 'ok', text: 'Manager A and Manager C fee schedules match their 2024 submissions.', src: 'Questionnaires p. 21 · 2024 file' },
  ];
  const managers = [
    { name: 'Manager A', score: 82, aum: 'US$ 112 bn', track: '+0.9% a year vs benchmark', open: 0 },
    { name: 'Manager B', score: 61, aum: 'US$ 38.0 bn (audited)', track: '+1.4% a year vs benchmark', open: 2 },
    { name: 'Manager C', score: 77, aum: 'US$ 64 bn', track: '+0.6% a year vs benchmark', open: 0 },
  ];

  // ---------- fraud detection system ----------
  const fraudKpis = { scored: 1842113, medianMs: 38, alerts: 37 };
  const alerts = [
    { id: 'R-2611-07', typ: 'Mule ring', scope: '41 accounts', banks: 6, aed: 4.82, score: 0.97, status: 'Case open', tone: 'red', link: true },
    { id: 'A-77805', typ: 'Fan-out to new accounts', scope: '14 accounts', banks: 4, aed: 1.10, score: 0.84, status: 'Reviewing', tone: 'amber' },
    { id: 'A-77812', typ: 'Rapid pass-through', scope: '9 accounts', banks: 3, aed: 0.61, score: 0.91, status: 'Reviewing', tone: 'amber' },
    { id: 'A-77809', typ: 'Impersonation scam', scope: '1 account, 58 victims', banks: 2, aed: 0.34, score: 0.88, status: 'Alert sent to banks', tone: 'green' },
    { id: 'A-77801', typ: 'Payroll diversion', scope: '3 employers on WPS', banks: 1, aed: 0.22, score: 0.79, status: 'New', tone: '' },
    { id: 'A-77796', typ: 'Merchant collusion', scope: '5 card merchants', banks: 2, aed: 0.18, score: 0.72, status: 'New', tone: '' },
  ].sort((a, b) => b.score - a.score);
  const heldAed = +alerts.reduce((a, x) => a + x.aed, 0).toFixed(2);
  console.assert(heldAed === 7.27, 'held value', heldAed);
  const detection = { central: { precision: 0.86, recall: 0.78 }, single: { precision: 0.71, recall: 0.31 } };
  const typologies = [
    { name: 'Impersonation scams', n: 27 }, { name: 'Rapid pass-through', n: 19 }, { name: 'Fan-out to new accounts', n: 11 },
    { name: 'Merchant collusion', n: 8 }, { name: 'Payroll diversion', n: 6 }, { name: 'Mule rings', n: 4 },
  ];

  Object.assign(D, { hist, fcst, fmodels: models, ensemble, benchmarks, horizons, horizonErr, features,
    notional, allocation, stages, mandates, ddFindings, managers, fraudKpis, alerts, heldAed, detection, typologies });
})();
