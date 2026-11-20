/* List pages: select-all and bulk bar. Delegated, so it survives HTMX swaps of #list-region. */
(function () {
  'use strict';
  function boxes() { return Array.prototype.slice.call(document.querySelectorAll('#product-table input[name=ids]')); }
  function refresh() {
    var checked = boxes().filter(function (b) { return b.checked; });
    var bar = document.getElementById('bulk-bar'), n = document.getElementById('bulk-count');
    if (bar) bar.hidden = checked.length === 0;
    if (n) n.textContent = checked.length;
    var all = document.getElementById('select-all');
    if (all) { all.checked = checked.length > 0 && checked.length === boxes().length; all.indeterminate = checked.length > 0 && !all.checked; }
  }
  document.addEventListener('change', function (e) {
    if (e.target.id === 'select-all') { boxes().forEach(function (b) { b.checked = e.target.checked; }); refresh(); }
    else if (e.target.name === 'ids') refresh();
  });
  document.body.addEventListener('htmx:afterSwap', refresh);
  document.body.addEventListener('products-changed', function () { setTimeout(refresh, 400); });
})();
