(function () {
  var React = window.React;
  var ReactDOM = window.ReactDOM;
  var htmVendor = window.htm;
  if (!React || !ReactDOM || !htmVendor) return;

  var html = htmVendor.bind(React.createElement);
  var useEffect = React.useEffect;
  var useMemo = React.useMemo;
  var useState = React.useState;

  function readBoot() {
    try {
      return JSON.parse(document.getElementById("mes-nav-boot").textContent || "{}");
    } catch (e) {
      return {};
    }
  }

  function readInitialTab() {
    var h = (window.location.hash || "").replace(/^#/, "").toLowerCase();
    var ok = {
      overview: 1,
      blister: 1,
      bottle: 1,
      machines: 1,
      bags: 1,
      staging: 1,
      alerts: 1,
      analytics: 1,
      users: 1,
      settings: 1,
    };
    return ok[h] ? h : "overview";
  }

  function fmtTimeMs(ms) {
    if (ms == null) return "N/A";
    var s = Math.max(0, Math.floor((Date.now() - Number(ms)) / 1000));
    var h = Math.floor(s / 3600);
    var m = Math.floor((s % 3600) / 60);
    var ss = s % 60;
    return String(h).padStart(2, "0") + ":" + String(m).padStart(2, "0") + ":" + String(ss).padStart(2, "0");
  }

  function shortClock(ms) {
    return ms ? new Date(ms).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "—";
  }

  function statusClass(status) {
    if (status === "LIVE_QR") return "is-run";
    if (status === "NO_ACTIVITY_TODAY") return "is-warn";
    if (status === "MANUAL_ENTRY") return "is-manual";
    return "is-off";
  }

  function nodeStatus(wip) {
    if (wip > 0) return "Active";
    return "Idle";
  }

  function machineSvgWrap(body, status) {
    var cls = "mes-machine-svg " + (status === "LIVE_QR" ? "run" : status === "NOT_INTEGRATED" ? "dim" : "idle");
    return html`<svg className=${cls} viewBox="0 0 220 120" role="img" aria-label="machine illustration">
      <rect x="2" y="2" width="216" height="116" rx="8" className="frame" />
      ${body}
      <circle cx="206" cy="14" r="5" className="beacon" />
    </svg>`;
  }

  function renderDPP115BlisterMachine(status) {
    return machineSvgWrap(html`
      <circle cx="26" cy="58" r="13" className="part" />
      <rect x="45" y="49" width="58" height="18" className="part" />
      <rect x="113" y="41" width="36" height="34" className="part" />
      <rect x="154" y="64" width="46" height="9" className="part" />
      <g className="pill-grid">${Array.from({ length: 5 }).map(function (_, i) {
        return html`<circle key=${i} cx=${50 + i * 10} cy="58" r="2.6" className="pill"/>`;
      })}</g>
    `, status);
  }

  function renderHeatPressMachine(status) {
    return machineSvgWrap(html`
      <rect x="40" y="28" width="140" height="18" className="part" />
      <rect x="35" y="70" width="150" height="16" className="part" />
      <line x1="52" y1="46" x2="52" y2="70" className="line" />
      <line x1="168" y1="46" x2="168" y2="70" className="line" />
      <path d="M90 52 l8 10 l8-10" className="arrow" />
      <path d="M120 52 l8 10 l8-10" className="arrow" />
    `, status);
  }

  function renderStickeringMachine(status) {
    return machineSvgWrap(html`
      <circle cx="42" cy="42" r="14" className="part" />
      <rect x="58" y="35" width="56" height="14" className="part" />
      <rect x="120" y="34" width="18" height="28" className="part" />
      <rect x="142" y="68" width="54" height="9" className="part" />
      <path d="M58 42 h-10" className="line" />
    `, status);
  }

  function renderBottleSealingMachine(status) {
    return machineSvgWrap(html`
      <path d="M58 80 h24 l6-28 h-8 v-11 h-20 v11 h-8 z" className="part" />
      <rect x="98" y="34" width="20" height="26" className="part" />
      <ellipse cx="156" cy="78" rx="32" ry="12" className="part" />
      <rect x="130" y="72" width="52" height="8" className="part" />
    `, status);
  }

  function renderPackagingStation(status) {
    return machineSvgWrap(html`
      <rect x="36" y="68" width="58" height="24" className="part" />
      <rect x="104" y="60" width="38" height="32" className="part" />
      <rect x="146" y="52" width="40" height="40" className="part" />
      <line x1="36" y1="68" x2="188" y2="68" className="line" />
    `, status);
  }

  function renderMachineIllustration(slot, status) {
    if (slot === 1) return renderDPP115BlisterMachine(status);
    if (slot === 2 || slot === 3) return renderHeatPressMachine(status);
    if (slot === 4) return renderStickeringMachine(status);
    if (slot === 5) return renderBottleSealingMachine(status);
    return renderPackagingStation(status);
  }

  function KpiCard(props) {
    return html`<div className="mes-kpi-card">
      <div className="label">${props.label}</div>
      <div className="value">${props.value}</div>
      ${props.spark && props.spark.length > 1
        ? html`<svg className="spark" viewBox="0 0 100 18">${props.spark.map(function (v, i) {
            var x = (i / (props.spark.length - 1)) * 100;
            var max = Math.max.apply(null, props.spark);
            var y = 17 - (max ? (v / max) * 15 : 0);
            return html`<circle key=${i} cx=${x} cy=${y} r="1.2" className="pt" />`;
          })}</svg>`
        : html`<div className="spark-empty">No data</div>`}
    </div>`;
  }

  function stagesToNodes(stages) {
    return (stages || []).map(function (s) {
      var wip = Number(s.wip != null ? s.wip : s.queue_depth || 0);
      var bags = Number(s.bags != null ? s.bags : wip);
      var dwell = s.dwell != null && String(s.dwell) !== "" ? String(s.dwell) : s.alert_note ? String(s.alert_note) : "—";
      if (s.bottleSealIntegrated === false) dwell = "Awaiting integration";
      return { name: s.title || s.key || "—", wip: wip, bags: bags, dwell: dwell };
    });
  }

  function ProcessLane(props) {
    if (props.lane) {
      var lane = props.lane;
      var nodes = stagesToNodes(lane.stages);
      var sub = lane.subtitle ? html`<span>${lane.subtitle}</span>` : lane.sku && lane.sku !== "—" ? html`<span>SKU ${lane.sku}</span>` : null;
      return html`<div className=${"mes-lane " + (props.dimmed ? "dim" : "")}>
        <div className="lane-title">${lane.title}${sub}</div>
        <div className="lane-track">${nodes.map(function (n, idx) {
          return html`<div key=${idx} className="lane-node">
            <div className="n-top"><strong>${n.name}</strong><em>${nodeStatus(n.wip)}</em></div>
            <div className="n-meta">WIP ${n.wip} · bags ${n.bags}</div>
            <div className="n-meta">Dwell ${n.dwell}</div>
          </div>`;
        })}</div>
      </div>`;
    }
    return html`<div className=${"mes-lane " + (props.dimmed ? "dim" : "")}>
      <div className="lane-title">${props.title}${props.subtitle ? html`<span>${props.subtitle}</span>` : null}</div>
      <div className="lane-track">${(props.nodes || []).map(function (n, idx) {
        return html`<div key=${idx} className="lane-node">
          <div className="n-top"><strong>${n.name}</strong><em>${nodeStatus(n.wip)}</em></div>
          <div className="n-meta">WIP ${n.wip || 0} · bags ${n.bags || 0}</div>
          <div className="n-meta">Oldest dwell ${n.dwell || "N/A"}</div>
        </div>`;
      })}</div>
    </div>`;
  }

  function MachineCard(props) {
    var m = props.machine;
    var status = m.integrationStatus;
    var notIntegrated = status === "NOT_INTEGRATED";
    return html`<article className=${"mes-machine-card " + statusClass(status)}>
      <header>
        <h3>${m.shortLabel} · ${m.label}</h3>
        <span className="badge">${status === "LIVE_QR" ? "LIVE QR" : status === "NO_ACTIVITY_TODAY" ? "NO ACTIVITY TODAY" : status}</span>
      </header>
      <div className="svg-wrap">${renderMachineIllustration(m.slot, status)}</div>
      <dl>
        <dt>Station ID</dt><dd>${m.stationId != null ? m.stationId : "—"}</dd>
        <dt>Current bag</dt><dd>${notIntegrated ? "N/A" : m.currentBagId != null ? m.currentBagId : "NO ACTIVITY TODAY"}</dd>
        <dt>Timer</dt><dd>${notIntegrated ? "N/A" : fmtTimeMs(m.lastScanMs)}</dd>
        <dt>Counter start</dt><dd>${notIntegrated ? "N/A" : m.counterStart != null ? m.counterStart : "Insufficient data"}</dd>
        <dt>Counter current/end</dt><dd>${notIntegrated ? "N/A" : m.counterEnd != null ? m.counterEnd : "Insufficient data"}</dd>
        <dt>Throughput</dt><dd>${notIntegrated ? "N/A" : m.throughputPerHour != null ? m.throughputPerHour.toFixed(1) + " u/h" : "Insufficient data"}</dd>
        <dt>Utilization</dt><dd>${notIntegrated ? "N/A" : m.utilizationPct != null ? m.utilizationPct.toFixed(1) + "%" : "Insufficient data"}</dd>
        <dt>OEE</dt><dd>${notIntegrated ? "N/A" : m.oeeLabel || "Insufficient data"}</dd>
        <dt>Operator</dt><dd>${notIntegrated ? "N/A" : m.operator || "Insufficient data"}</dd>
        <dt>Last scan</dt><dd>${notIntegrated ? "N/A" : m.lastScanMs ? new Date(m.lastScanMs).toLocaleTimeString() : "Insufficient data"}</dd>
        <dt>Data source</dt><dd>${notIntegrated ? "Not connected" : status === "MANUAL_ENTRY" ? "Manual" : "QR + Counter"}</dd>
      </dl>
    </article>`;
  }

  function TracePanel(props) {
    var inputState = useState("");
    var q = inputState[0];
    var setQ = inputState[1];
    var parsed = parseInt(String(q || "").trim(), 10);
    var bagId = Number.isFinite(parsed) ? parsed : props.defaultBagId;
    var geo = window.OpsMetrics.deriveBagGenealogy(bagId, props.events, props.bags);
    return html`<section className="mes-panel trace" id="lot-trace-panel">
      <div className="panel-title">Live Bag Genealogy / Lot Trace</div>
      <label for="trace-bag">Trace bag ID</label>
      <input id="trace-bag" value=${q} placeholder=${String(props.defaultBagId || "Enter bag ID")} onInput=${function (e) { setQ(e.target.value); }} />
      <div className="trace-summary">Bag <strong>${geo.bagId || "—"}</strong> · SKU <strong>${geo.sku || "—"}</strong> · received <strong>${geo.receivedQtyDisplay || "—"}</strong></div>
      <div className="trace-lines">${(geo.traceLines || []).map(function (r, idx) {
        return html`<div key=${idx} className=${"trace-row " + (r.pending ? "pending" : "done")}>
          <span>${r.label}</span>
          <span>${r.atMs ? new Date(r.atMs).toLocaleTimeString() : "—"}</span>
          <span>${r.machineLabel || "—"}</span>
          <span>${r.operatorLabel || "—"}</span>
          <span>${r.counterReading != null ? r.counterReading : "—"}</span>
          <span>${r.dwellFromPrevMinutes != null ? r.dwellFromPrevMinutes.toFixed(1) + "m" : "—"}</span>
          <span>${r.statusBadge || (r.pending ? "Pending" : "Done")}</span>
        </div>`;
      })}</div>
    </section>`;
  }

  function StagingPanel(props) {
    var rows = props.rows || [];
    return html`<section className="mes-panel">
      <div className="panel-title">Staging / WIP (idle bags between stations)</div>
      <table className="mini-table">
        <thead><tr><th>Order</th><th>Bag</th><th>Idle</th><th>Entered</th><th>Last station</th><th>Last event</th></tr></thead>
        <tbody>
          ${rows.length
            ? rows.map(function (r, i) {
                return html`<tr key=${i}><td>#${i + 1}</td><td>${r.bagId}</td><td>${r.idleMinutes.toFixed(1)}m</td><td>${shortClock(r.enteredAtMs)}</td><td>${r.lastStationLabel || "—"}</td><td>${r.lastEventType}</td></tr>`;
              })
            : html`<tr><td colspan="6" className="muted">No staged idle bags.</td></tr>`}
        </tbody>
      </table>
    </section>`;
  }

  function MachineSettingsPanel(props) {
    var slots = props.slots || [];
    return html`<section className="mes-panel">
      <div className="panel-title">Machine settings / configuration</div>
      <table className="mini-table">
        <thead><tr><th>Slot</th><th>Label</th><th>Station ID</th><th>Kind</th><th>Status</th></tr></thead>
        <tbody>${slots.map(function (s, i) {
          return html`<tr key=${i}><td>${s.slot}</td><td>${s.label}</td><td>${s.stationId != null ? s.stationId : "Unmapped"}</td><td>${s.stationKind || "—"}</td><td>${s.stationId != null ? "Mapped" : "Needs mapping"}</td></tr>`;
        })}</tbody>
      </table>
      <p className="muted">Edit station mapping in workflow QR admin.</p>
    </section>`;
  }

  function AlertsPanels(props) {
    var alerts = (props.alerts || []).slice(0, 10);
    var activity = (props.activity || []).slice(0, 10);
    return html`<div className="mes-alerts-pair">
      <section className="mes-panel">
        <div className="panel-title">MES Alerts</div>
        <div className="feed-list">${alerts.length
          ? alerts.map(function (a, i) {
              var sev = String(a.severity || "info").toLowerCase();
              return html`<div key=${i} className=${"feed-row " + sev}><span>${shortClock(a.at_ms || a.atMs)}</span><span>${a.message}</span></div>`;
            })
          : html`<div className="muted">No active alerts.</div>`}</div>
      </section>
      <section className="mes-panel">
        <div className="panel-title">Activity feed</div>
        <div className="feed-list">${activity.length
          ? activity.map(function (a, i) {
              return html`<div key=${i} className="feed-row"><span>${shortClock(a.at_ms || a.atMs)}</span><span>${a.event || a.message || "—"}</span></div>`;
            })
          : html`<div className="muted">No recent activity.</div>`}</div>
      </section>
    </div>`;
  }

  function MesSectionTitle(props) {
    return html`<div className="mes-section-title">
      <h2>${props.title}</h2>
      ${props.sub ? html`<p>${props.sub}</p>` : null}
    </div>`;
  }

  function MesDataTable(props) {
    var cols = props.columns || [];
    var rows = props.rows || [];
    if (!rows.length) {
      return html`<p className="mes-muted">${props.empty || "No rows."}</p>`;
    }
    return html`<div className="mes-table-wrap">
      <table className="mes-data-table">
        <thead><tr>${cols.map(function (c, i) { return html`<th key=${i}>${c}</th>`; })}</tr></thead>
        <tbody>${rows.map(function (row, ri) {
          return html`<tr key=${ri}>${row.map(function (cell, ci) { return html`<td key=${ci}>${cell}</td>`; })}</tr>`;
        })}</tbody>
      </table>
    </div>`;
  }

  function filterTimelineByLine(timeline, lineKey) {
    return (timeline || []).filter(function (t) { return String(t.line_key || "").toLowerCase() === String(lineKey).toLowerCase(); });
  }

  function App(props) {
    var snapState = useState(null);
    var snap = snapState[0];
    var setSnap = snapState[1];

    var boot = useMemo(readBoot, []);
    var tabState = useState(readInitialTab);
    var activeTab = tabState[0];
    var setActiveTab = tabState[1];

    function selectTab(t) {
      setActiveTab(t);
      var h = "#" + t;
      if (window.location.hash !== h) window.history.replaceState(null, "", h);
    }

    useEffect(function () {
      function onHash() {
        setActiveTab(readInitialTab());
      }
      window.addEventListener("hashchange", onHash);
      return function () { window.removeEventListener("hashchange", onHash); };
    }, []);

    useEffect(function () {
      var n = document.getElementById("ops-tv-initial-data");
      if (n && n.textContent) {
        try {
          setSnap(JSON.parse(n.textContent));
        } catch (e) {}
      }
      function load() {
        fetch(props.snapshotUrl, { credentials: "same-origin" })
          .then(function (r) {
            return r.json();
          })
          .then(setSnap)
          .catch(function () {});
      }
      load();
      var id = setInterval(load, 15000);
      return function () {
        clearInterval(id);
      };
    }, [props.snapshotUrl]);

    var mes = (snap && snap.mes) || {};
    var inp = mes.metrics_inputs || {};
    var derived = useMemo(function () {
      if (!window.OpsMetrics || !window.OpsMetrics.deriveDashboardMetrics) {
        return { kpis: [], machines: [], queues: [], stagingBags: [] };
      }
      return window.OpsMetrics.deriveDashboardMetrics(inp.events || [], inp.machines || [], inp.bags || [], inp.shiftConfig || {});
    }, [snap]);

    var configuredMachineIds = (inp.machines || []).map(function (m) {
      return m.id;
    });
    var machineDefs = [
      { slot: 1, shortLabel: "M1", label: "DPP115 Blister Machine", stationId: inp.slots && inp.slots[0] ? inp.slots[0].stationId : null },
      { slot: 2, shortLabel: "M2", label: "Heat Press / Sealing", stationId: inp.slots && inp.slots[1] ? inp.slots[1].stationId : null },
      { slot: 3, shortLabel: "M3", label: "Heat Press / Sealing", stationId: inp.slots && inp.slots[2] ? inp.slots[2].stationId : null },
      { slot: 4, shortLabel: "M4", label: "Stickering Machine", stationId: inp.slots && inp.slots[3] ? inp.slots[3].stationId : null },
      { slot: 5, shortLabel: "M5", label: "Bottle Sealing Machine", stationId: inp.slots && inp.slots[4] ? inp.slots[4].stationId : null },
    ];

    var machineCards = machineDefs.map(function (d) {
      var stationId = d.stationId;
      var metrics = derived.machines.find(function (m) { return m.id === stationId; }) || {};
      var forceNotIntegrated = d.slot === 5 && !derived.machines.some(function (m) { return m.id === stationId && m.eventsCount > 0; });
      var status =
        stationId == null
          ? "NOT_INTEGRATED"
          : window.OpsMetrics.getMachineIntegrationStatus(stationId, inp.events || [], {
              dayStartMs: inp.shiftConfig && inp.shiftConfig.dayStartMs,
              configuredMachineIds: configuredMachineIds,
              forceNotIntegratedMachineIds: forceNotIntegrated ? [stationId] : [],
            });
      return Object.assign({}, d, metrics, {
        integrationStatus: status,
        currentBagId: metrics.currentBagId,
        stationId: stationId,
      });
    });

    var kpiBy = {};
    (derived.kpis || []).forEach(function (k) {
      kpiBy[k.id] = k;
    });

    var lanes = mes.lanes || [];
    var laneBlister = lanes.find(function (L) { return L.id === "lane_blister"; });
    var laneBottle = lanes.find(function (L) { return L.id === "lane_bottle"; });
    var urls = boot.urls || {};
    var navItems = boot.nav || [];
    var exit = boot.exit || {};

    var exitHref = exit.href || "";
    try {
      var rootEl = document.getElementById("mes-root");
      if (!exitHref && rootEl && rootEl.getAttribute("data-command-center-url")) {
        exitHref = rootEl.getAttribute("data-command-center-url");
      }
    } catch (e) {}

    var traceBagId = derived.genealogySelectedBagId || inp.genealogySelectedBagId;
    var alertsOnly = (mes.alerts || []).filter(function (a) {
      var s = String(a.severity || "").toLowerCase();
      return s === "alert" || s === "warn";
    });
    var activityFeed = (mes.timeline || []).map(function (t) {
      return {
        at_ms: t.at_ms,
        atMs: t.at_ms,
        event: [t.event, t.machine, t.bag_id].filter(Boolean).join(" · "),
      };
    });

    function alertRows(items, limit) {
      var xs = items || [];
      if (!xs.length) return html`<p className="mes-muted">No alerts in the current feed.</p>`;
      return html`<ul className="mes-alert-list">
        ${xs.slice(0, limit || 48).map(function (a, i) {
          var sev = (a.severity || "info").toLowerCase();
          return html`<li key=${i} className=${"mes-alert-li mes-sev-" + sev}>
            <span className="mes-alert-t">${a.at_ms ? new Date(Number(a.at_ms)).toLocaleTimeString() : "—"}</span>
            <span className="mes-alert-m">${a.message || ""}</span>
          </li>`;
        })}
      </ul>`;
    }

    function renderOverviewBands() {
      return html`<div className="mes-overview-stack">
        <section className="band band-kpi">
          <${KpiCard} label="Bags Today" value=${kpiBy.bags ? kpiBy.bags.value : 0} spark=${kpiBy.bags ? kpiBy.bags.sparkline : []} />
          <${KpiCard} label="Units Today" value=${kpiBy.units ? Number(kpiBy.units.value || 0).toLocaleString() : 0} spark=${kpiBy.units ? kpiBy.units.sparkline : []} />
          <${KpiCard} label="Active Bags / WIP" value=${kpiBy.cycles ? kpiBy.cycles.value : 0} spark=${[]} />
          <${KpiCard} label="Avg Cycle Time" value=${kpiBy.avg_cycle ? kpiBy.avg_cycle.value : "Insufficient data"} spark=${[]} />
          <${KpiCard} label="OEE" value=${kpiBy.oee ? kpiBy.oee.value : "Insufficient data"} spark=${[]} />
          <${KpiCard} label="On-Time Completion" value=${kpiBy.on_time ? kpiBy.on_time.value : "No target set"} spark=${[]} />
          <${KpiCard} label="Reject Rate" value=${kpiBy.rework ? kpiBy.rework.value : "No reject data"} spark=${[]} />
        </section>
        <section className="band band-map">
          <div className="map-lanes">
            ${lanes.length
              ? lanes.map(function (ln, li) {
                  return html`<${ProcessLane} key=${ln.id || li} lane=${ln} />`;
                })
              : html`<p className="mes-muted" style=${{ padding: "8px" }}>No production map data from server.</p>`}
          </div>
          <aside className="alert-rail">
            <h4>Priority alerts</h4>
            ${(mes.alerts || []).length
              ? (mes.alerts || []).slice(0, 10).map(function (a, i) {
                  return html`<div key=${i} className="alert-row">${a.message}</div>`;
                })
              : html`<div className="alert-row">No active alerts</div>`}
          </aside>
        </section>
        <section className="band band-machines">
          ${machineCards.map(function (m, i) {
            return html`<${MachineCard} key=${i} machine=${m} />`;
          })}
        </section>
        <section className="band band-analytics">
          <div className="analytics-grid">
            <div className="mes-panel">
              <div className="panel-title">Bag inventory (snapshot)</div>
              ${MesDataTable({
                columns: ["SKU", "Bag ref", "Qty", "Status"],
                rows: (mes.inventory || []).map(function (r) {
                  return [r.sku || "—", r.bag_id || "—", String(r.qty != null ? r.qty : "—"), r.status || "—"];
                }),
                empty: "No inventory rows from workflow bags yet.",
              })}
            </div>
            <div className="mes-panel">
              <div className="panel-title">Production trend (today)</div>
              ${mes.trend && mes.trend.series_valid
                ? html`<div className="mes-mini-stats">
                    <div>Blister hourly sum: ${(mes.trend.blister || []).reduce(function (a, b) { return a + Number(b || 0); }, 0)}</div>
                    <div>Bottle hourly sum: ${(mes.trend.bottle || []).reduce(function (a, b) { return a + Number(b || 0); }, 0)}</div>
                    <div>Card hourly sum: ${(mes.trend.card || []).reduce(function (a, b) { return a + Number(b || 0); }, 0)}</div>
                  </div>`
                : html`<p className="mes-muted">Insufficient data · no plotted production series yet today.</p>`}
            </div>
            <div className="mes-panel">
              <div className="panel-title">Cycle analysis</div>
              ${(mes.cycle_analysis && (mes.cycle_analysis.labels || []).length)
                ? MesDataTable({
                    columns: ["Period", "Today", "Prior"],
                    rows: (mes.cycle_analysis.labels || []).map(function (lbl, i) {
                      return [
                        String(lbl),
                        String((mes.cycle_analysis.today || [])[i] != null ? (mes.cycle_analysis.today || [])[i] : "—"),
                        String((mes.cycle_analysis.yesterday || [])[i] != null ? (mes.cycle_analysis.yesterday || [])[i] : "—"),
                      ];
                    }),
                    empty: "No cycle comparison.",
                  })
                : html`<p className="mes-muted">No cycle analysis payload for today.</p>`}
            </div>
            <div className="mes-panel">
              <div className="panel-title">Top SKUs</div>
              ${MesDataTable({
                columns: ["SKU", "Line", "Units", "Bags"],
                rows: (mes.sku_table || []).map(function (r) {
                  return [r.sku || "—", r.line || "—", String(r.units != null ? r.units : "—"), String(r.bags != null ? r.bags : "—")];
                }),
                empty: "No SKU totals yet today.",
              })}
            </div>
            <div className="mes-panel">
              <div className="panel-title">Staging status</div>
              ${MesDataTable({
                columns: ["Line", "Area", "Bags", "Oldest", "Minutes"],
                rows: (mes.staging || []).map(function (r) {
                  return [r.line || "—", r.area_name || "—", String(r.bags != null ? r.bags : "—"), r.oldest_bag || "—", String(r.minutes != null ? r.minutes : "—")];
                }),
                empty: "No staging rows from flow intel.",
              })}
            </div>
            <div className="mes-panel">
              <div className="panel-title">Recent timeline</div>
              ${MesDataTable({
                columns: ["Time", "Event", "Station", "Bag", "SKU"],
                rows: (mes.timeline || []).slice(0, 12).map(function (r) {
                  return [
                    r.at_ms ? new Date(Number(r.at_ms)).toLocaleTimeString() : "—",
                    r.event || "—",
                    r.machine || r.line || "—",
                    r.bag_id || "—",
                    r.sku || "—",
                  ];
                }),
                empty: "No recent workflow events.",
              })}
            </div>
            <div className="mes-panel">
              <div className="panel-title">Downtime (server)</div>
              ${(mes.downtime || []).length
                ? MesDataTable({
                    columns: ["Machine", "Reason", "Minutes"],
                    rows: mes.downtime.map(function (d) {
                      return [d.machine || "—", d.reason || "—", String(d.minutes != null ? d.minutes : "—")];
                    }),
                  })
                : html`<p className="mes-muted">No downtime records in snapshot.</p>`}
            </div>
            <div className="mes-panel">
              <div className="panel-title">Team (snapshot)</div>
              ${(mes.team || []).length
                ? MesDataTable({
                    columns: ["Operator", "Role", "Events"],
                    rows: mes.team.map(function (t) {
                      return [t.name || t.operator || "—", t.role || "—", String(t.events != null ? t.events : "—")];
                    }),
                  })
                : html`<p className="mes-muted">No team roll-up in snapshot — open Users tab for app link.</p>`}
            </div>
            <${MachineSettingsPanel} slots=${inp.slots || []} />
            <${StagingPanel} rows=${derived.stagingBags || []} />
            <div className="mes-panel mes-alerts-pair-wrap">
              <${AlertsPanels} alerts=${alertsOnly} activity=${activityFeed} />
            </div>
            <${TracePanel} events=${inp.events || []} bags=${inp.bags || []} defaultBagId=${traceBagId} />
          </div>
        </section>
      </div>`;
    }

    function renderLineSection(lane, title, lineKey,slots) {
      if (!lane) {
        return html`<div className="mes-tab-panel-inner">
          <${MesSectionTitle} title=${title} sub="No lane configuration returned from server for this view." />
        </div>`;
      }
      var cards = machineCards.filter(function (m) {
        return slots.indexOf(m.slot) >= 0;
      });
      var timeline = filterTimelineByLine(mes.timeline || [], lineKey);
      var m5c = lineKey === "bottle" ? machineCards.find(function (m) { return m.slot === 5; }) : null;
      var bottleBanner =
        m5c && m5c.integrationStatus === "NOT_INTEGRATED"
          ? html`<p className="mes-muted">Bottle line not integrated yet — no sealing workflow events at mapped M5 today.</p>`
          : null;
      return html`<div className="mes-tab-panel-inner">
        ${bottleBanner}
        <${MesSectionTitle} title=${title} sub=${lane.subtitle || "Live data from workflow snapshot (America/New_York day)."} />
        <${ProcessLane} lane=${lane} />
        <h3 className="mes-h3">Machines</h3>
        <div className="band-machines mes-band-inline">${cards.map(function (m, i) {
          return html`<${MachineCard} key=${i} machine=${m} />`;
        })}</div>
        <h3 className="mes-h3">Alerts (feed)</h3>
        ${alertRows(mes.alerts, 24)}
        <h3 className="mes-h3">Timeline today (${lineKey})</h3>
        ${MesDataTable({
          columns: ["Time", "Event", "Machine", "Bag", "SKU", "Operator"],
          rows: timeline.slice(0, 40).map(function (r) {
            return [
              r.at_ms ? new Date(Number(r.at_ms)).toLocaleTimeString() : "—",
              r.event || "—",
              r.machine || "—",
              r.bag_id || "—",
              r.sku || "—",
              r.employee || "—",
            ];
          }),
          empty: "No workflow events for this line in the recent timeline window.",
        })}
      </div>`;
    }

    function renderTabBody() {
      if (activeTab === "overview") return renderOverviewBands();
      if (activeTab === "blister") return renderLineSection(laneBlister, "Blister line", "blister", [1, 2, 3, 4]);
      if (activeTab === "bottle") {
        return renderLineSection(laneBottle, "Bottle line", "bottle", [5]);
      }
      if (activeTab === "machines") {
        return html`<div className="mes-tab-panel-inner">
          <${MesSectionTitle} title="Machines" sub="Live twin cards from workflow events and station mapping. Configuration edits remain in the main app." />
          <div className="band-machines mes-band-inline">${machineCards.map(function (m, i) {
            return html`<${MachineCard} key=${i} machine=${m} />`;
          })}</div>
          <h3 className="mes-h3">Station mapping (read-only)</h3>
          ${MesDataTable({
            columns: ["Slot", "Label", "Station ID", "Kind"],
            rows: (inp.slots || []).map(function (s) {
              return [String(s.slot), s.label || "—", s.stationId != null ? String(s.stationId) : "—", s.stationKind || "—"];
            }),
            empty: "No slot map — add workflow stations in Command Center.",
          })}
          <h3 className="mes-h3">Machine administration</h3>
          <p className="mes-muted">Name, role, line assignment, and display order are managed under Product configuration and the table Command Center. This panel will surface inline edits when APIs are available.</p>
          <button type="button" className="mes-btn-disabled" disabled title="Not available in this release">
            Edit machines (coming soon)
          </button>
          <${MachineSettingsPanel} slots=${inp.slots || []} />
        </div>`;
      }
      if (activeTab === "bags") {
        var mrows = inp.machines || [];
        var occRows = mrows
          .filter(function (row) {
            return row.workflowBagId != null;
          })
          .map(function (row) {
            return [
              String(row.workflowBagId),
              row.displayName || row.stationLabel || "—",
              row.stationKind || "—",
              row.status || "—",
              fmtTimeMs(row.occupancyStartedAtMs),
            ];
          });
        return html`<div className="mes-tab-panel-inner">
          <${MesSectionTitle} title="Bags / inventory" sub="Workflow bags and live station assignments from the current snapshot." />
          <h3 className="mes-h3">Live assignments (stations)</h3>
          ${MesDataTable({
            columns: ["Workflow bag", "Station", "Kind", "Status", "Timer"],
            rows: occRows,
            empty: "No bags currently claimed at stations.",
          })}
          <h3 className="mes-h3">Recent workflow bags (inventory slice)</h3>
          ${MesDataTable({
            columns: ["SKU", "Bag ref", "Qty", "Status"],
            rows: (mes.inventory || []).map(function (r) {
              return [r.sku || "—", r.bag_id || "—", String(r.qty != null ? r.qty : "—"), r.status || "—"];
            }),
            empty: "No workflow bag inventory rows — receiving and bag creation may not have run yet.",
          })}
          <p className="mes-muted">Shipment receiving and physical box/bag labels: <a href=${urls.receiving || "/receiving"} target="_blank" rel="noopener noreferrer">Shipments received</a>. QR card assignment: table Command Center.</p>
        </div>`;
      }
      if (activeTab === "staging") {
        var pipe = (snap && snap.flow && snap.flow.pipeline) || [];
        return html`<div className="mes-tab-panel-inner">
          <${MesSectionTitle} title="Staging / WIP" sub="Between-stage queues from flow intelligence and pill board payloads." />
          <${StagingPanel} rows=${derived.stagingBags || []} />
          <h3 className="mes-h3">Staging table</h3>
          ${MesDataTable({
            columns: ["Line", "Area", "Bags", "Oldest", "Minutes"],
            rows: (mes.staging || []).map(function (r) {
              return [r.line || "—", r.area_name || "—", String(r.bags != null ? r.bags : "—"), r.oldest_bag || "—", String(r.minutes != null ? r.minutes : "—")];
            }),
            empty: "No staging rows — pipeline may show zero WIP between blister and sealing.",
          })}
          <h3 className="mes-h3">Pipeline stages</h3>
          ${MesDataTable({
            columns: ["Stage", "WIP", "Subtitle", "Delay"],
            rows: pipe.map(function (n) {
              return [
                String(n.label || n.id || "—"),
                String(n.wip != null ? n.wip : "—"),
                String(n.subtitle || "—"),
                n.max_delay_min != null ? "max " + n.max_delay_min + "m" : n.avg_delay_min != null ? "avg " + n.avg_delay_min + "m" : "—",
              ];
            }),
            empty: "No pipeline data in snapshot.",
          })}
        </div>`;
      }
      if (activeTab === "alerts") {
        var act = (snap && snap.activity) || [];
        return html`<div className="mes-tab-panel-inner">
          <${MesSectionTitle} title="Alerts" sub="Smart alerts and activity feed (same source as ops snapshot)." />
          <${AlertsPanels} alerts=${alertsOnly} activity=${activityFeed} />
          <h3 className="mes-h3">Mes alerts (full list)</h3>
          ${alertRows(mes.alerts, 40)}
          <h3 className="mes-h3">Activity feed (server)</h3>
          ${alertRows(act, 60)}
        </div>`;
      }
      if (activeTab === "analytics") {
        return html`<div className="mes-tab-panel-inner">
          <${MesSectionTitle} title="Analytics" sub="Charts and tables from live snapshot — no demo fabrications." />
          <p className="mes-muted">
            For exports and printable reports, open
            <a href=${urls.reports || "/reports"} target="_blank" rel="noopener noreferrer"> Reports</a>
            in a new tab.
          </p>
          <h3 className="mes-h3">Output by station (today)</h3>
          ${MesDataTable({
            columns: ["Station", "Output", "Unit"],
            rows: ((snap && snap.bar_by_station) || []).map(function (b) {
              return [b.name || "—", String(b.output != null ? b.output : "—"), b.unit || "—"];
            }),
            empty: "No bar-by-station totals.",
          })}
          <h3 className="mes-h3">Top SKUs</h3>
          ${MesDataTable({
            columns: ["SKU", "Line", "Units", "Bags", "Cycles"],
            rows: (mes.sku_table || []).map(function (r) {
              return [
                r.sku || "—",
                r.line || "—",
                String(r.units != null ? r.units : "—"),
                String(r.bags != null ? r.bags : "—"),
                String(r.cycles != null ? r.cycles : "—"),
              ];
            }),
            empty: "No SKU aggregates today.",
          })}
          <h3 className="mes-h3">Hourly packaging (displays)</h3>
          ${MesDataTable({
            columns: ["Hour", "Displays"],
            rows: ((snap && snap.hour_labels) || []).map(function (lbl, i) {
              return [String(lbl), String(((snap && snap.chart_hourly_output) || [])[i] != null ? ((snap && snap.chart_hourly_output) || [])[i] : "—")];
            }),
            empty: "No hourly series.",
          })}
          <${TracePanel} events=${inp.events || []} bags=${inp.bags || []} defaultBagId=${traceBagId} />
        </div>`;
      }
      if (activeTab === "users") {
        return html`<div className="mes-tab-panel-inner">
          <${MesSectionTitle} title="Users" sub="Operator-facing roll-up when present in snapshot." />
          ${(mes.team || []).length
            ? MesDataTable({
                columns: ["Name", "Role", "Events"],
                rows: mes.team.map(function (t) {
                  return [t.name || t.operator || "—", t.role || "—", String(t.events != null ? t.events : "—")];
                }),
              })
            : html`<p className="mes-muted">No team metrics in this snapshot. User accounts are managed in the main app.</p>`}
          <p><a href=${urls.employees || "/admin/employees"} target="_blank" rel="noopener noreferrer">Open employee management</a></p>
        </div>`;
      }
      if (activeTab === "settings") {
        return html`<div className="mes-tab-panel-inner">
          <${MesSectionTitle} title="Command center settings" sub="Display and polling — advanced thresholds follow server policy." />
          <ul className="mes-settings-list">
            <li><strong>Data refresh</strong>: every 15 seconds (live snapshot poll).</li>
            <li><strong>Deep links</strong>: tab state is stored in the URL hash for refresh/back (#overview, #blister, …).</li>
            <li><strong>Thresholds</strong>: staging delay and bottleneck hints come from server-side flow intel (not editable here).</li>
          </ul>
          <p><a href=${urls.command_center || "/command-center"}>${"Table Command Center"}</a></p>
          <p><a href=${urls.product_config || "/admin/config"} target="_blank" rel="noopener noreferrer">Product configuration / machines</a></p>
        </div>`;
      }
      return renderOverviewBands();
    }

    return html`<div className="mes-app">
      <aside className="mes-aside">
        ${exitHref
          ? html`<a className="mes-exit-cc" href=${exitHref}>${exit.label || "Exit Command Center"}</a>`
          : null}
        ${navItems.map(function (item, i) {
          var tab = (item.tab || "").toLowerCase();
          var active = activeTab === tab;
          var lab = (item.icon ? item.icon + " " : "") + item.label;
          return html`<button
            type="button"
            key=${i}
            className=${"mes-nav-a mes-nav-btn " + (active ? "mes-active" : "")}
            onClick=${function () {
              selectTab(tab);
            }}
            aria-current=${active ? "page" : undefined}
          >
            ${lab}
          </button>`;
        })}
      </aside>
      <main className="mes-main">
        <header className="mes-header">
          <h1>Pill Packing Command Center</h1>
          <div className="mes-header-meta">
            <span>${new Date().toLocaleString()}</span>
            ${snap && snap.date_label ? html`<span className="mes-date-lbl">${snap.date_label} ET</span>` : null}
          </div>
        </header>
        ${activeTab === "overview"
          ? renderOverviewBands()
          : html`<div className="mes-tab-panel">${renderTabBody()}</div>`}
      </main>
    </div>`;
  }

  var root = document.getElementById("mes-root");
  if (!root) return;
  ReactDOM.createRoot(root).render(html`<${App} snapshotUrl=${root.getAttribute("data-snapshot-url") || ""} />`);

  window.renderDPP115BlisterMachine = renderDPP115BlisterMachine;
  window.renderHeatPressMachine = renderHeatPressMachine;
  window.renderStickeringMachine = renderStickeringMachine;
  window.renderBottleSealingMachine = renderBottleSealingMachine;
  window.renderPackagingStation = renderPackagingStation;
})();
