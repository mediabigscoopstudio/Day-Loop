/* Seller portal behaviour. Delegated listeners so it works inside HTMX-loaded modals. */
(function () {
  'use strict';

  /* ---- live volumetric / chargeable weight (same formula as the server: L x W x H / 5000) ---- */
  function num(box, key) { var el = box.querySelector('[data-w="' + key + '"]'); return el && el.value ? parseFloat(el.value) : 0; }
  function updateWeights(box) {
    var l = num(box, 'l'), w = num(box, 'w'), h = num(box, 'h'), g = num(box, 'g');
    var vol = (l > 0 && w > 0 && h > 0) ? Math.round(l * w * h / 5000 * 1000) / 1000 : 0;
    var dead = Math.round(g) / 1000;
    var chg = Math.max(vol, dead);
    var v = box.querySelector('[data-out="vol"]'), c = box.querySelector('[data-out="chg"]');
    if (v) v.textContent = vol.toFixed(3) + ' kg';
    if (c) c.textContent = chg.toFixed(3) + ' kg';
  }
  document.addEventListener('input', function (e) {
    var box = e.target.closest && e.target.closest('[data-weights]');
    if (box) updateWeights(box);
  });
  document.body.addEventListener('htmx:afterSwap', function () {
    document.querySelectorAll('[data-weights]').forEach(updateWeights);
  });
})();
