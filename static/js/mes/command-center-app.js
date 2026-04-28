(function () {
  var React = window.React;
  var ReactDOM = window.ReactDOM;
  var htmVendor = window.htm;
  if (!React || !ReactDOM || !htmVendor) return;

  var html = htmVendor.bind(React.createElement);
  var useEffect = React.useEffect;
  var useMemo = React.useMemo;
  var useState = React.useState;

  function readNavBoot() {
    try {
      var n = document.getElementById("mes-nav-boot");
      return JSON.parse(n.textContent || "{}").nav || [];
    } catch (e) {
      return [];
    }
  }

  function fmtTimeMs(ms) {
    if (ms == null) return "N/A";
    var s = Math.max(0, Math.floor((Date.now() - Number(ms)) / 1000));
    var h = Math.floor(s / 3600);
    var m = Math.floor((s % 3600) / 60);
    var ss = s % 60;
    return String(h).padStart(2, "0") + ":" + String(m).padStart(2, "0") + ":" + String(ss).padStart(2, "0");
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

  function ProcessLane(props) {
    return html`<div className=${"mes-lane " + (props.dimmed ? "dim" : "") }>
      <div className="lane-title">${props.title}${props.subtitle ? html`<span>${props.subtitle}</span>` : null}</div>
      <div className="lane-track">${props.nodes.map(function (n, idx) {
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
        return html`<div key=${idx} className=${"trace-row " + (r.pending ? "pending" : "done") }>
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

  function App(props) {
    var snapState = useState(null);
    var snap = snapState[0];
    var setSnap = snapState[1];

    useEffect(function () {
      var n = document.getElementById("ops-tv-initial-data");
      if (n && n.textContent) {
        try { setSnap(JSON.parse(n.textContent)); } catch (e) {}
      }
      function load() {
        fetch(props.snapshotUrl, { credentials: "same-origin" })
          .then(function (r) { return r.json(); })
          .then(setSnap)
          .catch(function () {});
      }
      load();
      var id = setInterval(load, 15000);
      return function () { clearInterval(id); };
    }, [props.snapshotUrl]);

    var mes = (snap && snap.mes) || {};
    var inp = mes.metrics_inputs || {};
    var derived = useMemo(function () {
      return window.OpsMetrics.deriveDashboardMetrics(inp.events || [], inp.machines || [], inp.bags || [], inp.shiftConfig || {});
    }, [snap]);

    var configuredMachineIds = (inp.machines || []).map(function (m) { return m.id; });
    var machineDefs = [
      { slot: 1, shortLabel: "M1", label: "DPP115 Blister Machine", stationId: inp.slots && inp.slots[0] ? inp.slots[0].stationId : null },
      { slot: 2, shortLabel: "M2", label: "Heat Press / Card Sealing Machine", stationId: inp.slots && inp.slots[1] ? inp.slots[1].stationId : null },
      { slot: 3, shortLabel: "M3", label: "Heat Press / Card Sealing Machine", stationId: inp.slots && inp.slots[2] ? inp.slots[2].stationId : null },
      { slot: 4, shortLabel: "M4", label: "Stickering Machine", stationId: inp.slots && inp.slots[3] ? inp.slots[3].stationId : null },
      { slot: 5, shortLabel: "M5", label: "Bottle Sealing Machine", stationId: inp.slots && inp.slots[4] ? inp.slots[4].stationId : null }
    ];

    var machineCards = machineDefs.map(function (d) {
      var stationId = d.stationId;
      var metrics = derived.machines.find(function (m) { return m.id === stationId; }) || {};
      var forceNotIntegrated = d.slot === 5 && !derived.machines.some(function (m) { return m.id === stationId && m.eventsCount > 0; });
      var status = stationId == null
        ? "NOT_INTEGRATED"
        : window.OpsMetrics.getMachineIntegrationStatus(stationId, inp.events || [], {
            dayStartMs: inp.shiftConfig && inp.shiftConfig.dayStartMs,
            configuredMachineIds: configuredMachineIds,
            forceNotIntegratedMachineIds: forceNotIntegrated ? [stationId] : [],
          });
      return Object.assign({}, d, metrics, { integrationStatus: status, currentBagId: metrics.currentBagId });
    });

    var kpiBy = {};
    (derived.kpis || []).forEach(function (k) { kpiBy[k.id] = k; });

    return html`<div className="mes-app">
      <aside className="mes-aside">${readNavBoot().map(function (n, i) {
        return html`<a key=${i} href=${n.href} className=${"mes-nav-a " + (String(n.href).indexOf("ops-tv") >= 0 ? "mes-active" : "")}>${n.label}</a>`;
      })}</aside>
      <main className="mes-main">
        <header className="mes-header"><h1>Pill Packing MES Command Center</h1><div>${new Date().toLocaleString()}</div></header>

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
            <${ProcessLane} title="Blister SKU Flow" nodes=${[
              { name: "Raw Material Receipt", wip: 0, bags: 0, dwell: "N/A" },
              { name: "Machine 1 DPP115", wip: kpiBy.cycles ? kpiBy.cycles.value : 0, bags: kpiBy.bags ? kpiBy.bags.value : 0, dwell: "Live" },
              { name: "Post-Blister Staging", wip: derived.queues.length, bags: derived.queues.length, dwell: derived.queues[0] ? derived.queues[0].ageMinutes.toFixed(1) + "m" : "N/A" },
              { name: "Machine 2 OR Machine 3 Heat Seal", wip: 0, bags: 0, dwell: "N/A" },
              { name: "Post-Seal Staging", wip: 0, bags: 0, dwell: "N/A" },
              { name: "Packaging", wip: 0, bags: 0, dwell: "N/A" },
              { name: "Finished Goods", wip: 0, bags: 0, dwell: "N/A" }
            ]} />
            <${ProcessLane} title="Bottle SKU Flow" subtitle="Bottle line not integrated yet" dimmed=${true} nodes=${[
              { name: "Raw Material", wip: 0, bags: 0, dwell: "N/A" },
              { name: "Machine 5 Bottle Sealing", wip: 0, bags: 0, dwell: "N/A" },
              { name: "Bottle QA Hold", wip: 0, bags: 0, dwell: "N/A" },
              { name: "Finished Goods", wip: 0, bags: 0, dwell: "N/A" }
            ]} />
            <${ProcessLane} title="Card / Stickering SKU Flow" nodes=${[
              { name: "Raw Material", wip: 0, bags: 0, dwell: "N/A" },
              { name: "Machine 4 Stickering", wip: 0, bags: 0, dwell: "N/A" },
              { name: "Packaging", wip: 0, bags: 0, dwell: "N/A" },
              { name: "Finished Goods", wip: 0, bags: 0, dwell: "N/A" }
            ]} />
          </div>
          <aside className="alert-rail">
            <h4>Active alerts</h4>
            ${(mes.alerts || []).length ? (mes.alerts || []).slice(0, 8).map(function (a, i) {
              return html`<div key=${i} className="alert-row">${a.message}</div>`;
            }) : html`<div className="alert-row">No active alerts</div>`}
          </aside>
        </section>

        <section className="band band-machines">
          ${machineCards.map(function (m, i) { return html`<${MachineCard} key=${i} machine=${m} />`; })}
        </section>

        <section className="band band-analytics">
          <div className="analytics-grid">
            <div className="mes-panel"><div className="panel-title">Bag Inventory</div></div>
            <div className="mes-panel"><div className="panel-title">Production Trend</div></div>
            <div className="mes-panel"><div className="panel-title">Cycle Analysis</div></div>
            <div className="mes-panel"><div className="panel-title">Top SKUs</div></div>
            <div className="mes-panel"><div className="panel-title">Staging Status</div></div>
            <div className="mes-panel"><div className="panel-title">Production Timeline</div></div>
            <div className="mes-panel"><div className="panel-title">OEE Breakdown</div></div>
            <div className="mes-panel"><div className="panel-title">Downtime Today</div></div>
            <div className="mes-panel"><div className="panel-title">Team Performance</div></div>
            <${TracePanel} events=${inp.events || []} bags=${inp.bags || []} defaultBagId=${derived.genealogySelectedBagId || inp.genealogySelectedBagId} />
          </div>
        </section>
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
