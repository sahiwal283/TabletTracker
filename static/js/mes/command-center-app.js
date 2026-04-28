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

  function fmtPct(v) {
    var n = asNum(v);
    return n == null ? "Insufficient data" : n.toFixed(1) + "%";
  }

  function fmtTime(ms, seconds) {
    var n = asNum(ms);
    if (n == null) return "N/A";
    return new Date(n).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: seconds ? "2-digit" : undefined });
  }

  function fmtDate(ms) {
    var d = ms ? new Date(ms) : new Date();
    return d.toLocaleDateString([], { month: "short", day: "numeric", year: "numeric" });
  }

  function elapsedSince(ms) {
    var n = asNum(ms);
    if (n == null) return "N/A";
    var total = Math.max(0, Math.floor((Date.now() - n) / 1000));
    var h = Math.floor(total / 3600);
    var m = Math.floor((total % 3600) / 60);
    return h > 0 ? h + "h " + String(m).padStart(2, "0") + "m" : m + "m";
  }

  function durationClock(ms) {
    var n = asNum(ms);
    if (n == null) return "N/A";
    var total = Math.max(0, Math.floor((Date.now() - n) / 1000));
    var h = Math.floor(total / 3600);
    var m = Math.floor((total % 3600) / 60);
    return h + "h " + String(m).padStart(2, "0") + "m";
  }

  function eventType(e) {
    return String((e && e.eventType) || "").toUpperCase();
  }

  function eventAt(e) {
    return asNum(e && (e.atMs != null ? e.atMs : e.at_ms));
  }

  function eventBagId(e) {
    return asNum(e && (e.bagId != null ? e.bagId : e.workflowBagId));
  }

  function eventMachineId(e) {
    return asNum(e && (e.stationId != null ? e.stationId : e.machineId));
  }

  function statusText(status) {
    if (status === "LIVE_QR") return "RUNNING";
    if (status === "NO_ACTIVITY_TODAY") return "IDLE";
    if (status === "NOT_INTEGRATED") return "NOT INTEGRATED";
    return String(status || "N/A").toUpperCase();
  }

  function statusTone(status) {
    if (status === "LIVE_QR") return "run";
    if (status === "NO_ACTIVITY_TODAY") return "idle";
    if (status === "NOT_INTEGRATED") return "off";
    return "idle";
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

  function machineIcon(kind, status) {
    var tone = statusTone(status);
    var body;
    if (kind === "blister") {
      body = html`<g><rect x="12" y="22" width="30" height="43" rx="4" /><circle cx="20" cy="31" r="3" /><circle cx="32" cy="31" r="3" /><circle cx="20" cy="44" r="3" /><circle cx="32" cy="44" r="3" /><circle cx="20" cy="57" r="3" /><circle cx="32" cy="57" r="3" /></g>`;
    } else if (kind === "heat") {
      body = html`<g><rect x="8" y="26" width="56" height="11" rx="2" /><rect x="4" y="54" width="64" height="11" rx="2" /><path d="M13 37v17M59 37v17M27 42l8 8 8-8" /></g>`;
    } else if (kind === "sticker") {
      body = html`<g><path d="M30 18h13v15h-4v38H26V33h-4V18z" /><path d="M18 71h32" /></g>`;
    } else if (kind === "bag") {
      body = html`<g><path d="M20 24h30l6 47H14z" /><path d="M25 24c0-12 20-12 20 0" /></g>`;
    } else if (kind === "bottle") {
      body = html`<g><path d="M25 69h21l4-30h-8V23H29v16h-8z" /><path d="M24 51h24" /></g>`;
    } else {
      body = html`<g><circle cx="36" cy="36" r="24" /><path d="M36 16v20l14 9" /></g>`;
    }
    return html`<svg className=${"line-icon " + tone} viewBox="0 0 72 82" aria-hidden="true">${body}</svg>`;
  }

  function miniIcon(type) {
    if (type === "bag") return html`<svg viewBox="0 0 48 48"><path d="M14 18h20l4 24H10z"/><path d="M18 18c0-10 12-10 12 0"/></svg>`;
    if (type === "bars") return html`<svg viewBox="0 0 48 48"><path d="M9 38V25M20 38V18M31 38V12M42 38V6"/></svg>`;
    if (type === "cycle") return html`<svg viewBox="0 0 48 48"><path d="M36 16a15 15 0 0 0-25 7M12 13v10h10M12 32a15 15 0 0 0 25-7M36 35V25H26"/></svg>`;
    if (type === "clock") return html`<svg viewBox="0 0 48 48"><circle cx="24" cy="24" r="17"/><path d="M24 12v13l9 7"/></svg>`;
    if (type === "gauge") return html`<svg viewBox="0 0 48 48"><path d="M8 32a16 16 0 0 1 32 0"/><path d="M24 32l9-13"/><path d="M13 32h4M31 32h4"/></svg>`;
    if (type === "target") return html`<svg viewBox="0 0 48 48"><circle cx="24" cy="24" r="16"/><circle cx="24" cy="24" r="9"/><circle cx="24" cy="24" r="3"/><path d="M36 12l6-6M35 13h7v7"/></svg>`;
    return html`<svg viewBox="0 0 48 48"><path d="M24 7l19 34H5z"/><path d="M24 18v10M24 35h.01"/></svg>`;
  }

  function Badge(props) {
    return html`<span className=${"occ-badge occ-" + (props.tone || "off")}>${props.children}</span>`;
  }

  function KpiCard(props) {
    return html`<article className="occ-kpi">
      <div><span>${props.label}</span><strong className=${props.tone ? "kpi-" + props.tone : ""}>${props.value}</strong><em>${props.note || "Insufficient data"}</em></div>
      <div className="occ-kpi-icon">${miniIcon(props.icon)}</div>
    </article>`;
  }

  function Sidebar(props) {
    var items = [
      ["Overview", "grid"], ["Blister Line", "blister"], ["Bottle Line", "bottle"], ["Card Line", "trend"],
      ["Machines", "machine"], ["Bags / Inventory", "bag"], ["Staging", "grid"], ["Alerts", "warn"],
      ["Reports", "report"], ["Analytics", "bars"], ["Users", "users"], ["Settings", "settings"]
    ];
    return html`<aside className="occ-side">
      <div className="occ-logo"><span></span><span></span><span></span></div>
      ${items.map(function (it, i) {
        var href = it[0] === "Settings" && props.boot.urls ? props.boot.urls.product_config : "#";
        return html`<a key=${it[0]} href=${href || "#"} className=${i === 0 ? "active" : ""}>
          <span className="nav-icon">${miniIcon(it[1])}</span><em>${it[0]}</em>
        </a>`;
      })}
    </aside>`;
  }

  function StepCard(props) {
    return html`<div className="step-card">
      <b>${props.index}</b>
      <div><strong>${props.title}</strong><small>${props.sub || "Insufficient data"}</small></div>
      ${machineIcon(props.icon || "bag", props.status || "NO_ACTIVITY_TODAY")}
      <p>${props.detail || "Insufficient data"}</p>
    </div>`;
  }

  function LifecycleLane(props) {
    return html`<section className=${"life-lane " + props.tone + (props.dimmed ? " dimmed" : "")}>
      <header><h2>${props.title} <span>(FULL LIFECYCLE)</span></h2><p>SKU: <b>${props.sku || "N/A"}</b></p></header>
      <div className="step-row">${props.steps.map(function (s, i) {
        return html`<${StepCard} key=${i} index=${i + 1} title=${s.title} sub=${s.sub} detail=${s.detail} icon=${s.icon} status=${s.status} />`;
      })}</div>
      <footer><span></span><strong>FULL PRODUCTION CYCLE COMPLETE</strong><i>✓</i></footer>
    </section>`;
  }

  function MachineCard(props) {
    var m = props.machine;
    var notIntegrated = m.integrationStatus === "NOT_INTEGRATED";
    var latest = m.latestEvent || {};
    var done = m.counterEvent || {};
    var start = done.counterStart != null ? done.counterStart : latest.counterStart;
    var end = done.counterEnd != null ? done.counterEnd : latest.counterEnd;
    var counter = notIntegrated ? "N/A" : (start != null || end != null ? String(start != null ? start : "N/A") + " / " + String(end != null ? end : "N/A") : "Insufficient data");
    return html`<article className=${"occ-machine " + statusTone(m.integrationStatus)}>
      <header><div><h3>${m.shortLabel}</h3><p>${m.label}</p></div><${Badge} tone=${statusTone(m.integrationStatus)}>${statusText(m.integrationStatus)}</${Badge}></header>
      <div className="machine-mid">${machineIcon(m.kind, m.integrationStatus)}<dl>
        <div><dt>Current Bag</dt><dd>${notIntegrated ? "N/A" : (m.currentBagId != null ? "BAG-" + m.currentBagId : "No activity today")}</dd></div>
        <div><dt>SKU</dt><dd>${m.sku || "N/A"}</dd></div>
      </dl></div>
      <div className="machine-grid-data">
        <div><span>Start Time</span><b>${notIntegrated ? "N/A" : fmtTime(m.lastScanMs)}</b></div>
        <div><span>Elapsed Time</span><b>${notIntegrated ? "N/A" : (m.lastScanMs ? durationClock(m.lastScanMs) : "N/A")}</b></div>
        <div><span>Counter</span><b>${counter}</b></div>
        <div><span>Last Scan</span><b>${notIntegrated ? "N/A" : fmtTime(m.lastScanMs)}</b></div>
        <div><span>Throughput</span><b>${notIntegrated ? "N/A" : (m.throughputPerHour != null ? m.throughputPerHour.toFixed(1) + " u/h" : "Insufficient data")}</b></div>
        <div><span>Units Today</span><b>${notIntegrated ? "N/A" : fmtNumber(m.completedUnits)}</b></div>
      </div>
    </article>`;
  }

  function MachineBand(props) {
    return html`<section className=${"machine-band " + props.tone}>
      <h2>${props.title}</h2>
      <div className="machine-band-row">${props.machines.map(function (m) { return html`<${MachineCard} key=${m.shortLabel} machine=${m} />`; })}</div>
    </section>`;
  }

  function AlertsRail(props) {
    var alerts = (props.alerts || []).slice(0, 5);
    return html`<aside className="alerts-rail">
      <header><h2>ACTIVE ALERTS</h2><a href="#">View all</a></header>
      ${alerts.length ? alerts.map(function (a, i) {
        var sev = String(a.severity || "info").toLowerCase();
        return html`<div key=${i} className=${"alert-item " + sev}>
          <b>${fmtTime(a.at_ms || a.atMs)}</b><p>${a.message || a.event || "Activity"}</p><${Badge} tone=${sev === "warn" || sev === "alert" ? "idle" : "off"}>${sev}</${Badge}>
        </div>`;
      }) : html`<div className="alert-item info"><b>N/A</b><p>No active alerts</p><${Badge} tone="off">INFO</${Badge}></div>`}
    </aside>`;
  }

  function DataTable(props) {
    return html`<table className="occ-table"><thead><tr>${props.headers.map(function (h) { return html`<th key=${h}>${h}</th>`; })}</tr></thead>
      <tbody>${props.rows.length ? props.rows.map(function (r, i) { return html`<tr key=${i}>${r.map(function (c, j) { return html`<td key=${j}>${c}</td>`; })}</tr>`; }) : html`<tr><td colSpan=${props.headers.length}>Insufficient data</td></tr>`}</tbody></table>`;
  }

  function TrendPanel(props) {
    var trend = props.trend || {};
    var valid = trend.series_valid && Array.isArray(trend.blister) && trend.blister.length;
    var series = valid ? [trend.blister || [], trend.bottle || [], trend.card || []] : [];
    var max = Math.max.apply(null, [1].concat(series.reduce(function (a, b) { return a.concat(b); }, [])));
    return html`<section className="wall-panel trend-panel"><h3>PRODUCTION TREND (UNITS)</h3>
      ${valid ? html`<svg viewBox="0 0 420 150" className="trend-svg">
        ${[0, 1, 2, 3, 4].map(function (i) { return html`<path key=${i} d=${"M0 " + (130 - i * 27) + "H410"} />`; })}
        ${series.map(function (s, si) {
          var d = s.map(function (v, i) {
            var x = 12 + (i / Math.max(1, s.length - 1)) * 390;
            var y = 132 - (Number(v || 0) / max) * 116;
            return (i ? "L" : "M") + x.toFixed(1) + " " + y.toFixed(1);
          }).join(" ");
          return html`<path key=${si} className=${"line s" + si} d=${d} />`;
        })}
      </svg>` : html`<div className="panel-empty">Insufficient data</div>`}
    </section>`;
  }

  function OeePanel(props) {
    var label = String(props.value || "Insufficient data");
    var pct = parseFloat(label);
    var valid = Number.isFinite(pct);
    var dash = valid ? Math.max(0, Math.min(100, pct)) + " 100" : "0 100";
    return html`<section className="wall-panel oee-panel"><h3>OEE BREAKDOWN (OVERALL)</h3>
      <div className="donut-wrap"><svg viewBox="0 0 42 42"><circle cx="21" cy="21" r="15.9" /><circle className="donut-meter" cx="21" cy="21" r="15.9" stroke-dasharray=${dash} /></svg><strong>${label}</strong></div>
    </section>`;
  }

  function TracePanel(props) {
    var inputState = useState("");
    var q = inputState[0];
    var setQ = inputState[1];
    var parsed = parseInt(String(q || "").trim(), 10);
    var bagId = Number.isFinite(parsed) ? parsed : props.defaultBagId;
    var geo = window.OpsMetrics.deriveBagGenealogy(bagId, props.events, props.bags);
    return html`<section className="wall-panel trace-panel"><h3>LIVE BAG GENEALOGY / LOT TRACE</h3>
      <div className="trace-meta"><input aria-label="Trace bag ID" value=${q} placeholder=${String(props.defaultBagId || "Bag ID")} onInput=${function (e) { setQ(e.target.value); }} /><b>Bag ${geo.bagId || "N/A"}</b><span>SKU ${geo.sku || "N/A"}</span><span>Qty ${geo.receivedQtyDisplay || "N/A"}</span></div>
      <div className="trace-steps">${(geo.traceLines || []).map(function (r, i) { return html`<div key=${i} className=${r.pending ? "pending" : "done"}><span></span><b>${r.label}</b><em>${r.pending ? "Pending" : fmtTime(r.atMs)}</em></div>`; })}</div>
    </section>`;
  }

  function App(props) {
    var snapState = useState(null);
    var snap = snapState[0];
    var setSnap = snapState[1];
    var clockState = useState(new Date());
    var now = clockState[0];
    var setNow = clockState[1];

    useEffect(function () {
      var t = setInterval(function () { setNow(new Date()); }, 1000);
      return function () { clearInterval(t); };
    }, []);

    useEffect(function () {
      var n = document.getElementById("ops-tv-initial-data");
      if (n && n.textContent) {
        try { setSnap(JSON.parse(n.textContent)); } catch (e) {}
      }
      function load() {
        fetch(props.snapshotUrl, { credentials: "same-origin" }).then(function (r) { return r.json(); }).then(setSnap).catch(function () {});
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
    var defs = [
      { slot: 1, shortLabel: "MACHINE 1", label: "DPP115 BLISTER MACHINE", kind: "blister", stationId: slots[0] && slots[0].stationId },
      { slot: 2, shortLabel: "MACHINE 2", label: "HEAT PRESS MACHINE", kind: "heat", stationId: slots[1] && slots[1].stationId },
      { slot: 3, shortLabel: "MACHINE 3", label: "HEAT PRESS MACHINE", kind: "heat", stationId: slots[2] && slots[2].stationId },
      { slot: 4, shortLabel: "MACHINE 4", label: "STICKERING MACHINE", kind: "sticker", stationId: slots[3] && slots[3].stationId },
      { slot: 5, shortLabel: "MACHINE 5", label: "BOTTLE SEALING MACHINE", kind: "bottle", stationId: slots[4] && slots[4].stationId }
    ];
    var configured = (inp.machines || []).map(function (m) { return m.id; });
    var machines = defs.map(function (d) {
      var metrics = (derived.machines || []).find(function (m) { return m.id === d.stationId; }) || {};
      var hasBottleEvents = d.slot !== 5 || events.some(function (e) { return eventMachineId(e) === asNum(d.stationId) && eventType(e) === "SEALING_COMPLETE"; });
      var status = d.stationId == null ? "NOT_INTEGRATED" : window.OpsMetrics.getMachineIntegrationStatus(d.stationId, events, {
        dayStartMs: inp.shiftConfig && inp.shiftConfig.dayStartMs,
        configuredMachineIds: configured,
        forceNotIntegratedMachineIds: hasBottleEvents ? [] : [d.stationId],
      });
      return Object.assign({}, d, metrics, {
        integrationStatus: status,
        latestEvent: latestByMachine(events, d.stationId),
        counterEvent: completedCounterEvent(events, d.stationId),
        sku: (inp.bags && inp.bags[0] && inp.bags[0].sku) || "N/A",
      });
    });

    var alerts = (mes.alerts || []).filter(function (a) { return String(a.severity || "info").toLowerCase() !== "info"; });
    var timeline = (mes.timeline || []).slice(0, 7);
    var staging = derived.stagingBags || [];
    var inventoryRows = (mes.inventory || []).slice(0, 6).map(function (r) {
      return [r.sku || r.product || "N/A", r.bag_id || r.bagId || "N/A", fmtNumber(r.units || r.qty), fmtNumber(r.quantity || r.bags), r.status || "N/A"];
    });
    var topSkuRows = (mes.sku_table || []).slice(0, 4).map(function (r) {
      return [r.sku || "N/A", r.line || r.product_type || "N/A", fmtNumber(r.units), fmtNumber(r.bags), fmtNumber(r.cycles)];
    });
    var stagingRows = staging.slice(0, 6).map(function (r) {
      return ["Line", "Post Staging", r.bagId, elapsedSince(r.enteredAtMs)];
    });
    var timelineRows = timeline.map(function (r) {
      return [fmtTime(r.at_ms || r.atMs), r.line || "N/A", r.machine || r.station || "N/A", r.event || r.message || "Activity", r.bag_id || "N/A"];
    });
    var teamRows = (mes.team || []).slice(0, 6).map(function (r) {
      return [r.employee || r.operator || r.name || "N/A", r.line || "N/A", fmtNumber(r.cycles || r.bags), fmtNumber(r.units || r.qty)];
    });
    var downtimeRows = (mes.downtime || []).slice(0, 4).map(function (r) {
      return [r.line || "N/A", r.downtime || r.duration || "N/A", r.reason || "N/A", fmtNumber(r.impact_units || r.impact)];
    });

    var bottleIntegrated = machines[4].integrationStatus !== "NOT_INTEGRATED";
    var generated = snap && snap.generated_at_ms;
    return html`<div className="occ-app">
      <${Sidebar} boot=${boot} />
      <main className="occ-main">
        <header className="occ-header">
          <div><h1>PILL PACKING COMMAND CENTER</h1><p>Real-time Production Monitoring <span></span> LIVE</p></div>
          <div className="occ-head-controls"><b>${fmtDate(generated)}</b><b>${fmtTime(now.getTime())}</b><button>All Lines</button><button>All SKUs</button><i>⛶</i></div>
        </header>
        <section className="occ-kpis">
          <${KpiCard} label="TOTAL BAGS PROCESSED (TODAY)" value=${kpiBy.bags ? fmtNumber(kpiBy.bags.value) : "0"} note="Real workflow bags" icon="bag" />
          <${KpiCard} label="TOTAL UNITS PROCESSED (TODAY)" value=${kpiBy.units ? fmtNumber(kpiBy.units.value) : "0"} note="Completed counter deltas" icon="bars" />
          <${KpiCard} label="PRODUCTION CYCLES (TODAY)" value=${kpiBy.cycles ? fmtNumber(kpiBy.cycles.value) : "0"} note="Active WIP" icon="cycle" />
          <${KpiCard} label="AVERAGE CYCLE TIME (ALL)" value=${kpiBy.avg_cycle ? kpiBy.avg_cycle.value : "Insufficient data"} note=${kpiBy.avg_cycle && kpiBy.avg_cycle.value !== "Insufficient data" ? "From completed operations" : "Insufficient data"} icon="clock" tone="amber" />
          <${KpiCard} label="OEE (OVERALL)" value=${kpiBy.oee ? kpiBy.oee.value : "Insufficient data"} note=${inp.shiftConfig && inp.shiftConfig.targetThroughputPerHour ? "Target configured" : "No target set"} icon="gauge" tone="green" />
          <${KpiCard} label="ON TIME COMPLETION" value=${kpiBy.on_time ? kpiBy.on_time.value : "No target set"} note=${inp.shiftConfig && inp.shiftConfig.productionDueMs ? "Due time configured" : "No target set"} icon="target" tone="red" />
          <${KpiCard} label="REWORK / REJECTS" value=${kpiBy.rework ? kpiBy.rework.value : "No reject data"} note="Real reject events only" icon="warn" tone="red" />
        </section>
        <section className="occ-life-grid">
          <${LifecycleLane} tone="blue" title="BLISTER PACKING LINE" sku=${(inp.bags && inp.bags[0] && inp.bags[0].sku) || "N/A"} steps=${[
            { title: "RAW MATERIAL RECEIPT", sub: "QR code assigned", detail: "Received qty N/A", icon: "bag" },
            { title: "BLISTER (DPP115)", sub: "Machine 1 Blistering", detail: machines[0].currentBagId ? "Bag " + machines[0].currentBagId : "Insufficient data", icon: "blister", status: machines[0].integrationStatus },
            { title: "POST-BLISTER STAGING", sub: "Buffer queue", detail: "Staged bags " + staging.length, icon: "bag" },
            { title: "HEAT SEALING", sub: "Machine 2 / 3", detail: "Counter required", icon: "heat", status: machines[1].integrationStatus },
            { title: "POST-SEAL STAGING", sub: "Buffer queue", detail: "Insufficient data", icon: "bag" },
            { title: "PACKAGING", sub: "Hand pack / master", detail: "Insufficient data", icon: "bag" }
          ]} />
          <${LifecycleLane} tone="green" title="BOTTLE SEALING LINE" sku="N/A" dimmed=${!bottleIntegrated} steps=${[
            { title: "RAW MATERIAL RECEIPT", sub: "QR code assigned", detail: bottleIntegrated ? "Received qty N/A" : "Bottle line not integrated yet", icon: "bag", status: machines[4].integrationStatus },
            { title: "HAND COUNTING", sub: "Scan start / complete", detail: "Insufficient data", icon: "bottle", status: machines[4].integrationStatus },
            { title: "COUNTING STAGING", sub: "Buffer queue", detail: "Insufficient data", icon: "bag" },
            { title: "STICKERING", sub: "Machine 4", detail: "Insufficient data", icon: "sticker", status: machines[3].integrationStatus },
            { title: "STICKER STAGING", sub: "Buffer queue", detail: "Insufficient data", icon: "bag" },
            { title: "SEALING", sub: "Machine 5", detail: bottleIntegrated ? "Real sealing events" : "Not integrated", icon: "heat", status: machines[4].integrationStatus },
            { title: "PACKING", sub: "Handmade displays", detail: "Insufficient data", icon: "bag" }
          ]} />
          <${LifecycleLane} tone="purple" title="CARD / BLISTER CARD LINE" sku="N/A" steps=${[
            { title: "RAW MATERIAL RECEIPT", sub: "QR code assigned", detail: "Received qty N/A", icon: "bag" },
            { title: "HEAT SEALING", sub: "Machine 2 / 3", detail: "Insufficient data", icon: "heat", status: machines[1].integrationStatus },
            { title: "STICKERING", sub: "Machine 4", detail: "Insufficient data", icon: "sticker", status: machines[3].integrationStatus },
            { title: "PACKAGING", sub: "Hand pack / master", detail: "Insufficient data", icon: "bag" }
          ]} />
          <${AlertsRail} alerts=${alerts} />
        </section>
        <section className="occ-machine-grid">
          <${MachineBand} title="BLISTER LINE MACHINES" tone="blue" machines=${[machines[0], machines[1], machines[2], machines[3]]} />
          <${MachineBand} title="BOTTLE LINE MACHINES" tone="green" machines=${[machines[4], machines[3]]} />
          <${MachineBand} title="CARD LINE MACHINES" tone="purple" machines=${[machines[1], machines[3]]} />
        </section>
        <section className="occ-wall wall-row-a">
          <section className="wall-panel"><h3>BAG INVENTORY (IN STOCK)</h3><${DataTable} headers=${["SKU", "BAG ID", "UNITS", "QUANTITY", "STATUS"]} rows=${inventoryRows} /></section>
          <${TrendPanel} trend=${mes.trend || {}} />
          <section className="wall-panel"><h3>CYCLE TIME ANALYSIS (AVG)</h3><div className="panel-empty">${kpiBy.avg_cycle ? kpiBy.avg_cycle.value : "Insufficient data"}</div></section>
          <section className="wall-panel"><h3>TOP SKUS (TODAY)</h3><${DataTable} headers=${["SKU", "LINE", "UNITS", "BAGS", "CYCLES"]} rows=${topSkuRows} /></section>
          <section className="wall-panel"><h3>STAGING AREA STATUS</h3><${DataTable} headers=${["LINE", "STAGING AREA", "BAG", "TIME IN AREA"]} rows=${stagingRows} /></section>
        </section>
        <section className="occ-wall wall-row-b">
          <section className="wall-panel"><h3>PRODUCTION TIMELINE (LATEST ACTIVITY)</h3><${DataTable} headers=${["TIME", "LINE", "MACHINE", "EVENT", "BAG ID"]} rows=${timelineRows} /></section>
          <${OeePanel} value=${kpiBy.oee && kpiBy.oee.value} />
          <section className="wall-panel"><h3>DOWNTIME SUMMARY (TODAY)</h3><${DataTable} headers=${["LINE", "DOWNTIME", "REASON", "IMPACT"]} rows=${downtimeRows} /></section>
          <section className="wall-panel"><h3>TEAM PERFORMANCE (TODAY)</h3><${DataTable} headers=${["TEAM", "LINE", "CYCLES", "UNITS"]} rows=${teamRows} /></section>
        </section>
        <${TracePanel} events=${events} bags=${inp.bags || []} defaultBagId=${derived.genealogySelectedBagId || inp.genealogySelectedBagId} />
        <footer className="occ-footer"><span>All data is real-time and updates automatically.</span><span>Last updated: ${generated ? fmtTime(generated, true) : "N/A"} <i></i></span></footer>
      </main>
    </div>`;
  }

  var root = document.getElementById("mes-root");
  if (!root) return;
  ReactDOM.createRoot(root).render(html`<${App} snapshotUrl=${root.getAttribute("data-snapshot-url") || ""} />`);
})();
