var CACHE_NAME = "oo-shell-v1";
var SHELL = ["/", "/assets/site-nav.css", "/assets/site.css", "/assets/tools.css", "/assets/config.js", "/assets/site.js", "/assets/logo.png"];

self.addEventListener("install", function (event) {
  event.waitUntil(caches.open(CACHE_NAME).then(function (cache) { return cache.addAll(SHELL); }).then(function () { return self.skipWaiting(); }));
});

self.addEventListener("activate", function (event) {
  event.waitUntil(caches.keys().then(function (keys) {
    return Promise.all(keys.filter(function (key) { return key !== CACHE_NAME; }).map(function (key) { return caches.delete(key); }));
  }).then(function () { return self.clients.claim(); }));
});

function networkFirst(request) {
  return fetch(request).then(function (response) {
    if (response && response.ok) {
      var copy = response.clone();
      caches.open(CACHE_NAME).then(function (cache) { cache.put(request, copy); });
    }
    return response;
  }).catch(function () { return caches.match(request); });
}

function cacheFirst(request) {
  return caches.match(request).then(function (cached) {
    if (cached) return cached;
    return fetch(request).then(function (response) {
      if (response && response.ok) {
        var copy = response.clone();
        caches.open(CACHE_NAME).then(function (cache) { cache.put(request, copy); });
      }
      return response;
    });
  });
}

self.addEventListener("fetch", function (event) {
  var request = event.request;
  if (request.method !== "GET") return;
  var url = new URL(request.url);
  if (url.protocol === "chrome-extension:" || url.protocol === "moz-extension:") return;
  var isApi = url.hostname === "api.warframestat.us" || url.pathname.indexOf("/api/") === 0;
  if (isApi) { event.respondWith(networkFirst(request)); return; }
  var isShell = url.origin === self.location.origin && (request.mode === "navigate" || /\.(?:html|css|js|png)$/i.test(url.pathname));
  if (isShell) event.respondWith(cacheFirst(request));
});
