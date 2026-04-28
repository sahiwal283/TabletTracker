/* Legacy wall script (non-React fallback).
 * Intentionally honest: no synthetic machine/OEE data.
 */
(function () {
  var root = document.getElementById("ops-root");
  if (!root) return;
  var snapshotUrl = root.getAttribute("data-snapshot-url") || "";
  function render(msg) {
    root.innerHTML = '<div style="padding:12px;color:#93c5fd;font:12px Inter,system-ui">' + msg + "</div>";
  }
  function refresh() {
    if (!snapshotUrl) {
      render("Command center data source is unavailable.");
      return;
    }
    fetch(snapshotUrl, { credentials: "same-origin" })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        var machines = (data && data.machines) || [];
        var live = machines.filter(function (m) { return m.status === "running"; }).length;
        render("Legacy wall mode: " + live + " live stations. Use /command-center/ops-tv for full MES view.");
      })
      .catch(function () {
        render("Unable to load live snapshot.");
      });
  }
  refresh();
})();
