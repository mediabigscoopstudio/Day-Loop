/* Product editor: rich text (bold + lists only, plain-text paste), highlights, counters, auto-open of invalid sections. */
(function () {
  'use strict';

  /* ---- rich text ---- */
  document.querySelectorAll('[data-rte]').forEach(function (box) {
    var area = box.querySelector('.rte-area'), src = box.querySelector('textarea');
    src.hidden = true;
    area.innerHTML = src.value;                       // server already sanitised this
    function sync() { src.value = area.innerHTML; }
    area.addEventListener('input', sync);
    area.addEventListener('blur', sync);
    area.addEventListener('paste', function (e) {     // no HTML pasting: always plain text
      e.preventDefault();
      var text = (e.clipboardData || window.clipboardData).getData('text/plain');
      document.execCommand('insertText', false, text);
    });
    area.addEventListener('drop', function (e) { e.preventDefault(); });
    box.querySelectorAll('[data-cmd]').forEach(function (btn) {
      btn.addEventListener('mousedown', function (e) { e.preventDefault(); });        // keep the selection
      btn.addEventListener('click', function () { document.execCommand(btn.dataset.cmd, false, null); area.focus(); sync(); });
    });
    var form = box.closest('form');
    if (form) form.addEventListener('submit', sync);
  });

  /* ---- highlights ---- */
  var list = document.getElementById('hl-list'), add = document.getElementById('hl-add'), count = document.getElementById('hl-count');
  function refreshHl() {
    if (!list) return;
    var n = list.querySelectorAll('.hl-row').length;
    if (count) count.textContent = n;
    if (add) add.disabled = n >= parseInt(list.dataset.max, 10);
  }
  if (add) {
    add.addEventListener('click', function () {
      var row = document.createElement('div'); row.className = 'hl-row';
      row.innerHTML = '<input class="input" name="highlights" maxlength="140" placeholder="e.g. 25 g protein per serving">' +
                      '<button type="button" class="btn sm" data-hl-remove aria-label="Remove highlight">✕</button>';
      list.appendChild(row); row.querySelector('input').focus(); refreshHl();
    });
    list.addEventListener('click', function (e) {
      var b = e.target.closest('[data-hl-remove]'); if (b) { b.closest('.hl-row').remove(); refreshHl(); }
    });
    refreshHl();
  }

  /* ---- character counters ---- */
  document.querySelectorAll('[data-count]').forEach(function (el) {
    var max = parseInt(el.dataset.count, 10), soft = el.dataset.countSoft === 'true';
    var c = document.createElement('span'); c.className = 'counter'; el.insertAdjacentElement('afterend', c);
    function upd() {
      var n = el.value.length; c.textContent = n + ' / ' + max;
      c.classList.toggle('over', n > max);
      if (!soft) c.classList.toggle('over', n > max);
    }
    el.addEventListener('input', upd); upd();
  });

  /* ---- open any card that contains an error, and scroll to the first ---- */
  var firstBad = document.querySelector('.pcard .has-error, .pcard .field-error');
  if (firstBad) {
    var card = firstBad.closest('details'); if (card) card.open = true;
    document.querySelectorAll('.pcard').forEach(function (d) { if (d.querySelector('.has-error, .field-error')) d.open = true; });
    setTimeout(function () { firstBad.scrollIntoView({ block: 'center', behavior: 'smooth' }); }, 100);
  }
  // jump links open their card
  document.addEventListener('click', function (e) {
    var a = e.target.closest('a[href^="#sec-"]'); if (!a) return;
    var d = document.querySelector(a.getAttribute('href')); if (d && d.tagName === 'DETAILS') d.open = true;
  });
})();
