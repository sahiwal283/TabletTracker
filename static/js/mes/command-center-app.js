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
      var n = document.getElementById("mes-nav-boot");
      return JSON.parse((n && n.textContent) || "{}");
    } catch (e) {
      return {};
    }
  }

  function asNum(v) {
    var n = Number(v);
    return Number.isFinite(n) ? n : null;
  }

  function fmtNumber(v) {
    var n = asNum(v);
    return n == null ? "N/A" : n.toLocaleString();
  }

  function fmtTime(ms) {
    var n = asNum(ms);
    if (n == null) return "N/A";
    return new Date(n).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  }

  function fmtClock(d) {
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  }

  function elapsedSince(ms) {
    var n = asNum(ms);
    if (n == null) return "N/A";
    var total = Math.max(0, Math.floor((Date.now() - n) / 1000));
    var h = Math.floor(total / 3600);
    var m = Math.floor((total % 3600) / 60);
    var s = total % 60;
    return String(h).padStart(2, "0") + ":" + String(m).padStart(2, "0") + ":" + String(s).padStart(2, "0");
  }

  function minutesLabel(v) {
    var n = asNum(v);
    if (n == null) return "N/A";
    if (n >= 60) return (n / 60).toFixed(1) + "h";
    return n.toFixed(1) + "m";
  }

  function eventBagId(e) {
    return asNum(e && (e.bagId != null ? e.bagId : e.workflowBagId));
  }

  function eventMachineId(e) {
    return asNum(e && (e.stationId != null ? e.stationId : e.machineId));
  }

  function eventAt(e) {
    return asNum(e && (e.atMs != null ? e.atMs : e.at_ms));
  }

  function eventType(e) {
    return String((e && e.eventType) || "").toUpperCase();
  }

  function statusText(status) {
    if (status === "LIVE_QR") return "LIVE QR";
    if (status === "NO_ACTIVITY_TODAY") return "No activity today";
    if (status === "NOT_INTEGRATED") return "Not integrated";
    return status || "N/A";
  }

  function statusTone(status) {
    if (status === "LIVE_QR") return "run";
    if (status === "NO_ACTIVITY_TODAY") return "wait";
    if (status === "NOT_INTEGRATED") return "off";
    return "wait";
  }

  function latestByMachine(events, stationId) {
    var sid = asNum(stationId);
    if (sid == null) return null;
    return (events || []).filter(function (e) { return eventMachineId(e) === sid; }).sort(function (a, b) {
      return (eventAt(b) || 0) - (eventAt(a) || 0);
    })[0] || null;
  }

  function completedCounterEvent(events, stationId) {
    var sid = asNum(stationId);
    if (sid == null) return null;
    return (events || []).filter(function (e) {
      var t = eventType(e);
      return eventMachineId(e) === sid && (t === "BLISTER_COMPLETE" || t === "SEALING_COMPLETE" || t === "PACKAGING_SNAPSHOT" || t === "BAG_FINALIZED");
    }).sort(function (a, b) {
      return (eventAt(b) || 0) - (eventAt(a) || 0);
    })[0] || null;
  }

  function machineSvg(kind, status) {
    var tone = statusTone(status);
    var common = html`<rect x="7" y="8" width="146" height="78" rx="8" className="svg-bed" />
      <circle cx="145" cy="18" r="4" className="svg-beacon" />`;
    var body;
    if (kind === "blister") {
      body = html`<g><circle cx="30" cy="52" r="13" className="svg-part" />
        <rect x="48" y="43" width="40" height="18" rx="4" className="svg-part" />
        <rect x="96" y="35" width="24" height="34" rx="3" className="svg-part" />
        <path d="M36 52 H116 H138" className="svg-line" />
        ${[0, 1, 2, 3].map(function (i) { return html`<circle key=${i} cx=${54 + i * 9} cy="52" r="2.5" className="svg-dot" />`; })}</g>`;
    } else if (kind === "heat") {
      body = html`<g><rect x="32" y="30" width="96" height="15" rx="3" className="svg-part" />
        <rect x="27" y="65" width="106" height="13" rx="3" className="svg-part" />
        <path d="M43 45 V65 M118 45 V65 M68 50 l8 9 l8 -9 M93 50 l8 9 l8 -9" className="svg-line" /></g>`;
    } else if (kind === "sticker") {
      body = html`<g><circle cx="36" cy="39" r="13" className="svg-part" />
        <rect x="55" y="33" width="42" height="12" rx="3" className="svg-part" />
        <rect x="104" y="30" width="16" height="29" rx="3" className="svg-part" />
        <path d="M36 52 C58 70 94 70 136 66" className="svg-line" /></g>`;
    } else {
      body = html`<g><path d="M42 75 h22 l5 -25 h-7 v-11 h-18 v11 h-7 z" className="svg-part" />
        <rect x="82" y="33" width="18" height="27" rx="3" className="svg-part" />
        <ellipse cx="121" cy="74" rx="25" ry="9" className="svg-part" />
        <path d="M34 79 H146" className="svg-line" /></g>`;
    }
    return html`<svg className=${"machine-svg " + tone} viewBox="0 0 160 94" role="img" aria-label="machine pictogram">${common}${body}</svg>`;
  }

  function Badge(props) {
    return html`<span className=${"badge badge-" + (props.tone || "off")}>${props.children}</span>`;
  }

  function KpiCard(props) {
    return html`<article className="kpi-card">
      <div className="kpi-label">${props.label}</div>
      <div className=${"kpi-value " + (props.muted ? "muted-value" : "")}>${props.value}</div>
      <div className="kpi-note">${props.note || ""}</div>
    </article>`;
  }

  function laneNodeStatus(node) {
    if (node.notIntegrated) return "NOT_INTEGRATED";
    if ((node.wip || 0) > 0) return "LIVE_QR";
    return "NO_ACTIVITY_TODAY";
  }

  function ProcessLane(props) {
    return html`<section className=${"process-lane " + (props.dimmed ? "lane-dimmed" : "")}>
      <header>
        <h3>${props.title}</h3>
        ${props.subtitle ? html`<span>${props.subtitle}</span>` : null}
      </header>
      <div className="process-track">
        ${props.nodes.map(function (n, idx) {
          var st = laneNodeStatus(n);
          return html`<div key=${idx} className=${"process-node node-" + statusTone(st)}>
            <strong>${n.name}</strong>
            <dl>
              <div><dt>WIP</dt><dd>${n.notIntegrated ? "N/A" : fmtNumber(n.wip || 0)}</dd></div>
              <div><dt>Oldest dwell</dt><dd>${n.notIntegrated ? "N/A" : (n.dwell || "N/A")}</dd></div>
            </dl>
            <${Badge} tone=${statusTone(st)}>${n.notIntegrated ? "Not integrated" : (n.status || ((n.wip || 0) > 0 ? "Active" : "Waiting"))}</${Badge}>
          </div>`;
        })}
      </div>
    </section>`;
  }

  function MachineCard(props) {
    var m = props.machine;
    var notIntegrated = m.integrationStatus === "NOT_INTEGRATED";
    var last = m.latestEvent || {};
    var done = m.counterEvent || {};
    var counterStart = done.counterStart != null ? done.counterStart : last.counterStart;
    var counterEnd = done.counterEnd != null ? done.counterEnd : last.counterEnd;
    var counterText = notIntegrated ? "N/A" : (counterStart != null || counterEnd != null ? String(counterStart != null ? counterStart : "N/A") + " -> " + String(counterEnd != null ? counterEnd : "N/A") : "Insufficient data");

    return html`<article className=${"machine-card machine-" + statusTone(m.integrationStatus)}>
      <header>
        <div><span>${m.shortLabel}</span><h3>${m.label}</h3></div>
        <${Badge} tone=${statusTone(m.integrationStatus)}>${statusText(m.integrationStatus)}</${Badge}>
      </header>
      <div className="machine-visual">${machineSvg(m.kind, m.integrationStatus)}</div>
      <div className="source-row"><span>Data source</span><${Badge} tone=${notIntegrated ? "off" : "run"}>${notIntegrated ? "Not integrated" : "QR + Counter"}</${Badge}></div>
      <dl className="machine-stats">
        <div><dt>Current bag</dt><dd>${notIntegrated ? "N/A" : (m.currentBagId != null ? m.currentBagId : "No activity today")}</dd></div>
        <div><dt>Timer</dt><dd>${notIntegrated ? "N/A" : (m.lastScanMs ? elapsedSince(m.lastScanMs) : "N/A")}</dd></div>
        <div><dt>Counter</dt><dd>${counterText}</dd></div>
        <div><dt>Throughput</dt><dd>${notIntegrated ? "N/A" : (m.throughputPerHour != null ? m.throughputPerHour.toFixed(1) + " u/h" : "Insufficient data")}</dd></div>
        <div><dt>Utilization</dt><dd>${notIntegrated ? "N/A" : (m.utilizationPct != null ? m.utilizationPct.toFixed(1) + "%" : "Insufficient data")}</dd></div>
        <div><dt>OEE</dt><dd>${notIntegrated ? "N/A" : (m.oeeLabel || "Insufficient data")}</dd></div>
        <div><dt>Last scan</dt><dd>${notIntegrated ? "N/A" : (m.lastScanMs ? fmtTime(m.lastScanMs) : "N/A")}</dd></div>
      </dl>
    </article>`;
  }

  function InventoryPanel(props) {
    var rows = (props.rows || []).slice(0, 8);
    return html`<section className="wall-panel">
      <h3>Bag Inventory</h3>
      <table><thead><tr><th>SKU</th><th>Bags</th><th>Units</th><th>Status</th></tr></thead>
      <tbody>${rows.length ? rows.map(function (r, i) {
        return html`<tr key=${i}><td>${r.sku || r.product || "N/A"}</td><td>${fmtNumber(r.bags || r.bag_count || r.count)}</td><td>${fmtNumber(r.units || r.qty || r.quantity)}</td><td>${r.status || "N/A"}</td></tr>`;
      }) : html`<tr><td colspan="4" className="empty">No inventory rows</td></tr>`}</tbody></table>
    </section>`;
  }

  function TimelinePanel(props) {
    var rows = (props.rows || []).slice(0, 8);
    return html`<section className="wall-panel">
      <h3>Production Timeline</h3>
      <div className="event-list">${rows.length ? rows.map(function (r, i) {
        return html`<div key=${i} className="event-row"><span>${fmtTime(r.at_ms || r.atMs)}</span><strong>${r.event || r.event_type || r.message || "Event"}</strong><em>${[r.machine, r.station, r.bag_id ? "Bag " + r.bag_id : null].filter(Boolean).join(" / ")}</em></div>`;
      }) : html`<div className="empty">No production timeline events</div>`}</div>
    </section>`;
  }

  function StagingPanel(props) {
    var rows = (props.rows || []).slice(0, 8);
    return html`<section className="wall-panel">
      <h3>Staging Status</h3>
      <table><thead><tr><th>Bag</th><th>Idle</th><th>Entered</th><th>Last event</th></tr></thead>
      <tbody>${rows.length ? rows.map(function (r, i) {
        return html`<tr key=${i}><td>${r.bagId}</td><td>${minutesLabel(r.idleMinutes)}</td><td>${fmtTime(r.enteredAtMs)}</td><td>${r.lastEventType || "N/A"}</td></tr>`;
      }) : html`<tr><td colspan="4" className="empty">No staged idle bags</td></tr>`}</tbody></table>
    </section>`;
  }

  function TracePanel(props) {
    var inputState = useState("");
    var q = inputState[0];
    var setQ = inputState[1];
    var parsed = parseInt(String(q || "").trim(), 10);
    var bagId = Number.isFinite(parsed) ? parsed : props.defaultBagId;
    var geo = window.OpsMetrics.deriveBagGenealogy(bagId, props.events, props.bags);
    var current = (geo.traceLines || []).filter(function (r) { return !r.pending; }).slice(-1)[0];

    return html`<section className="wall-panel lot-trace">
      <h3>Live Bag Genealogy / Lot Trace</h3>
      <div className="trace-head">
        <input aria-label="Trace bag ID" value=${q} placeholder=${String(props.defaultBagId || "Bag ID")} onInput=${function (e) { setQ(e.target.value); }} />
        <div><span>Bag ID</span><strong>${geo.bagId || "N/A"}</strong></div>
        <div><span>SKU</span><strong>${geo.sku || "N/A"}</strong></div>
        <div><span>Received qty</span><strong>${geo.receivedQtyDisplay || "N/A"}</strong></div>
        <div><span>Current stage</span><strong>${current ? current.label : "N/A"}</strong></div>
        <div><span>Current machine</span><strong>${current && current.machineLabel ? current.machineLabel : "N/A"}</strong></div>
        <div><span>Elapsed</span><strong>${geo.totals && geo.totals.elapsedMinutes != null ? minutesLabel(geo.totals.elapsedMinutes) : "N/A"}</strong></div>
      </div>
      <div className="trace-timeline">${(geo.traceLines || []).map(function (r, idx) {
        return html`<div key=${idx} className=${"trace-step " + (r.pending ? "pending" : "done")}>
          <span></span><strong>${r.label}</strong><em>${r.pending ? "Pending" : fmtTime(r.atMs)}</em>
        </div>`;
      })}</div>
    </section>`;
  }

  function BottleneckPanel(props) {
    var rows = (props.queues || []).slice(0, 6);
    return html`<section className="wall-panel">
      <h3>Bottleneck / Queue Aging</h3>
      <div className="bottleneck-callout"><strong>${props.bottleneck && props.bottleneck.station ? props.bottleneck.station : "No bottleneck"}</strong><span>${props.bottleneck && props.bottleneck.reason ? props.bottleneck.reason : "No active staged queue"}</span></div>
      <table><thead><tr><th>Bag</th><th>Age</th></tr></thead><tbody>
      ${rows.length ? rows.map(function (r, i) { return html`<tr key=${i}><td>${r.bagId}</td><td>${minutesLabel(r.ageMinutes)}</td></tr>`; }) : html`<tr><td colspan="2" className="empty">No queue aging data</td></tr>`}
      </tbody></table>
    </section>`;
  }

  function TeamPanel(props) {
    var rows = (props.rows || []).slice(0, 8);
    return html`<section className="wall-panel">
      <h3>Team Performance</h3>
      <table><thead><tr><th>Team member</th><th>Bags</th><th>Units</th></tr></thead>
      <tbody>${rows.length ? rows.map(function (r, i) {
        return html`<tr key=${i}><td>${r.employee || r.operator || r.name || "N/A"}</td><td>${fmtNumber(r.bags || r.bag_count)}</td><td>${fmtNumber(r.units || r.qty || r.count)}</td></tr>`;
      }) : html`<tr><td colspan="3" className="empty">No team performance rows</td></tr>`}</tbody></table>
    </section>`;
  }

  function useClock() {
    var state = useState(new Date());
    var now = state[0];
    var setNow = state[1];
    useEffect(function () {
      var id = setInterval(function () { setNow(new Date()); }, 1000);
      return function () { clearInterval(id); };
    }, []);
    return now;
  }

  function App(props) {
    var snapState = useState(null);
    var snap = snapState[0];
    var setSnap = snapState[1];
    var now = useClock();

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

    var boot = readBoot();
    var mes = (snap && snap.mes) || {};
    var inp = mes.metrics_inputs || {};
    var events = inp.events || [];
    var derived = useMemo(function () {
      return window.OpsMetrics.deriveDashboardMetrics(inp.events || [], inp.machines || [], inp.bags || [], inp.shiftConfig || {});
    }, [snap]);

    var kpiBy = {};
    (derived.kpis || []).forEach(function (k) { kpiBy[k.id] = k; });

    var slots = inp.slots || [];
    var machineDefs = [
      { slot: 1, shortLabel: "M1", label: "DPP115 Blister Machine", kind: "blister", stationId: slots[0] && slots[0].stationId },
      { slot: 2, shortLabel: "M2", label: "Heat Press / Card Sealing", kind: "heat", stationId: slots[1] && slots[1].stationId },
      { slot: 3, shortLabel: "M3", label: "Heat Press / Card Sealing", kind: "heat", stationId: slots[2] && slots[2].stationId },
      { slot: 4, shortLabel: "M4", label: "Stickering Machine", kind: "sticker", stationId: slots[3] && slots[3].stationId },
      { slot: 5, shortLabel: "M5", label: "Bottle Sealing Machine", kind: "bottle", stationId: slots[4] && slots[4].stationId }
    ];
    var configuredMachineIds = (inp.machines || []).map(function (m) { return m.id; });
    var machineCards = machineDefs.map(function (d) {
      var metrics = (derived.machines || []).find(function (m) { return m.id === d.stationId; }) || {};
      var hasBottleEvents = d.slot !== 5 || events.some(function (e) { return eventMachineId(e) === asNum(d.stationId) && eventType(e) === "SEALING_COMPLETE"; });
      var status = d.stationId == null ? "NOT_INTEGRATED" : window.OpsMetrics.getMachineIntegrationStatus(d.stationId, events, {
        dayStartMs: inp.shiftConfig && inp.shiftConfig.dayStartMs,
        configuredMachineIds: configuredMachineIds,
        forceNotIntegratedMachineIds: hasBottleEvents ? [] : [d.stationId],
      });
      return Object.assign({}, d, metrics, {
        integrationStatus: status,
        latestEvent: latestByMachine(events, d.stationId),
        counterEvent: completedCounterEvent(events, d.stationId),
      });
    });

    var stageWip = {
      m1: machineCards[0] && machineCards[0].currentBagId != null ? 1 : 0,
      m2m3: (machineCards[1] && machineCards[1].currentBagId != null ? 1 : 0) + (machineCards[2] && machineCards[2].currentBagId != null ? 1 : 0),
      m4: machineCards[3] && machineCards[3].currentBagId != null ? 1 : 0,
      m5: machineCards[4] && machineCards[4].integrationStatus !== "NOT_INTEGRATED" && machineCards[4].currentBagId != null ? 1 : 0,
    };
    var staging = derived.stagingBags || [];
    var oldestStaging = staging[0] ? minutesLabel(staging[0].idleMinutes) : "N/A";
    var bottleDim = !machineCards[4] || machineCards[4].integrationStatus === "NOT_INTEGRATED";

    return html`<div className="mes-app">
      <main className="mes-main">
        <header className="mes-header">
          <div><h1>Pill Packing Command Center</h1><span>${snap && snap.generated_at_ms ? "Snapshot " + fmtTime(snap.generated_at_ms) : "Awaiting snapshot"}</span></div>
          <div className="header-controls">
            <button type="button">All Lines</button>
            <button type="button">All SKUs</button>
            <time>${fmtClock(now)}</time>
            ${boot.exit && boot.exit.href ? html`<a href=${boot.exit.href}>${boot.exit.label || "Exit"}</a>` : null}
          </div>
        </header>

        <section className="kpi-strip">
          <${KpiCard} label="Bags Today" value=${kpiBy.bags ? fmtNumber(kpiBy.bags.value) : "0"} />
          <${KpiCard} label="Units Today" value=${kpiBy.units ? fmtNumber(kpiBy.units.value) : "0"} />
          <${KpiCard} label="Active Bags / WIP" value=${kpiBy.cycles ? fmtNumber(kpiBy.cycles.value) : "0"} note="Active staged bags" />
          <${KpiCard} label="Avg Cycle Time" value=${kpiBy.avg_cycle ? kpiBy.avg_cycle.value : "Insufficient data"} muted=${kpiBy.avg_cycle && kpiBy.avg_cycle.value === "Insufficient data"} />
          <${KpiCard} label="OEE / Estimated OEE" value=${kpiBy.oee ? kpiBy.oee.value : "Insufficient data"} muted=${kpiBy.oee && String(kpiBy.oee.value).indexOf("data") >= 0} />
          <${KpiCard} label="On-Time Completion" value=${kpiBy.on_time ? kpiBy.on_time.value : "No target set"} muted=${true} />
          <${KpiCard} label="Reject Rate" value=${kpiBy.rework ? kpiBy.rework.value : "No reject data"} muted=${true} />
        </section>

        <section className="control-map">
          <div className="section-title"><h2>Production Control Map</h2><span>QR and counter event flow</span></div>
          <${ProcessLane} title="Blister SKU" nodes=${[
            { name: "Raw Material", wip: 0, dwell: "N/A" },
            { name: "M1 DPP115 Blister", wip: stageWip.m1, dwell: machineCards[0] && machineCards[0].lastScanMs ? elapsedSince(machineCards[0].lastScanMs) : "N/A" },
            { name: "Post-Blister Staging", wip: staging.length, dwell: oldestStaging },
            { name: "M2/M3 Heat Seal", wip: stageWip.m2m3, dwell: "N/A" },
            { name: "Post-Seal Staging", wip: 0, dwell: "N/A" },
            { name: "Packaging", wip: 0, dwell: "N/A" },
            { name: "Finished Goods", wip: 0, dwell: "N/A" }
          ]} />
          <${ProcessLane} title="Bottle SKU" subtitle=${bottleDim ? "Bottle line not integrated yet" : ""} dimmed=${bottleDim} nodes=${[
            { name: "Raw Material", wip: 0, dwell: "N/A", notIntegrated: bottleDim },
            { name: "M5 Bottle Sealing", wip: stageWip.m5, dwell: "N/A", notIntegrated: bottleDim },
            { name: "QA Hold", wip: 0, dwell: "N/A", notIntegrated: bottleDim },
            { name: "Finished Goods", wip: 0, dwell: "N/A", notIntegrated: bottleDim }
          ]} />
          <${ProcessLane} title="Card / Stickering SKU" nodes=${[
            { name: "Raw Material", wip: 0, dwell: "N/A" },
            { name: "M4 Stickering", wip: stageWip.m4, dwell: machineCards[3] && machineCards[3].lastScanMs ? elapsedSince(machineCards[3].lastScanMs) : "N/A" },
            { name: "Packaging", wip: 0, dwell: "N/A" },
            { name: "Finished Goods", wip: 0, dwell: "N/A" }
          ]} />
        </section>

        <section className="machine-grid">
          <div className="section-title"><h2>Machine Command Grid</h2><span>Five configured floor assets</span></div>
          <div className="machine-grid-inner">${machineCards.map(function (m, i) { return html`<${MachineCard} key=${i} machine=${m} />`; })}</div>
        </section>

        <section className="analytics-wall">
          <${InventoryPanel} rows=${mes.inventory || []} />
          <${TimelinePanel} rows=${mes.timeline || []} />
          <${StagingPanel} rows=${staging} />
          <${TracePanel} events=${events} bags=${inp.bags || []} defaultBagId=${derived.genealogySelectedBagId || inp.genealogySelectedBagId} />
          <${BottleneckPanel} queues=${derived.queues || []} bottleneck=${derived.bottleneck || {}} />
          <${TeamPanel} rows=${mes.team || []} />
        </section>
      </main>
    </div>`;
  }

  var root = document.getElementById("mes-root");
  if (!root) return;
  ReactDOM.createRoot(root).render(html`<${App} snapshotUrl=${root.getAttribute("data-snapshot-url") || ""} />`);
})();
