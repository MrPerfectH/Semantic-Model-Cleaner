/* Native modal layers contain focus and restore the invoking control. */
(function () {
  'use strict';
  function upgrade(element, label) {
    var dialog = document.createElement('dialog');
    Array.from(element.attributes).forEach(function (attribute) { dialog.setAttribute(attribute.name, attribute.value); });
    dialog.setAttribute('aria-label', label);
    while (element.firstChild) dialog.appendChild(element.firstChild);
    element.replaceWith(dialog);
    return dialog;
  }
  document.querySelectorAll('.modal-overlay').forEach(function (element) {
    var heading = element.querySelector('h2');
    var dialog = upgrade(element, heading ? heading.textContent : 'Review');
    if (heading) { heading.id = heading.id || dialog.id + 'Title'; dialog.setAttribute('aria-labelledby', heading.id); }
    function sync() {
      if (dialog.classList.contains('hidden')) { if (dialog.open) dialog.close(); }
      else if (!dialog.open) dialog.showModal();
    }
    dialog.addEventListener('close', function () { dialog.classList.add('hidden'); });
    new MutationObserver(sync).observe(dialog, {attributes:true, attributeFilter:['class']});
    sync();
  });
  var drawer = document.getElementById('scopeDrawer');
  if (drawer) {
    drawer = upgrade(drawer, 'Analysis scope');
    drawer.inert = false;
    drawer.removeAttribute('aria-hidden');
    window.smcOpenScope = function () {
      document.body.classList.add('scope-open');
      if (!drawer.open) drawer.showModal();
    };
    window.smcCloseScope = function () {
      document.body.classList.remove('scope-open');
      if (drawer.open) drawer.close();
    };
    drawer.addEventListener('close', function () { document.body.classList.remove('scope-open'); });
  }
  var path = document.getElementById('explorerPathInput');
  if (path) path.setAttribute('aria-label', 'Folder path');
  document.querySelectorAll('.scope-close').forEach(function (button) { button.setAttribute('aria-label', 'Close analysis scope'); });
  document.addEventListener('keydown', function (event) {
    if (event.key !== 'Tab') return;
    var dialog = event.target.closest('dialog[open]');
    if (!dialog) return;
    var controls = Array.from(dialog.querySelectorAll('button:not(:disabled),a[href],input:not(:disabled),select:not(:disabled),textarea:not(:disabled),summary,[tabindex]')).filter(function (node) {
      return node.tabIndex >= 0 && node.getClientRects().length && !node.closest('[inert]') && getComputedStyle(node).visibility !== 'hidden';
    });
    var next = event.shiftKey ? controls[controls.length - 1] : controls[0];
    if (next && (event.target === dialog || event.target === (event.shiftKey ? controls[0] : controls[controls.length - 1]))) {
      event.preventDefault(); next.focus();
    }
  });
})();
