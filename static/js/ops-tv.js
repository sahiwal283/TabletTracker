/**
 * TV operations board — polls snapshot API, renders tiles + Chart.js (no tables).
 */
(function () {
  var POLL_MS = 8000;
  var root = document.getElementById("ops-root");
  if (!root) return;

  var url = root.getAttribute("data-snapshot-url");
  var cardsEl = document.getElementById("ops-cards");
  var feedEl = document.getElementById("ops-feed-list");
  var headEl = document.getElementById("ops-head");
  var clockEl = document.getElementById("ops-clock");

  var charts = {
    line: null,
    multi: null,
    bar: null,
    idle: null,
    donut: null,
  };

  var chartCommon = {
    responsive: true,
    maintainAspectRatio: false,
    animation: { duration: 450, easing: "easeOutQuart" },
    plugins: {
      legend: {
        display: true,
        labels: { color: "#9aa8b8", font: { size: 9 }, boxWidth: 10 },
      },
    },
    scales: {},
  };

  function fmtTime(ms) {
    if (!ms) return "--:--:--";
    var total = Math.max(0, Math.floor((Date.now() - ms) / 1000));
    var h = Math.floor(total / 3600);
    var m = Math.floor((total % 3600) / 60);
    var s = total % 60;
    return String(h).padStart(2, "0") + ":" + String(m).padStart(2, "0") + ":" + String(s).padStart(2, "0");
  }

  function fmtFeedTime(ms) {
    var d = new Date(ms);
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  }

  function drawSpark(canvas, values) {
    if (!canvas || !values || !values.length) return;
    var dpr = window.devicePixelRatio || 1;
    var W = canvas.offsetWidth;
    var H = canvas.offsetHeight;
    if (W < 2 || H < 2) return;
    canvas.width = W * dpr;
    canvas.height = H * dpr;
    var ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);
    var max = Math.max.apply(null, values.concat([1]));
    ctx.beginPath();
    ctx.strokeStyle = "rgba(0, 212, 255, 0.85)";
    ctx.lineWidth = 2;
    values.forEach(function (v, i) {
      var x = (i / (values.length - 1 || 1)) * (W - 4) + 2;
      var y = H - 4 - (v / max) * (H - 8);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.stroke();
    ctx.lineTo(W - 2, H - 2);
    ctx.lineTo(2, H - 2);
    ctx.fillStyle = "rgba(0, 212, 255, 0.08)";
    ctx.fill();
  }

  function statusOrder(s) {
    if (s === "running") return 0;
    if (s === "paused") return 1;
    return 2;
  }

  function renderFlow(flow) {
    var el = document.getElementById("ops-flow");
    var bn = document.getElementById("ops-bottleneck");
    if (!el) return;
    if (!flow || !flow.pipeline || !flow.pipeline.length) {
      el.innerHTML = "";
      if (bn) bn.innerHTML = "";
      return;
    }
    var parts = [];
    flow.pipeline.forEach(function (node, i) {
      if (i > 0) {
        parts.push('<span class="ops-flow-arrow" aria-hidden="true">→</span>');
      }
      var al = node.alert || "ok";
      var mod = al === "warn" || al === "crit" ? " ops-flow-node--" + al : "";
      var dm = node.max_delay_min;
      var av = node.avg_delay_min;
      var delayTxt = "";
      if (dm != null) {
        delayTxt =
          '<div class="ops-flow-delay">max ' +
          dm +
          "m · avg " +
          (av != null ? av + "m" : "—") +
          "</div>";
      }
      parts.push(
        '<div class="ops-flow-node' +
        mod +
        '" data-stage="' +
        String(node.id || "").replace(/"/g, "") +
        '">' +
        '<div class="ops-flow-label">' +
        String(node.label || "").replace(/</g, "&lt;") +
        "</div>" +
        '<div class="ops-flow-wip">' +
        (node.wip != null ? node.wip : "—") +
        "</div>" +
        '<div class="ops-flow-sub">' +
        String(node.subtitle || "").replace(/</g, "&lt;") +
        "</div>" +
        delayTxt +
        "</div>"
      );
    });
    el.innerHTML = parts.join("");
    if (bn && flow.bottleneck) {
      var b = flow.bottleneck;
      bn.innerHTML =
        '<div class="ops-bn-title">Bottleneck</div>' +
        '<div class="ops-bn-reason">' +
        String(b.reason || "").replace(/</g, "&lt;") +
        "</div>" +
        '<div class="ops-bn-hint">' +
        String(b.hint || "").replace(/</g, "&lt;") +
        "</div>";
    }
  }

  function renderHeader(data) {
    if (!headEl) return;
    var k = data.kpis || {};
    var t = data.targets || {};
    var target = t.daily_output_tablets || 800;
    var down = k.down_machines || 0;
    var pct = k.throughput_pct || 0;
    var cycle = k.avg_cycle_time_min;
    var cycleStr = cycle != null ? cycle + " min" : "—";

    headEl.innerHTML =
      '<div class="ops-kpi' +
      (down > 0 ? " ops-kpi--alert" : "") +
      '">' +
      '<div class="ops-kpi-label">Active</div>' +
      '<div class="ops-kpi-value ops-kpi-value--run">' +
      (k.active_machines != null ? k.active_machines : "—") +
      "</div></div>" +
      '<div class="ops-kpi">' +
      '<div class="ops-kpi-label">Idle</div>' +
      '<div class="ops-kpi-value ops-kpi-value--idle">' +
      (k.idle_machines != null ? k.idle_machines : "—") +
      "</div></div>" +
      '<div class="ops-kpi' +
      (down > 0 ? " ops-kpi--alert" : "") +
      '">' +
      '<div class="ops-kpi-label">Down</div>' +
      '<div class="ops-kpi-value ops-kpi-value--down">' +
      down +
      "</div>" +
      (down > 0 ? '<div class="ops-kpi-sub">Check stations</div>' : "") +
      "</div>" +
      '<div class="ops-kpi">' +
      '<div class="ops-kpi-label">Output today</div>' +
      '<div class="ops-kpi-value ops-kpi-value--accent">' +
      (k.total_output_today != null ? k.total_output_today.toLocaleString() : "0") +
      "</div>" +
      '<div class="ops-kpi-sub">tablets · target ' +
      target.toLocaleString() +
      "</div></div>" +
      '<div class="ops-kpi">' +
      '<div class="ops-kpi-label">Throughput vs target</div>' +
      '<div class="ops-kpi-value ops-kpi-value--accent">' +
      pct +
      "%</div>" +
      '<div class="ops-kpi-sub">of daily target</div></div>' +
      '<div class="ops-kpi">' +
      '<div class="ops-kpi-label">Avg cycle</div>' +
      '<div class="ops-kpi-value">' +
      cycleStr +
      "</div>" +
      '<div class="ops-kpi-sub">claim → seal (median)</div></div>';
  }

  function renderCards(machines) {
    if (!cardsEl) return;
    var sorted = (machines || []).slice().sort(function (a, b) {
      var d = statusOrder(a.status) - statusOrder(b.status);
      if (d !== 0) return d;
      return (b.output_today || 0) - (a.output_today || 0);
    });
    cardsEl.innerHTML = sorted
      .map(function (m) {
        var st = m.status || "idle";
        var timer =
          st !== "idle" && m.occupancy_started_at_ms
            ? '<div class="ops-card-timer" data-start-ms="' +
              m.occupancy_started_at_ms +
              '">' +
              fmtTime(m.occupancy_started_at_ms) +
              "</div>"
            : '<div class="ops-card-timer">—</div>';
        return (
          '<article class="ops-card ops-card--' +
          st +
          '">' +
          '<div class="ops-card-name">' +
          (m.display_name || "Station") +
          "</div>" +
          '<div class="ops-card-kind">' +
          (m.station_kind || "") +
          "</div>" +
          '<div class="ops-card-status ops-card-status--' +
          st +
          '">' +
          st +
          "</div>" +
          '<div class="ops-card-product" title="' +
          (m.product || "").replace(/"/g, "&quot;") +
          '">' +
          (m.product || "—") +
          "</div>" +
          timer +
          '<div class="ops-card-out">Out today · ' +
          (m.output_today != null ? m.output_today.toLocaleString() : "0") +
          " tablets</div>" +
          '<canvas class="ops-card-spark" width="200" height="36" data-spark="' +
          encodeURIComponent(JSON.stringify(m.sparkline || [])) +
          '"></canvas>' +
          "</article>"
        );
      })
      .join("");

    cardsEl.querySelectorAll("canvas.ops-card-spark").forEach(function (cnv) {
      try {
        var raw = decodeURIComponent(cnv.getAttribute("data-spark") || "[]");
        drawSpark(cnv, JSON.parse(raw));
      } catch (e) {}
    });
  }

  function tickTimers() {
    document.querySelectorAll(".ops-card-timer[data-start-ms]").forEach(function (el) {
      var ms = parseInt(el.getAttribute("data-start-ms"), 10);
      if (ms) el.textContent = fmtTime(ms);
    });
  }

  function renderFeed(items) {
    if (!feedEl) return;
    feedEl.innerHTML = (items || [])
      .slice(0, 40)
      .map(function (it) {
        var sev = it.severity || "info";
        return (
          '<div class="ops-feed-item ops-feed-item--' +
          sev +
          '"><span class="ops-feed-time">' +
          fmtFeedTime(it.at_ms) +
          "</span>" +
          (it.message || "").replace(/</g, "&lt;") +
          "</div>"
        );
      })
      .join("");
  }

  function ensureCharts(labels) {
    if (typeof Chart === "undefined") return;

    var darkScales = {
      x: {
        ticks: { color: "#6a7a8a", maxRotation: 0, font: { size: 9 } },
        grid: { color: "rgba(0,255,200,0.06)" },
      },
      y: {
        ticks: { color: "#6a7a8a", font: { size: 9 } },
        grid: { color: "rgba(0,255,200,0.06)" },
      },
    };

    if (!charts.line) {
      var el = document.getElementById("c-chart-line");
      if (el)
        charts.line = new Chart(el, {
          type: "line",
          data: { labels: labels, datasets: [] },
          options: Object.assign({}, chartCommon, {
            scales: darkScales,
            plugins: { legend: { labels: { color: "#9aa8b8", font: { size: 9 } } } },
          }),
        });
    }
    if (!charts.multi) {
      var el2 = document.getElementById("c-chart-multi");
      if (el2)
        charts.multi = new Chart(el2, {
          type: "line",
          data: { labels: labels, datasets: [] },
          options: Object.assign({}, chartCommon, {
            scales: darkScales,
            plugins: { legend: { display: true, position: "bottom" } },
          }),
        });
    }
    if (!charts.bar) {
      var el3 = document.getElementById("c-chart-bar");
      if (el3)
        charts.bar = new Chart(el3, {
          type: "bar",
          data: { labels: [], datasets: [] },
          options: Object.assign({}, chartCommon, {
            indexAxis: "y",
            scales: {
              x: {
                ticks: { color: "#6a7a8a", font: { size: 9 } },
                grid: { color: "rgba(0,255,200,0.06)" },
              },
              y: {
                ticks: { color: "#9aa8b8", font: { size: 9 } },
                grid: { display: false },
              },
            },
            plugins: { legend: { display: false } },
          }),
        });
    }
    if (!charts.idle) {
      var el4 = document.getElementById("c-chart-idle");
      if (el4)
        charts.idle = new Chart(el4, {
          type: "bar",
          data: { labels: [], datasets: [] },
          options: Object.assign({}, chartCommon, {
            indexAxis: "y",
            scales: {
              x: {
                stacked: true,
                max: 100,
                ticks: { color: "#6a7a8a", font: { size: 9 }, callback: function (v) { return v + "%"; } },
                grid: { color: "rgba(0,255,200,0.06)" },
              },
              y: {
                stacked: true,
                ticks: { color: "#9aa8b8", font: { size: 9 } },
                grid: { display: false },
              },
            },
            plugins: { legend: { labels: { color: "#9aa8b8", font: { size: 9 } } } },
          }),
        });
    }
    if (!charts.donut) {
      var el5 = document.getElementById("c-chart-donut");
      if (el5)
        charts.donut = new Chart(el5, {
          type: "doughnut",
          data: { labels: [], datasets: [{ data: [], backgroundColor: [] }] },
          options: Object.assign({}, chartCommon, {
            cutout: "62%",
            plugins: {
              legend: { position: "right", labels: { color: "#9aa8b8", font: { size: 9 }, boxWidth: 10 } },
            },
          }),
        });
    }
  }

  var palette = [
    "#00d4ff",
    "#00ff9d",
    "#ffcc00",
    "#ff9f43",
    "#a29bfe",
    "#fd79a8",
    "#ffeaa7",
    "#74b9ff",
  ];

  function updateCharts(data) {
    if (typeof Chart === "undefined") return;
    var labels = data.hour_labels || [];
    ensureCharts(labels);

    if (charts.line) {
      charts.line.data.labels = labels;
      charts.line.data.datasets = [
        {
          label: "Actual cumulative",
          data: data.chart_cumulative_output || [],
          borderColor: "#00d4ff",
          backgroundColor: "rgba(0, 212, 255, 0.06)",
          fill: true,
          tension: 0.25,
          borderWidth: 2,
        },
        {
          label: "Target pace",
          data: data.chart_target_cumulative || [],
          borderColor: "rgba(255, 204, 0, 0.55)",
          borderDash: [6, 4],
          fill: false,
          tension: 0,
          pointRadius: 0,
          borderWidth: 2,
        },
      ];
      charts.line.update();
    }

    if (charts.multi) {
      charts.multi.data.labels = labels;
      var series = data.chart_station_series || {};
      var names = data.chart_station_names || {};
      var ds = [];
      var i = 0;
      Object.keys(series).forEach(function (sid) {
        ds.push({
          label: names[sid] || "St " + sid,
          data: series[sid],
          borderColor: palette[i % palette.length],
          backgroundColor: "transparent",
          tension: 0.2,
          borderWidth: 2,
          pointRadius: 0,
        });
        i++;
      });
      if (!ds.length) {
        ds.push({
          label: "—",
          data: labels.map(function () { return 0; }),
          borderColor: "rgba(122,138,154,0.4)",
          borderWidth: 1,
          pointRadius: 0,
        });
      }
      charts.multi.data.datasets = ds;
      charts.multi.update();
    }

    if (charts.bar) {
      var bars = data.bar_by_station || [];
      if (!bars.length) {
        charts.bar.data.labels = ["—"];
        charts.bar.data.datasets = [
          { label: "Tablets", data: [0], backgroundColor: ["rgba(122,138,154,0.4)"] },
        ];
      } else {
        charts.bar.data.labels = bars.map(function (b) { return b.name; });
        charts.bar.data.datasets = [
          {
            label: "Tablets",
            data: bars.map(function (b) { return b.output; }),
            backgroundColor: bars.map(function (_, j) {
              return palette[j % palette.length];
            }),
          },
        ];
      }
      charts.bar.update();
    }

    if (charts.idle) {
      var idles = data.idle_pct_by_station || [];
      if (!idles.length) {
        charts.idle.data.labels = ["—"];
        charts.idle.data.datasets = [
          { label: "Engaged", data: [0], backgroundColor: "rgba(0, 255, 157, 0.35)" },
          { label: "Idle / wait", data: [100], backgroundColor: "rgba(255, 204, 0, 0.35)" },
        ];
      } else {
      charts.idle.data.labels = idles.map(function (r) { return r.name; });
      charts.idle.data.datasets = [
        {
          label: "Engaged",
          data: idles.map(function (r) { return r.load_pct; }),
          backgroundColor: "rgba(0, 255, 157, 0.7)",
        },
        {
          label: "Idle / wait",
          data: idles.map(function (r) { return r.pct; }),
          backgroundColor: "rgba(255, 204, 0, 0.45)",
        },
      ];
      }
      charts.idle.update();
    }

    if (charts.donut) {
      var fb = data.flavor_breakdown || [];
      if (!fb.length) {
        charts.donut.data.labels = ["No mix yet"];
        charts.donut.data.datasets = [
          { data: [1], backgroundColor: ["rgba(122,138,154,0.35)"] },
        ];
      } else {
        charts.donut.data.labels = fb.map(function (f) { return f.label; });
        charts.donut.data.datasets = [
          {
            data: fb.map(function (f) { return f.value; }),
            backgroundColor: fb.map(function (_, j) {
              return palette[j % palette.length];
            }),
          },
        ];
      }
      charts.donut.update();
    }
  }

  function apply(data) {
    if (!data || data.error) return;
    renderHeader(data);
    renderFlow(data.flow);
    renderCards(data.machines);
    renderFeed(data.activity);
    updateCharts(data);
  }

  function poll() {
    fetch(url, { credentials: "same-origin" })
      .then(function (r) { return r.json(); })
      .then(apply)
      .catch(function () {});
  }

  poll();
  setInterval(poll, POLL_MS);
  setInterval(tickTimers, 1000);

  if (clockEl) {
    function tickClock() {
      clockEl.textContent = new Date().toLocaleString([], {
        weekday: "short",
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      });
    }
    tickClock();
    setInterval(tickClock, 1000);
  }

  window.addEventListener("resize", function () {
    document.querySelectorAll("canvas.ops-card-spark").forEach(function (cnv) {
      try {
        var raw = decodeURIComponent(cnv.getAttribute("data-spark") || "[]");
        drawSpark(cnv, JSON.parse(raw));
      } catch (e) {}
    });
  });
})();
