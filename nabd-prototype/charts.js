// Nabd charts — one small SVG renderer for every time chart: bands (fans), hairline runs, lines, markers, hover read-out.
// Colours come from CSS custom properties so the palette stays in nabd.css.
(() => {
  const NS = 'http://www.w3.org/2000/svg';
  const el = (tag, attrs = {}, parent) => { const n = document.createElementNS(NS, tag); for (const [k, v] of Object.entries(attrs)) if (v != null) n.setAttribute(k, v); if (parent) parent.appendChild(n); return n; };
  const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

  function render(host, o) {
    host.innerHTML = '';
    const w = Math.max(280, host.clientWidth || 600), h = o.height || 240, n = o.xLabels.length;
    const yt = o.yTicks, ymin = yt[0], ymax = yt[yt.length - 1], fmt = o.yFormat || ((v) => String(v));
    const padL = 10 + Math.max(...yt.map((v) => fmt(v).length)) * 7, padR = o.padR ?? 8, padB = 26;
    const rows = o.markers && o.markers.length ? 22 : 6, padT = rows;
    const x = (i) => padL + (i * (w - padL - padR)) / Math.max(1, n - 1);
    const y = (v) => padT + (h - padT - padB) * (1 - (Math.max(ymin, Math.min(ymax, v)) - ymin) / (ymax - ymin));
    const s = el('svg', { viewBox: `0 0 ${w} ${h}`, height: h, role: 'img', 'aria-label': o.label || '' }, host);
    // grid and y ticks
    yt.forEach((v) => {
      el('line', { x1: padL, x2: w - padR, y1: y(v), y2: y(v), stroke: v === 0 ? '#9aa1a9' : css('--rule'), 'stroke-width': 1, 'shape-rendering': 'crispEdges' }, s);
      const t = el('text', { x: padL - 8, y: y(v) + 4, 'text-anchor': 'end' }, s); t.textContent = fmt(v);
    });
    // x labels: about six, evenly stepped, first and last kept inside
    const want = Math.min(n, Math.max(3, Math.floor((w - padL) / 110)));
    const step = Math.max(1, Math.round((n - 1) / (want - 1)));
    for (let i = 0; i < n; i += step) {
      const t = el('text', { x: x(i), y: h - 6, 'text-anchor': i === 0 ? 'start' : (n - 1 - i < step / 2 ? 'end' : 'middle') }, s);
      t.textContent = o.xLabels[i];
    }
    const path = (vals) => vals.map((v, i) => (v == null ? null : `${x(i).toFixed(1)},${y(v).toFixed(1)}`)).filter(Boolean).join(' L');
    const area = (lo, hi) => `M${path(hi)} L${hi.map((_, i) => i).reverse().map((i) => `${x(i).toFixed(1)},${y(lo[i]).toFixed(1)}`).join(' L')} Z`;
    (o.bands || []).forEach((b) => el('path', { d: area(b.lo, b.hi), fill: b.color, stroke: 'none' }, s));
    (o.hairlines || []).forEach((hl) => hl.lines.forEach((vals) => el('path', { d: 'M' + path(Array.from(vals)), fill: 'none', stroke: hl.color, 'stroke-width': 1, opacity: hl.opacity ?? 0.12 }, s)));
    (o.series || []).forEach((sr) => el('path', { d: 'M' + path(sr.values), fill: 'none', stroke: sr.color, 'stroke-width': sr.width || 2, 'stroke-dasharray': sr.dash || null, 'stroke-linejoin': 'round', class: sr.cls || null, pathLength: sr.cls ? 1 : null }, s));
    (o.points || []).forEach((p) => { if (p.pulse) el('circle', { cx: x(p.at), cy: y(p.value), r: (p.r || 4) + 2, fill: 'none', stroke: p.color, 'stroke-width': 2, class: 'pulse-ring' }, s); el('circle', { cx: x(p.at), cy: y(p.value), r: p.r || 4, fill: p.color, stroke: '#fff', 'stroke-width': 2 }, s); });
    // markers: a dashed rule with its label in the lane above the plot; labels alternate sides to avoid collisions
    let lastRight = -Infinity;
    (o.markers || []).forEach((m) => {
      const mx = x(m.at);
      el('line', { x1: mx, x2: mx, y1: padT - 4, y2: h - padB, stroke: m.color || '#6b7178', 'stroke-width': 1, 'stroke-dasharray': '3 3' }, s);
      const t = el('text', { x: mx, y: 12, fill: m.color || css('--ink-2'), 'font-weight': 600 }, s); t.textContent = m.label;
      const tw = t.getComputedTextLength ? t.getComputedTextLength() : m.label.length * 6.5;
      let anchorLeft = mx + 6 + tw > w - padR || mx + 6 < lastRight;
      if (anchorLeft) { t.setAttribute('text-anchor', 'end'); t.setAttribute('x', mx - 6); } else { t.setAttribute('x', mx + 6); lastRight = mx + 6 + tw + 12; }
    });
    // hover read-out
    if (o.tip) {
      const tip = document.createElement('div'); tip.className = 'tip'; host.appendChild(tip);
      const guide = el('line', { y1: padT, y2: h - padB, stroke: css('--ink'), 'stroke-width': 1, opacity: 0 }, s);
      const hit = el('rect', { x: padL, y: 0, width: w - padL - padR, height: h - padB, fill: 'transparent' }, s);
      hit.addEventListener('mousemove', (e) => {
        const r = s.getBoundingClientRect(), px = ((e.clientX - r.left) / r.width) * w;
        const i = Math.max(0, Math.min(n - 1, Math.round(((px - padL) / (w - padL - padR)) * (n - 1))));
        guide.setAttribute('x1', x(i)); guide.setAttribute('x2', x(i)); guide.setAttribute('opacity', 0.35);
        tip.textContent = o.tip(i); tip.style.left = `${(x(i) / w) * 100}%`; tip.style.top = `${padT + 8}px`; tip.style.opacity = 1;
      });
      hit.addEventListener('mouseleave', () => { tip.style.opacity = 0; guide.setAttribute('opacity', 0); });
    }
    return { x, y, svg: s };
  }
  window.NabdChart = { render, el };
})();
