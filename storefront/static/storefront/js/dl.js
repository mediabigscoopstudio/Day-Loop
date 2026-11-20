(function () {
  'use strict';
  document.querySelectorAll('.flash').forEach(function (f) { window.dlToast && dlToast(f.textContent, f.dataset.level); });

  // sticky navbar glass on scroll
  var nav = document.getElementById('nav');
  function onScroll() { if (nav) nav.classList.toggle('scrolled', window.scrollY > 8); }
  window.addEventListener('scroll', onScroll, { passive: true }); onScroll();

  // ?login=1 (redirect from a protected page) opens the sign-in popup
  var q = new URLSearchParams(location.search);
  if (q.get('login') && window.htmx) {
    htmx.ajax('GET', '/modal/login/?next=' + encodeURIComponent(q.get('next') || '/'), { target: '#modal-root' });
  }

  // phone Search tab focuses the navbar search
  document.addEventListener('click', function (e) {
    var t = e.target.closest('[data-focus-search]');
    if (t) { e.preventDefault(); var i = document.querySelector('.nav-search input'); if (i) { window.scrollTo(0, 0); i.focus(); } }
    if (!e.target.closest('.nav-search')) { var r = document.getElementById('search-results'); if (r) r.innerHTML = ''; }
    var sel = e.target.closest('[data-qty]');
    if (sel) {
      var inp = document.getElementById(sel.dataset.target);
      var v = Math.max(1, (parseInt(inp.value, 10) || 1) + parseInt(sel.dataset.qty, 10));
      inp.value = v;
    }
    var th = e.target.closest('[data-thumb]');
    if (th) { var m = document.getElementById('main-img'); if (m) m.src = th.dataset.thumb; }
    var tab = e.target.closest('[data-tab]');
    if (tab) {
      document.querySelectorAll('[data-tab]').forEach(function (x) { x.classList.toggle('on', x === tab); });
      document.querySelectorAll('[data-pane]').forEach(function (p) { p.hidden = p.dataset.pane !== tab.dataset.tab; });
    }
    var geo = e.target.closest('[data-geo]');
    if (geo) {
      var out = document.getElementById('geo-msg');
      if (!navigator.geolocation) { if (out) out.textContent = 'Location is not available. Search for your area instead.'; return; }
      navigator.geolocation.getCurrentPosition(function () {
        if (out) out.textContent = 'Got your location. Pick the nearest area below to confirm.';
      }, function () { if (out) out.textContent = 'Location is off. Search for your area instead.'; }, { timeout: 6000 });
    }
  });

  // price slider label + payment method pick
  document.addEventListener('input', function (e) {
    if (e.target.matches('[data-range]')) {
      var o = document.getElementById(e.target.dataset.range); if (o) o.textContent = '₹' + Number(e.target.value).toLocaleString('en-IN');
    }
  });
  // keep selected variant in the add-to-cart form
  document.addEventListener('change', function (e) {
    if (e.target.matches('input[name=variant_pick]')) {
      document.querySelectorAll('input[name=variant_id]').forEach(function (i) { i.value = e.target.value; });
      var u = new URL(location.href); u.searchParams.set('variant', e.target.value); history.replaceState(null, '', u);
    }
  });
  // protein calculator (client-side only, nothing stored)
  var kg = document.getElementById('calc-kg');
  if (kg) {
    var C = 326.7;
    var pick = function (name) { var r = document.querySelector('#protein-calc input[name=' + name + ']:checked'); return r ? parseFloat(r.value) : 1; };
    var calc = function () {
      var w = Math.min(200, Math.max(0, parseFloat(kg.value) || 0));
      var g = Math.round(w * pick('goal') * pick('activity'));
      var scoops = Math.ceil(g / 24);
      document.getElementById('calc-g').textContent = g;
      document.getElementById('calc-scoops').innerHTML = 'About <b>' + scoops + '</b> scoop' + (scoops === 1 ? '' : 's') + ' of whey a day';
      var ring = document.getElementById('calc-ring');
      ring.style.strokeDashoffset = C * (1 - Math.min(1, g / 250));
    };
    kg.addEventListener('input', calc);
    document.querySelectorAll('#protein-calc input[type=radio]').forEach(function (r) { r.addEventListener('change', calc); });
    calc();
  }
  // reminder calendar picker
  document.querySelectorAll('[data-cal]').forEach(function (cal) {
    var btn = cal.querySelector('[data-cal-toggle]');
    var panel = cal.querySelector('.cal-panel');
    var input = cal.querySelector('input[name=day]');
    var dayTxt = cal.querySelector('.cal-btn-day');
    function setOpen(open) { panel.hidden = !open; btn.setAttribute('aria-expanded', String(open)); }
    btn.addEventListener('click', function (e) { e.stopPropagation(); setOpen(panel.hidden); });
    cal.querySelectorAll('.cal-day').forEach(function (d) {
      d.addEventListener('click', function () {
        cal.querySelectorAll('.cal-day').forEach(function (x) { x.classList.remove('on'); x.setAttribute('aria-pressed', 'false'); });
        d.classList.add('on'); d.setAttribute('aria-pressed', 'true');
        input.value = d.dataset.day; dayTxt.textContent = d.dataset.day;
        setOpen(false);
      });
    });
    document.addEventListener('click', function (e) { if (!cal.contains(e.target)) setOpen(false); });
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape') setOpen(false); });
  });
})();
