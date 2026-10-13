/* Native browser dialogs are blocked by VS Code's outer sandbox. Keep every
 * confirmation explicit and awaited; never substitute a truthy Promise for a
 * synchronous confirmation. Ordinary browser launches keep native dialogs. */
(function () {
  'use strict';
  var embedded = !!document.querySelector('meta[name="smc-embedded-host"]');
  var pending = Promise.resolve();
  function dialog(message, confirmation) {
    var result = pending.then(function () {
      return new Promise(function (resolve) {
        var previous = document.activeElement;
        var box = document.createElement('dialog');
        box.setAttribute('aria-label', confirmation ? 'Confirm action' : 'Semantic Model Cleaner');
        box.style.cssText = 'margin:auto;padding:24px;max-width:560px;max-height:80vh;overflow:auto;border:1px solid #cbd5e1;border-radius:12px;background:#fff;color:#0f172a;box-shadow:0 20px 60px #0004';
        var text = document.createElement('p');
        text.textContent = String(message); text.style.cssText = 'white-space:pre-wrap;margin:0 0 20px';
        box.appendChild(text);
        function button(label, value) {
          var control = document.createElement('button');
          control.type = 'button'; control.textContent = label; control.className = 'btn btn-secondary';
          control.style.marginRight = '8px';
          control.onclick = function () { box.close(value); };
          box.appendChild(control); return control;
        }
        // Cancel gets initial focus; Enter cannot silently approve a change.
        var initial = confirmation ? button('Cancel', 'cancel') : null;
        var accept = button(confirmation ? 'Confirm' : 'OK', 'confirmed');
        box.addEventListener('close', function () {
          var confirmed = box.returnValue === 'confirmed';
          box.remove();
          if (previous && previous.isConnected) previous.focus();
          resolve(confirmed);
        }, {once:true});
        document.body.appendChild(box);
        box.showModal(); (initial || accept).focus();
      });
    });
    pending = result.catch(function () {});
    return result;
  }
  window.smcConfirm = function (message) {
    return embedded ? dialog(message, true) : Promise.resolve(window.confirm(message));
  };
  if (embedded) {
    window.alert = function (message) { void dialog(message, false); };
    document.addEventListener('DOMContentLoaded', function () {
      // Selecting a folder in VS Code already supplied the project. Show scope
      // for review, without analyzing or changing any model automatically.
      if (window.smcOpenScope) window.smcOpenScope();
      var body = document.getElementById('setupBody');
      var toggle = document.getElementById('btnToggleSetup');
      if (body && toggle && body.classList.contains('hidden')) toggle.click();
      var status = document.getElementById('projectStatus');
      if (status && typeof initialConfig !== 'undefined') status.textContent = 'Project: ' + initialConfig.defaultRoot;
    });
  }
})();
