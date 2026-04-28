/**
 * Pill Packing Command Center — full board (single JSON snapshot + poll).
 */
(function () {
  var POLL_MS = 10000;
  var root = document.getElementById("pcb-root");
  if (!root) return;
  var snapshotUrl = root.getAttribute("data-snapshot-url");

  var charts = { trend: null, cycle: null, oee: null };

  function esc(s) {
    if (s == null) return "";
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  function fmtTime(ms) {
    if (!ms) return "—";
    var d = new Date(ms);
    return d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  }

  function fmtPct(p) {
    if (p == null || p === "") return "—";
    var n = Number(p);
    if (isNaN(n)) return "—";
    var sign = n > 0 ? "↑" : n < 0 ? "↓" : "";
    return sign + " " + Math.abs(n).toFixed(1) + "%";
  }

  function kpiIcon(kind) {
    var o = { w: 14, h: 14, v: "0 0 24 24", f: "currentColor" };
    var paths = {
      bag: '<path d="M6 6h12v12H6z" fill="none" stroke="currentColor" stroke-width="1.8"/>',
      bars: '<path d="M4 18V6h3v12H4zm5-8v8h3V10H9zm5-5v13h3V5h-3z"/>',
      cycle: '<path d="M12 6V3L8 7l4 4V8c2.76 0 5 2.24 5 5s-2.24 5-5 5-5-2.24-5-5H7c0 3.87 3.13 7 7 7s7-3.13 7-7-3.13-7-7-7z"/>',
      clock: '<path d="M11.99 2C6.47 2 2 6.48 2 12s4.47 10 9.99 10C17.52 22 22 17.52 22 12S17.52 2 11.99 2zM12 20c-4.42 0-8-3.58-8-8s3.58-8 8-8 8 3.58 8 8-3.58 8-8 8zm.5-13H11v6l5.25 3.15.75-1.23-4.5-2.67z"/>',
      gauge: '<path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 18c-4.42 0-8-3.58-8-8s3.58-8 8-8 8 3.58 8 8-3.58 8-8 8z"/><path d="M12 6v6l4 2"/>',
      target: '<circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" stroke-width="1.5"/><circle cx="12" cy="12" r="4"/>',
      warn: '<path d="M1 21h22L12 2 1 21zm12-3h-2v-2h2v2zm0-4h-2v-4h2v4z"/>',
    };
    var p = paths[kind] || paths.bars;
    return (
      '<svg class="pcb-tile-ic" viewBox="' +
      o.v +
      '" width="' +
      o.w +
      '" height="' +
      o.h +
      '" aria-hidden="true">' +
      p +
      "</svg>"
    );
  }

  function renderKpis(pb) {
    var el = document.getElementById("pcb-kpi-row");
    if (!el || !pb || !pb.kpis) return;
    var kinds = ["bag", "bars", "cycle", "clock", "gauge", "target", "warn"];
    el.innerHTML = pb.kpis
      .map(function (k, i) {
        var ic = kinds[i] || "bars";
        var valHtml = "";
        var deltaHtml = "";
        if (k.id === "bags" || k.id === "units" || k.id === "cycles") {
          valHtml =
            '<div class="pcb-tile-value pcb-tile-value--green">' + esc(k.value) + "</div>";
          deltaHtml =
            '<div class="pcb-tile-delta pcb-tile-delta--up">' +
            fmtPct(k.delta_pct) +
            " " +
            esc(k.subtitle || "") +
            "</div>";
        } else if (k.id === "avg_cycle") {
          valHtml = '<div class="pcb-tile-value">' + esc(k.value) + "</div>";
          var dm = k.delta_min;
          deltaHtml =
            '<div class="pcb-tile-delta">' +
            (dm != null ? "↓ " + esc(String(dm)) + "m " : "") +
            esc(k.subtitle || "") +
            "</div>";
        } else if (k.id === "oee") {
          valHtml =
            '<div class="pcb-tile-value pcb-tile-value--green">' +
            (k.value_pct != null ? k.value_pct.toFixed(1) + "%" : "—") +
            "</div>";
          deltaHtml =
            '<div class="pcb-tile-delta">' +
            fmtPct(k.delta_pct) +
            " " +
            esc(k.subtitle || "") +
            "</div>";
        } else if (k.id === "on_time") {
          valHtml =
            '<div class="pcb-tile-value pcb-tile-value--rose">' +
            (k.value_pct != null ? k.value_pct.toFixed(1) + "%" : "—") +
            "</div>";
          deltaHtml = '<div class="pcb-tile-delta">vs floor SLA</div>';
        } else if (k.id === "rework") {
          valHtml =
            '<div class="pcb-tile-value pcb-tile-value--orange">' +
            (k.value_pct != null ? k.value_pct.toFixed(2) + "%" : "—") +
            "</div>";
          deltaHtml =
            '<div class="pcb-tile-delta">' + esc(k.subtitle || "") + "</div>";
        } else {
          valHtml = '<div class="pcb-tile-value">—</div>";
        }
        return (
          '<div class="pcb-tile" data-kpi="' +
          esc(k.id) +
          '"><div class="pcb-tile-head">' +
          '<div class="pcb-tile-title">' +
          esc(k.label) +
          "</div>" +
          kpiIcon(ic) +
          "</div>" +
          valHtml +
          deltaHtml +
          "</div>"
        );
      })
      .join("");
  }

  function renderLifelines(pb) {
    var el = document.getElementById("pcb-lifelines");
    if (!el || !pb || !pb.lifelines) return;
    el.innerHTML = pb.lifelines
      .map(function (L) {
        var steps = (L.steps || [])
          .map(function (s, idx, arr) {
            var st = s.staging ? "pcb-step pcb-step--staging" : "pcb-step";
            var seg =
              '<span class="' +
              st +
              '"><span class="pcb-step-num">' +
              s.n +
              "</span> " +
              esc(s.label) +
              "</span>";
            if (idx < arr.length - 1) seg += '<span class="pcb-arrow">→</span>';
            return seg;
          })
          .join("");
        return (
          '<article class="pcb-lifecycle">' +
          "<h3>" +
          esc(L.title) +
          "</h3>" +
          '<div class="pcb-sku">SKU: <strong>' +
          esc(L.sku) +
          "</strong></div>" +
          '<div class="pcb-flow-steps">' +
          steps +
          "</div>" +
          '<div class="pcb-lifecycle-foot">' +
          (L.footer_ok ? "✓ Full production cycle complete" : "○ In progress / idle") +
          "</div>" +
          "</article>"
        );
      })
      .join("");
  }

  function renderAlerts(activity) {
    var el = document.getElementById("pcb-alert-list");
    if (!el) return;
    var items = (activity || []).slice(0, 8);
    if (!items.length) {
      el.innerHTML =
        '<div class="pcb-alert pcb-alert--info"><span class="pcb-sev">INFO</span> — No alerts at this snapshot.</div>';
      return;
    }
    el.innerHTML = items
      .map(function (a) {
        var sev = (a.severity || "info").toLowerCase();
        var mod =
          sev === "alert"
            ? "pcb-alert pcb-alert--alert"
            : sev === "warn"
              ? "pcb-alert pcb-alert--warn"
              : "pcb-alert";
        return (
          '<div class="' +
          mod +
          '">' +
          "<strong>" +
          fmtTime(a.at_ms) +
          "</strong> — " +
          esc(a.message || "") +
          ' <span class="pcb-sev">' +
          sev.toUpperCase() +
          "</span></div>"
        );
      })
      .join("");
  }

  function groupMachines(machines) {
    var out = { blister: [], bottle: [], card: [] };
    (machines || []).forEach(function (m) {
      var k = String(m.station_kind || "").toLowerCase();
      if (k === "blister") out.blister.push(m);
      else if (k === "packaging") out.card.push(m);
      else out.bottle.push(m);
    });
    return out;
  }

  function renderMachines(machines) {
    var wrap = document.getElementById("pcb-machine-groups");
    if (!wrap) return;
    var g = groupMachines(machines);
    function cards(arr, title) {
      if (!arr.length)
        return (
          '<div class="pcb-line-group"><h4>' +
          esc(title) +
          '</h4><div class="pcb-machine-grid"><div class="pcb-mcard">—</div></div></div>'
        );
      var inner = arr
        .map(function (m) {
          var running = String(m.status) === "running";
          var c = running ? "pcb-mcard pcb-mcard-run" : "pcb-mcard pcb-mcard-idle";
          var st = running ? "run" : "idle";
          return (
            '<div class="' +
            c +
            '"><div class="pcb-mcard-name">' +
            esc(m.display_name) +
            "</div>" +
            '<div class="pcb-mcard-kind">' +
            esc(m.station_kind) +
            "</div>" +
            '<div class="pcb-mcard-st ' +
            st +
            '">' +
            (running ? "RUNNING" : "IDLE") +
            "</div>" +
            '<div>Bags today · ' +
            esc(String(m.output_today ?? "—")) +
            "</div>" +
            '<div>' +
            esc(String(m.product || "—")) +
            "</div>" +
            "</div>"
          );
        })
        .join("");
      return (
        '<div class="pcb-line-group"><h4>' +
        esc(title) +
        '</h4><div class="pcb-machine-grid">' +
        inner +
        "</div></div>"
      );
    }
    wrap.innerHTML =
      cards(g.blister, "Blister line machines") +
      cards(g.bottle, "Bottle line machines") +
      cards(g.card, "Card line machines");
  }

  function renderTables(pb) {
    var inv = document.getElementById("pcb-inv-body");
    if (inv && pb && pb.inventory) {
      if (!pb.inventory.length) {
        inv.innerHTML = "<tr><td colspan='5'>No rows</td></tr>";
      } else {
        inv.innerHTML = pb.inventory
          .map(function (r) {
            return (
              "<tr><td>" +
              esc(r.sku) +
              "</td><td>" +
              esc(r.bag_id) +
              "</td><td>" +
              esc(r.units) +
              "</td><td>" +
              esc(r.qty) +
              "</td><td class='pcb-st-ok'>" +
              esc(r.status) +
              "</td></tr>"
            );
          })
          .join("");
      }
    }
    var sku = document.getElementById("pcb-sku-body");
    if (sku && pb && pb.sku_table) {
      if (!pb.sku_table.length) sku.innerHTML = "<tr><td colspan='5'>No rows</td></tr>";
      else {
        sku.innerHTML = pb.sku_table
          .map(function (r) {
            return (
              "<tr><td>" +
              esc(r.sku) +
              "</td><td>" +
              esc(r.line) +
              "</td><td>" +
              esc(r.units) +
              "</td><td>" +
              esc(r.bags) +
              "</td><td>" +
              esc(r.cycles) +
              "</td></tr>"
            );
          })
          .join("");
      }
    }
    var stg = document.getElementById("pcb-staging-body");
    if (stg && pb && pb.staging) {
      if (!pb.staging.length) stg.innerHTML = "<tr><td colspan='5'>No staging rows</td></tr>";
      else {
        stg.innerHTML = pb.staging
          .map(function (r) {
            return (
              "<tr><td>" +
              esc(r.line) +
              "</td><td>" +
              esc(r.area_name) +
              "</td><td>" +
              esc(r.bags) +
              "</td><td>" +
              esc(r.oldest_bag) +
              "</td><td>" +
              esc(r.minutes) +
              "</td></tr>"
            );
          })
          .join("");
      }
    }
    var dt = document.getElementById("pcb-downtime-body");
    if (dt) {
      if (!pb || !pb.downtime || !pb.downtime.length) {
        dt.innerHTML = "<tr><td colspan='4'>No downtime logged</td></tr>";
      } else {
        dt.innerHTML = pb.downtime
          .map(function (r) {
            return (
              "<tr><td>" +
              esc(r.line) +
              "</td><td>" +
              esc(r.dur) +
              "</td><td>" +
              esc(r.reason) +
              "</td><td>" +
              esc(r.impact) +
              "</td></tr>"
            );
          })
          .join("");
      }
    }
    var tm = document.getElementById("pcb-team-body");
    if (tm && pb && pb.team) {
      if (!pb.team.length) tm.innerHTML = "<tr><td colspan='4'>No rows</td></tr>";
      else {
        tm.innerHTML = pb.team
          .map(function (r) {
            return (
              "<tr><td>" +
              esc(r.team) +
              "</td><td>" +
              esc(r.line) +
              "</td><td>" +
              esc(r.cycles) +
              "</td><td>" +
              esc(r.units) +
              "</td></tr>"
            );
          })
          .join("");
      }
    }
    var tl = document.getElementById("pcb-timeline-body");
    if (tl && pb && pb.timeline) {
      if (!pb.timeline.length) tl.innerHTML = "<tr><td colspan='7'>No rows</td></tr>";
      else {
        tl.innerHTML = pb.timeline
          .map(function (r) {
            var trc = r.alert ? " class='pcb-timeline-row--alert'" : "";
            return (
              "<tr" +
              trc +
              "><td>" +
              fmtTime(r.at_ms) +
              "</td><td>" +
              esc(r.line) +
              "</td><td>" +
              esc(r.machine) +
              "</td><td>" +
              esc(r.event) +
              "</td><td>" +
              esc(r.bag_id) +
              "</td><td>" +
              esc(r.sku) +
              "</td><td>" +
              esc(r.employee) +
              "</td></tr>"
            );
          })
          .join("");
      }
    }
  }

  function updateCharts(pb) {
    if (typeof Chart === "undefined" || !pb) return;
    var tr = document.getElementById("pcb-chart-trend");
    var cy = document.getElementById("pcb-chart-cycle");
    var oe = document.getElementById("pcb-chart-oee");
    var t = pb.trend || {};
    var labels = t.labels || [];
    var blister = t.blister || [];
    var bottle = t.bottle || [];
    var card = t.card || [];

    if (tr && !charts.trend) {
      charts.trend = new Chart(tr, {
        type: "line",
        data: { labels: labels, datasets: [] },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: { legend: { labels: { color: "#cbd5e1" } } },
          scales: {
            x: { ticks: { color: "#94a3b8", maxTicksLimit: 8 }, grid: { color: "rgba(148,163,184,0.1)" } },
            y: { ticks: { color: "#94a3b8" }, grid: { color: "rgba(148,163,184,0.1)" } },
          },
        },
      });
    }
    if (charts.trend) {
      charts.trend.data.labels = labels;
      charts.trend.data.datasets = [
        { label: "Blister line", data: blister, borderColor: "#38bdf8", tension: 0.2 },
        { label: "Bottle line", data: bottle, borderColor: "#4ade80", tension: 0.2 },
        { label: "Card line", data: card, borderColor: "#a78bfa", tension: 0.2 },
      ];
      charts.trend.update();
    }

    var ca = pb.cycle_analysis || {};
    if (cy && !charts.cycle) {
      charts.cycle = new Chart(cy, {
        type: "bar",
        data: { labels: ca.labels || [], datasets: [] },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: { legend: { labels: { color: "#cbd5e1" } } },
          scales: {
            x: { ticks: { color: "#94a3b8" }, grid: { display: false } },
            y: { ticks: { color: "#94a3b8" }, grid: { color: "rgba(148,163,184,0.1)" }, beginAtZero: true },
          },
        },
      });
    }
    if (charts.cycle) {
      charts.cycle.data.labels = ca.labels || [];
      charts.cycle.data.datasets = [
        {
          label: "Today",
          data: ca.today || [],
          backgroundColor: "rgba(56,189,248,0.55)",
          borderColor: "#38bdf8",
          borderWidth: 1,
        },
        {
          label: "Yesterday",
          data: ca.yesterday || [],
          backgroundColor: "rgba(148,163,184,0.25)",
          borderColor: "#94a3b8",
          borderWidth: 1,
        },
      ];
      charts.cycle.update();
    }

    var oee = pb.oee_donut || {};
    if (oe && !charts.oee) {
      charts.oee = new Chart(oe, {
        type: "doughnut",
        data: { labels: [], datasets: [{ data: [], backgroundColor: ["#38bdf8", "#fb923c", "#4ade80"] }] },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          cutout: "62%",
          plugins: {
            legend: { position: "bottom", labels: { color: "#cbd5e1", font: { size: 10 } } },
          },
        },
      });
    }
    if (charts.oee) {
      charts.oee.data.labels = ["Availability", "Performance", "Quality"];
      charts.oee.data.datasets = [
        {
          data: [
            oee.availability || 0,
            oee.performance || 0,
            oee.quality || 0,
          ],
          backgroundColor: ["#38bdf8", "#fb923c", "#4ade80"],
        },
      ];
      charts.oee.options.plugins = charts.oee.options.plugins || {};
      charts.oee.update();
    }
  }

  function apply(data) {
    if (!data || data.error) return;
    var pb = data.pill_board || {};
    renderKpis(pb);
    renderLifelines(pb);
    renderAlerts(data.activity);
    renderMachines(data.machines);
    renderTables(pb);
    updateCharts(pb);
    var ft = document.getElementById("pcb-footer-ts");
    if (ft)
      ft.textContent = new Date().toLocaleTimeString([], {
        hour: "numeric",
        minute: "2-digit",
        second: "2-digit",
      });
  }

  function poll() {
    fetch(snapshotUrl, { credentials: "same-origin" })
      .then(function (r) {
        return r.json();
      })
      .then(apply)
      .catch(function () {});
  }

  (function bootstrap() {
    var node = document.getElementById("ops-tv-initial-data");
    if (!node || !node.textContent) return;
    var raw = node.textContent.trim();
    if (!raw || raw === "{}") return;
    try {
      var payload = JSON.parse(raw);
      if (payload && !payload.error) apply(payload);
    } catch (e) {}
  })();

  poll();
  setInterval(poll, POLL_MS);

  var clockEl = document.getElementById("pcb-top-clock");
  if (clockEl) {
    function tick() {
      clockEl.textContent = new Date().toLocaleString([], {
        month: "short",
        day: "numeric",
        year: "numeric",
        hour: "numeric",
        minute: "2-digit",
      });
    }
    tick();
    setInterval(tick, 1000);
  }
})();
