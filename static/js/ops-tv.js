/* Backward-compatible loader for legacy /static/js/ops-tv.js references. */
(function () {
  var cur = document.currentScript;
  if (!cur || !cur.src) return;
  var next = cur.src.replace(/ops-tv\.js/i, "ops-command-center-wall.js");
  if (next === cur.src) return;
  var s = document.createElement("script");
  s.defer = true;
  s.src = next;
  document.head.appendChild(s);
})();
