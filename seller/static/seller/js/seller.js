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

/* ---- drag-to-reorder for gallery / A+ lists (arrows remain for phones) ---- */
(function () {
  'use strict';
  var dragged = null;
  function csrf() { var m = document.querySelector('meta[name="csrf-token"]'); return m ? m.content : ''; }
  document.addEventListener('dragstart', function (e) {
    var c = e.target.closest && e.target.closest('.img-card[draggable="true"]'); if (!c) return;
    dragged = c; c.classList.add('dragging'); e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', c.dataset.id);
  });
  document.addEventListener('dragover', function (e) {
    if (!dragged) return;
    var over = e.target.closest && e.target.closest('.img-card'); if (!over || over === dragged || over.parentNode !== dragged.parentNode) return;
    e.preventDefault();
    var r = over.getBoundingClientRect();
    over.parentNode.insertBefore(dragged, (e.clientX - r.left) > r.width / 2 ? over.nextSibling : over);
  });
  document.addEventListener('dragend', function () {
    if (!dragged) return;
    var list = dragged.parentNode, url = list.dataset.reorderUrl;
    dragged.classList.remove('dragging'); dragged = null;
    if (!url) return;
    var ids = Array.prototype.map.call(list.querySelectorAll('.img-card'), function (c) { return c.dataset.id; }).join(',');
    fetch(url, { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/x-www-form-urlencoded', 'X-CSRFToken': csrf(), 'HX-Request': 'true' }, body: 'ids=' + encodeURIComponent(ids) })
      .then(function (r) { if (!r.ok && window.dlToast) window.dlToast('Could not save the new order.', 'error'); });
  });
})();
