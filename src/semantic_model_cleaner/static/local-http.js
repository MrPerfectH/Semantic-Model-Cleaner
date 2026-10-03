/* Shared by both layouts: keep the launch token in same-origin request headers. */
(function () {
  'use strict';
  var token = document.querySelector('meta[name="smc-local-token"]').content;

  window.smcFetch = function (input, options) {
    var url = new URL(input, window.location.href);
    if (url.origin !== window.location.origin || !url.pathname.startsWith('/api/')) {
      return Promise.reject(new Error('Local API requests must use the application origin.'));
    }
    options = Object.assign({}, options || {});
    var headers = new Headers(options.headers || {});
    headers.set('X-SMC-Token', token);
    var method = (options.method || 'GET').toUpperCase();
    if (!['GET', 'HEAD', 'OPTIONS'].includes(method) && !headers.has('Content-Type')) {
      headers.set('Content-Type', 'application/json');
    }
    options.headers = headers;
    options.mode = 'same-origin';
    options.credentials = 'same-origin';
    options.redirect = 'error';
    return fetch(url.href, options);
  };

  window.smcDownload = async function (url) {
    try {
      var response = await window.smcFetch(url);
      if (!response.ok) {
        var error = await response.json();
        throw new Error(error.error || 'Export failed.');
      }
      var disposition = response.headers.get('Content-Disposition') || '';
      var utf8Name = /filename\*=UTF-8''([^;]+)/i.exec(disposition);
      var plainName = /filename="?([^";]+)"?/i.exec(disposition);
      var name = utf8Name ? decodeURIComponent(utf8Name[1]) : plainName ? plainName[1] : 'analysis';
      var blobUrl = URL.createObjectURL(await response.blob());
      var link = document.createElement('a');
      link.href = blobUrl;
      link.download = name;
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(function () { URL.revokeObjectURL(blobUrl); }, 1000);
    } catch (error) {
      window.alert(error.message || 'Export failed.');
    }
  };
}());
