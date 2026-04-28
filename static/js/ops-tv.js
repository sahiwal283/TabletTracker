/* Shim: forwarded to ops-command-center-wall.js (avoids stale /ops-tv.js only deployments) */
(function () {
  var cur = document.currentScript;
  if (!cur || !cur.src) return;
  var u = cur.src.replace(/ops-tv\.js/i, "ops-command-center-wall.js");
  if (u === cur.src) return;
  var s = document.createElement("script");
  s.src = u;
  s.defer = true;
  document.head.appendChild(s);
})();
