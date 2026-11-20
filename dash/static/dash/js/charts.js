/* Chart.js wiring for dash. Charts load their data from JSON endpoints (data-url). */
(function () {
  'use strict';
  if (typeof Chart === 'undefined') return;
  var css = getComputedStyle(document.documentElement);
  var v = function (n) { return css.getPropertyValue(n).trim(); };
  var palette = [v('--green-700'), v('--sage-300'), v('--green-500'), v('--sage-200'), v('--orange'), '#7aa88a'];
  var reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  Chart.defaults.font.family = v('--font') || 'system-ui';
  Chart.defaults.color = v('--muted');
  Chart.defaults.animation = reduce ? false : { duration: 500 };

  function group(n) {                       // 1234567 -> 12,34,567
    var s = String(Math.round(Math.abs(n))), last = s.slice(-3), rest = s.slice(0, -3);
    if (rest) last = rest.replace(/\B(?=(\d{2})+(?!\d))/g, ',') + ',' + last;
    return (n < 0 ? '-' : '') + last;
  }
  function inr(n) { return '₹' + group(n); }
  function inrShort(n) {
    var a = Math.abs(n);
    if (a >= 1e7) return '₹' + (n / 1e7).toFixed(2).replace(/\.?0+$/, '') + ' Cr';
    if (a >= 1e5) return '₹' + (n / 1e5).toFixed(2).replace(/\.?0+$/, '') + ' L';
    if (a >= 1e3) return '₹' + (n / 1e3).toFixed(0) + 'K';
    return '₹' + Math.round(n);
  }
  window.dlMoney = { inr: inr, short: inrShort };

  var charts = new WeakMap();

  var builders = {
    sales: function (ctx, d) {
      var g = ctx.createLinearGradient(0, 0, 0, 260);
      g.addColorStop(0, 'rgba(10,107,63,.22)'); g.addColorStop(1, 'rgba(10,107,63,0)');
      return { type: 'line', data: { labels: d.labels, datasets: [{
        data: d.gmv, borderColor: v('--green-700'), backgroundColor: g, fill: true, tension: .35,
        pointRadius: d.labels.length > 40 ? 0 : 3, pointHoverRadius: 5, pointBackgroundColor: v('--card'),
        pointBorderColor: v('--green-700'), borderWidth: 2 }] },
        options: { responsive: true, maintainAspectRatio: false, interaction: { mode: 'index', intersect: false },
          plugins: { legend: { display: false }, tooltip: { callbacks: { label: function (c) { return ' ' + inr(c.parsed.y); } } } },
          scales: { x: { grid: { display: false }, ticks: { maxTicksLimit: 8, maxRotation: 0 } },
            y: { beginAtZero: true, grid: { color: 'rgba(14,74,53,.08)' }, border: { display: false },
              ticks: { maxTicksLimit: 6, callback: function (x) { return inrShort(x); } } } } } };
    },
    donut: function (ctx, d) {
      var rows = d.rows;
      return { type: 'doughnut', data: { labels: rows.map(function (r) { return r.name; }), datasets: [{
        data: rows.map(function (r) { return r.revenue; }), backgroundColor: rows.map(function (_, i) { return palette[i % palette.length]; }),
        borderColor: v('--card'), borderWidth: 3 }] },
        options: { responsive: true, maintainAspectRatio: false, cutout: '68%',
          plugins: { legend: { display: false }, tooltip: { callbacks: { label: function (c) { return ' ' + c.label + ': ' + inr(c.parsed); } } } } } };
    },
    stacked: function (ctx, d) {
      return { type: 'bar', data: { labels: d.labels, datasets: [
        { label: 'New customers', data: d.new, backgroundColor: v('--orange'), borderRadius: 4 },
        { label: 'Repeat customers', data: d.repeat, backgroundColor: v('--green-700'), borderRadius: 4 }] },
        options: { responsive: true, maintainAspectRatio: false, interaction: { mode: 'index', intersect: false },
          plugins: { legend: { position: 'bottom', labels: { usePointStyle: true, boxWidth: 8 } } },
          scales: { x: { stacked: true, grid: { display: false }, ticks: { maxTicksLimit: 8, maxRotation: 0 } },
            y: { stacked: true, beginAtZero: true, ticks: { precision: 0 }, grid: { color: 'rgba(14,74,53,.08)' }, border: { display: false } } } } };
    }
  };

  function renderLegend(sel, d) {
    var box = document.querySelector(sel); if (!box) return;
    box.innerHTML = '';
    if (!d.rows.length) { box.innerHTML = '<div class="empty" style="padding:8px">No revenue in this period.</div>'; return; }
    d.rows.forEach(function (r, i) {
      var row = document.createElement('div'); row.className = 'legend-row';
      row.innerHTML = '<span class="swatch" style="background:' + palette[i % palette.length] + '"></span><span></span><strong></strong><span></span>';
      row.children[1].textContent = r.name; row.children[2].textContent = r.share + '%'; row.children[3].textContent = inrShort(r.revenue);
      box.appendChild(row);
    });
  }

  function empty(canvas, isEmpty) {
    var note = canvas.closest('section, .card');
    var msg = note && note.querySelector('.chart-empty');
    if (msg) msg.hidden = !isEmpty;
    canvas.style.visibility = isEmpty ? 'hidden' : 'visible';
  }

  function render(canvas) {
    var kind = canvas.dataset.chart, url = canvas.dataset.url;
    fetch(url, { headers: { Accept: 'application/json' }, credentials: 'same-origin' })
      .then(function (r) {
        if (r.status === 403) { window.location.href = '/login/'; throw new Error('forbidden'); }
        return r.json();
      })
      .then(function (d) {
        var old = charts.get(canvas); if (old) old.destroy();
        if (kind === 'donut') {
          renderLegend(canvas.dataset.legend, d);
          var t = document.getElementById('donut-total'); if (t) t.textContent = inrShort(d.total);
          empty(canvas, !d.rows.length);
        } else if (kind === 'sales') {
          empty(canvas, !d.gmv.some(function (x) { return x > 0; }));
        } else if (kind === 'stacked') {
          empty(canvas, !d.new.concat(d.repeat).some(function (x) { return x > 0; }));
        }
        charts.set(canvas, new Chart(canvas.getContext('2d'), builders[kind](canvas.getContext('2d'), d)));
      })
      .catch(function () {});
  }

  document.querySelectorAll('canvas[data-chart]').forEach(render);
  document.body.addEventListener('sellers-changed', function () {
    document.querySelectorAll('canvas[data-chart]').forEach(render);
  });
})();
