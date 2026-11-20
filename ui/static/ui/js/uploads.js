/* Upload fields: drag-drop, live preview (square for logos), camera capture. Delegated, works inside modals. */
(function () {
  'use strict';
  function zoneOf(el) { return el.closest('[data-dropzone]'); }

  function show(zone, file) {
    var name = zone.querySelector('[data-file-name]');
    var box = zone.querySelector('[data-preview-box]');
    if (name) name.textContent = file ? file.name + ' (' + Math.max(1, Math.round(file.size / 1024)) + ' KB)' : '';
    if (!box) return;
    if (!file) { box.hidden = true; box.innerHTML = ''; return; }
    box.hidden = false;
    if (file.type && file.type.indexOf('image/') === 0) {
      var img = document.createElement('img');
      img.alt = '';
      img.src = URL.createObjectURL(file);
      img.onload = function () { URL.revokeObjectURL(img.src); };
      box.innerHTML = ''; box.appendChild(img);
    } else {
      box.innerHTML = '<span class="dz-file">' + (file.type === 'application/pdf' ? 'PDF' : 'FILE') + '</span>';
    }
  }

  document.addEventListener('change', function (e) {
    if (e.target.type !== 'file') return;
    var zone = zoneOf(e.target); if (!zone) return;
    var f = e.target.files && e.target.files[0];
    // photo from the camera and file from the picker are mutually exclusive
    zone.querySelectorAll('input[type=file]').forEach(function (inp) { if (inp !== e.target && f) inp.value = ''; });
    show(zone, f);
  });

  ['dragenter', 'dragover'].forEach(function (t) {
    document.addEventListener(t, function (e) {
      var z = e.target.closest && e.target.closest('[data-dropzone]'); if (!z) return;
      e.preventDefault(); z.classList.add('is-over');
    });
  });
  ['dragleave', 'drop'].forEach(function (t) {
    document.addEventListener(t, function (e) {
      var z = e.target.closest && e.target.closest('[data-dropzone]'); if (!z) return;
      e.preventDefault(); z.classList.remove('is-over');
      if (t === 'drop' && e.dataTransfer && e.dataTransfer.files.length) {
        var input = z.querySelector('input[type=file]:not([capture])');
        if (input) { input.files = e.dataTransfer.files; input.dispatchEvent(new Event('change', { bubbles: true })); }
      }
    });
  });
  // a stray drop outside a zone must not navigate away from the page
  window.addEventListener('dragover', function (e) { e.preventDefault(); });
  window.addEventListener('drop', function (e) { e.preventDefault(); });
})();
