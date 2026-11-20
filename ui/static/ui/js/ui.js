/* Day Loop UI runtime: modal system, toasts, menus. Depends on htmx (vendored). */
(function () {
  'use strict';
  var root = function () { return document.getElementById('modal-root'); };
  var opener = null;

  /* ---------- modal ---------- */
  function currentDialog() { var r = root(); return r && r.querySelector('dialog.modal'); }

  function openDialog() {
    var dlg = currentDialog();
    if (!dlg || dlg.open) return;
    opener = document.activeElement;
    dlg.showModal();                       // native focus trap + ESC
    document.body.classList.add('scroll-locked');
    var auto = dlg.querySelector('[autofocus]') || dlg.querySelector('input:not([type=hidden]), select, textarea');
    if (auto) auto.focus();
  }

  function closeDialog() {
    var dlg = currentDialog();
    if (dlg && dlg.open) dlg.close();
    teardown();
  }

  function teardown() {
    var r = root();
    if (r) r.innerHTML = '';
    document.body.classList.remove('scroll-locked');
    if (opener && document.contains(opener)) { try { opener.focus(); } catch (e) {} }
    opener = null;
  }

  document.addEventListener('htmx:afterSwap', function (e) {
    if (e.detail.target && e.detail.target.id === 'modal-root') openDialog();
  });
  document.addEventListener('close', function (e) {            // fired by <dialog> on ESC / close()
    if (e.target.matches && e.target.matches('dialog.modal')) teardown();
  }, true);
  document.addEventListener('click', function (e) {
    var dlg = currentDialog();
    if (!dlg) return;
    if (e.target.closest('[data-modal-close]')) { e.preventDefault(); closeDialog(); return; }
    if (e.target === dlg) closeDialog();                       // backdrop click
  });

  /* ---------- toasts ---------- */
  function toast(message, level) {
    var box = document.getElementById('toasts');
    if (!box || !message) return;
    var t = document.createElement('div');
    t.className = 'toast' + (level === 'error' ? ' error' : '');
    t.setAttribute('role', level === 'error' ? 'alert' : 'status');
    t.textContent = message;
    box.appendChild(t);
    setTimeout(function () { t.remove(); }, 4200);
  }
  window.dlToast = toast;

  /* HX-Trigger events: {"toast": {"message": "...", "level": "success"}, "closeModal": true} */
  document.body.addEventListener('toast', function (e) { toast(e.detail.message, e.detail.level); });
  document.body.addEventListener('closeModal', closeDialog);

  /* ---------- htmx plumbing ---------- */
  document.addEventListener('htmx:configRequest', function (e) {
    var m = document.querySelector('meta[name="csrf-token"]');
    if (m) e.detail.headers['X-CSRFToken'] = m.content;
  });
  document.addEventListener('htmx:beforeRequest', function (e) {
    var el = e.detail.elt;
    var btn = el.matches && el.matches('form') ? el.querySelector('button[type=submit]') : null;
    if (btn) btn.classList.add('is-loading');
  });
  document.addEventListener('htmx:afterRequest', function (e) {
    var el = e.detail.elt;
    var btn = el.matches && el.matches('form') ? el.querySelector('button[type=submit]') : null;
    if (btn) btn.classList.remove('is-loading');
  });
  document.addEventListener('htmx:beforeSwap', function (e) {
    var s = e.detail.xhr.status;
    if (s === 422) { e.detail.shouldSwap = true; e.detail.isError = false; }   // validation errors re-render the modal
    if (s === 403 || s === 401) {
      e.detail.shouldSwap = false;
      toast('Your session has ended or you are not authorised.', 'error');
      setTimeout(function () { window.location.href = '/login/'; }, 900);
    }
    if (s >= 500) { e.detail.shouldSwap = false; toast('Something went wrong. Please try again.', 'error'); }
  });

  /* ---------- shell: drawer, menus, password toggle ---------- */
  document.addEventListener('click', function (e) {
    var t = e.target.closest('[data-toggle-nav]');
    if (t) {
      var shell = document.querySelector('.shell');
      var open = shell.dataset.navOpen === 'true';
      shell.dataset.navOpen = open ? 'false' : 'true';
      t.setAttribute('aria-expanded', String(!open));
      return;
    }
    if (e.target.closest('.scrim')) { document.querySelector('.shell').dataset.navOpen = 'false'; return; }

    var mb = e.target.closest('[data-menu-toggle]');
    document.querySelectorAll('.menu-panel').forEach(function (p) {
      var owner = p.parentElement.querySelector('[data-menu-toggle]');
      if (mb && owner === mb) {
        var show = p.hidden; p.hidden = !show; mb.setAttribute('aria-expanded', String(show));
      } else { p.hidden = true; if (owner) owner.setAttribute('aria-expanded', 'false'); }
    });

    var pw = e.target.closest('[data-toggle-password]');
    if (pw) {
      var input = document.getElementById(pw.dataset.togglePassword);
      var show2 = input.type === 'password';
      input.type = show2 ? 'text' : 'password';
      pw.textContent = show2 ? 'Hide' : 'Show';
      pw.setAttribute('aria-pressed', String(show2));
    }
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') {
      document.querySelectorAll('.menu-panel').forEach(function (p) { p.hidden = true; });
      var sr = document.querySelector('.search-results'); if (sr) sr.innerHTML = '';
      var shell = document.querySelector('.shell'); if (shell) shell.dataset.navOpen = 'false';
    }
  });

  /* login form loading state */
  document.addEventListener('submit', function (e) {
    var f = e.target;
    if (f.matches && f.matches('[data-loading-form]')) {
      var b = f.querySelector('button[type=submit]'); if (b) b.classList.add('is-loading');
    }
  });
})();
