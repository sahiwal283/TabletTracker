/**
 * Browser bundle mirroring src/lib/command-center/metrics.ts (honest event-based KPIs).
 */
(function (global) {
  "use strict";

  function insuf() {
    return "Insufficient data";
  }

  function clampOee(a, p, q) {
    var o = (a / 100) * (p / 100) * (q / 100) * 100;
    if (isNaN(o)) return null;
    return Math.min(100, Math.max(0, o));
  }

  function stationEvents(events, sid) {
    return events.filter(function (e) {
      return e.stationId === sid;
    });
  }

  function uniqueBags(events) {
    var s = {};
    for (var i = 0; i < events.length; i++) {
      var b = events[i].bagId;
      if (b != null) s[b] = 1;
    }
    return Object.keys(s).length;
  }

  function sumCounterDeltas(events) {
    var acc = 0;
    var any = false;
    for (var i = 0; i < events.length; i++) {
      var e = events[i];
      if (e.counterStart != null && e.counterEnd != null) {
        acc += Math.max(0, e.counterEnd - e.counterStart);
        any = true;
        continue;
      }
      if (e.countTotal != null && e.countTotal > 0) {
        acc += e.countTotal;
        any = true;
      }
      var displayTotal = e.totalDisplayCount != null ? e.totalDisplayCount : e.displayCount;
      if (displayTotal != null && displayTotal > 0) {
        acc += displayTotal;
        any = true;
      }
    }
    return any ? acc : null;
  }

  function rejectStats(events) {
    var rejects = 0;
    var total = 0;
    for (var i = 0; i < events.length; i++) {
      var e = events[i];
      if (e.eventType === "CARD_REJECT" || e.eventType === "CARD_FORCE_RELEASED") rejects += 1;
      var u = e.countTotal != null ? e.countTotal : e.totalDisplayCount != null ? e.totalDisplayCount : e.displayCount != null ? e.displayCount : null;
      if (u != null && u > 0) total += u;
    }
    if (total <= 0) return { qualityPct: null, rejectRate: null };
    var good = Math.max(0, total - rejects);
    var q = (good / (total + rejects)) * 100;
    var rr = total + rejects > 0 ? (rejects / (total + rejects)) * 100 : null;
    return { qualityPct: q, rejectRate: rr };
  }

  function getIntegration(sid, sk, slotRole, events) {
    if (sid == null) return "NOT_INTEGRATED";
    if (slotRole === "bottle_seal") {
      var hasSeal = false;
      for (var i = 0; i < events.length; i++) {
        var e = events[i];
        if (e.stationId === sid && e.eventType === "SEALING_COMPLETE") hasSeal = true;
      }
      if (!hasSeal) return "NOT_INTEGRATED";
    }
    var wf = [
      "BAG_CLAIMED",
      "BLISTER_COMPLETE",
      "SEALING_COMPLETE",
      "PACKAGING_SNAPSHOT",
      "CARD_ASSIGNED",
      "BAG_FINALIZED",
    ];
    var has = false;
    for (var j = 0; j < events.length; j++) {
      var ev = events[j];
      if (ev.stationId !== sid) continue;
      for (var k = 0; k < wf.length; k++) {
        if (ev.eventType === wf[k]) has = true;
      }
    }
    if (!has) return "NO_ACTIVITY_TODAY";
    return "LIVE_QR";
  }

  function deriveMachine(slot, machine, events, shift) {
    var sid = slot.stationId;
    var se = sid != null ? stationEvents(events, sid) : [];
    var st = String((machine && machine.status) || "idle").toLowerCase();
    if (st === "occupied") st = "running";
    var vis = st === "running" ? "RUNNING" : st === "paused" ? "WAITING" : "IDLE";
    var lt = vis === "RUNNING" ? "run" : vis === "WAITING" ? "wait" : "idle";
    var integ = getIntegration(sid, slot.stationKind, slot.role || null, events);
    if (!sid || integ === "NOT_INTEGRATED") {
      return {
        slot: slot.slot,
        label: slot.label,
        shortLabel: slot.shortLabel,
        canonical: slot.label,
        stationId: sid,
        dataSourceStatus: integ === "NOT_INTEGRATED" ? "NOT_INTEGRATED" : integ,
        statusUi: "NOT INTEGRATED",
        statusLight: "idle",
        rawStatus: st,
        integrationMessage:
          slot.role === "bottle_seal" && integ === "NOT_INTEGRATED"
            ? "Bottle sealing not integrated — no SEALING_COMPLETE at mapped station yet."
            : "Not integrated — QR workflow not configured.",
        dataSourceLine: "Manual / Not connected",
        bagId: "N/A",
        sku: "N/A",
        operatorLabel: "N/A",
        timerMs: null,
        counterDisplay: "N/A",
        throughputUh: "N/A",
        utilizationPct: "N/A",
        oeePct: "N/A",
        cycleElapsedMin: "N/A",
        lastScan: "N/A",
      };
    }
    var hasLive = integ === "LIVE_QR";
    var lastScan = "—";
    if (se.length) {
      var mx = 0;
      for (var i = 0; i < se.length; i++) {
        if (se[i].atMs > mx) mx = se[i].atMs;
      }
      lastScan = new Date(mx).toLocaleTimeString();
    }
    var bag = machine && machine.workflowBagId != null ? String(machine.workflowBagId) : "—";
    var timerMs = null;
    if (machine && machine.occupancyStartedAtMs && st === "running")
      timerMs = Number(machine.occupancyStartedAtMs);
    var delta = sumCounterDeltas(se);
    var ctrDisp = !hasLive ? "N/A" : delta != null ? String(Math.round(delta)) : insuf();
    var thrStr = insuf();
    var thrNum = NaN;
    var runH =
      timerMs != null
        ? Math.max(5 / 3600, (shift.nowMs - timerMs) / 3600000)
        : shift.plannedShiftMinutes > 1
          ? shift.plannedShiftMinutes / 60
          : 1;
    if (hasLive && delta != null && runH > 0) {
      thrNum = delta / runH;
      thrStr = thrNum.toFixed(1);
    }
    var utilDisp = insuf();
    var plannedMin = shift.plannedShiftMinutes || 480;
    if (hasLive && sid != null && se.length >= 2) {
      var mn = se[0].atMs;
      var mm = se[0].atMs;
      for (var u = 0; u < se.length; u++) {
        if (se[u].atMs < mn) mn = se[u].atMs;
        if (se[u].atMs > mm) mm = se[u].atMs;
      }
      var span = (mm - mn) / 60000;
      utilDisp = String(Math.min(100, Math.round((span / plannedMin) * 100)));
    } else if (hasLive && timerMs) {
      utilDisp = String(
        Math.min(100, Math.round(((shift.nowMs - timerMs) / 60000 / plannedMin) * 100)),
      );
    }
    var oee = insuf();
    var rs = rejectStats(events);
    if (hasLive && se.length >= 3) {
      var avail =
        plannedMin > 0
          ? Math.min(
              100,
              (Math.min(shift.nowMs - shift.dayStartMs, plannedMin * 60000) / 60000 / plannedMin) * 50,
            )
          : null;
      var perf = null;
      if (shift.targetThroughputPerHour != null && shift.targetThroughputPerHour > 0 && !isNaN(thrNum)) {
        perf = Math.min(100, (thrNum / shift.targetThroughputPerHour) * 100);
      }
      var qual = rs.qualityPct;
      var ox =
        avail != null && perf != null && qual != null ? clampOee(avail, perf, qual) : null;
      oee = ox != null ? ox.toFixed(1) + "%" : insuf();
    }
    var cycleDisp = insuf();
    if (hasLive && machine && machine.occupancyStartedAtMs)
      cycleDisp = ((shift.nowMs - Number(machine.occupancyStartedAtMs)) / 60000).toFixed(1);

    var dataLine = "Manual / Not connected";
    if (integ === "LIVE_QR") dataLine = "QR / workflow_events";
    else if (integ === "NO_ACTIVITY_TODAY") dataLine = "Station live — no workflow scans today";

    var opLab = "N/A";
    if (hasLive) {
      for (var oi = se.length - 1; oi >= 0; oi--) {
        if (se[oi].operatorLabel && String(se[oi].operatorLabel).trim()) {
          opLab = String(se[oi].operatorLabel);
          break;
        }
      }
      if (opLab === "N/A") opLab = "—";
    }

    return {
      slot: slot.slot,
      label: slot.label,
      shortLabel: slot.shortLabel,
      canonical: slot.label,
      stationId: sid,
      dataSourceStatus: integ,
      statusUi: vis,
      statusLight: lt,
      rawStatus: st,
      integrationMessage:
        integ === "NO_ACTIVITY_TODAY" ? "No workflow scans today." : "",
      dataSourceLine: dataLine,
      bagId: bag,
      sku: "—",
      operatorLabel: opLab,
      timerMs: hasLive ? timerMs : null,
      counterDisplay: !hasLive ? "N/A" : ctrDisp,
      throughputUh: !hasLive || thrStr === insuf() ? "N/A" : thrStr + " u/h",
      utilizationPct: !hasLive || utilDisp === insuf() ? "N/A" : utilDisp + "%",
      oeePct: !hasLive ? "N/A" : oee,
      cycleElapsedMin: !hasLive ? "N/A" : cycleDisp,
      lastScan: !hasLive ? "N/A" : lastScan,
    };
  }

  function deriveDashboardMetrics(inp) {
    var events = inp.events || [];
    var machines = inp.machines || [];
    var slots = inp.slots || [];
    var shift = inp.shiftConfig;
    var bags = inp.bags || [];
    var notes = [];

    if (!shift) {
      return {
        kpis: [],
        machines: [],
        oeeDonut: { total: insuf(), availability: insuf(), performance: insuf(), quality: insuf() },
        notes: [insuf()],
        genealogyBags: bags,
      };
    }

    var byId = {};
    for (var i = 0; i < machines.length; i++) {
      var mm = machines[i];
      byId[Number(mm.id)] = mm;
    }

    var bagsToday = uniqueBags(events);
    var units = sumCounterDeltas(events);
    var plannedMin = shift.plannedShiftMinutes || 1;
    var elapsedMin = Math.max(1, (shift.nowMs - shift.dayStartMs) / 60000);
    var rs = rejectStats(events);
    var qualPct = rs.qualityPct;
    var rejectRate = rs.rejectRate;

    var runtimeMin = 0;
    for (var mi = 0; mi < machines.length; mi++) {
      var m = machines[mi];
      var sev = stationEvents(events, Number(m.id));
      if (sev.length >= 2) {
        var a = sev[0].atMs,
          b = sev[0].atMs;
        for (var z = 0; z < sev.length; z++) {
          if (sev[z].atMs < a) a = sev[z].atMs;
          if (sev[z].atMs > b) b = sev[z].atMs;
        }
        runtimeMin += (b - a) / 60000;
      } else if (m.occupancyStartedAtMs && (String(m.status).toLowerCase() === "running" || String(m.status).toLowerCase() === "occupied")) {
        runtimeMin += (shift.nowMs - Number(m.occupancyStartedAtMs)) / 60000;
      }
    }

    var availability =
      runtimeMin > 0 && plannedMin > 0 ? Math.min(100, (runtimeMin / plannedMin) * 100) : null;
    var actualThr = units != null && elapsedMin > 0 ? units / (elapsedMin / 60) : null;
    var perf =
      shift.targetThroughputPerHour != null &&
      shift.targetThroughputPerHour > 0 &&
      actualThr != null
        ? Math.min(100, (actualThr / shift.targetThroughputPerHour) * 100)
        : null;
    var oee =
      availability != null && perf != null && qualPct != null
        ? clampOee(availability, perf, qualPct)
        : null;
    var oeeLabel =
      oee != null
        ? oee.toFixed(1) + "%"
        : availability != null && perf != null
          ? "Est. " +
            ((availability / 100) * (perf / 100) * 85).toFixed(1) +
            "% (quality assumed 85%)"
          : insuf();
    if (qualPct == null && availability != null && perf != null)
      notes.push("Estimated OEE — no structured reject totals.");

    var kpis = [
      {
        id: "bags",
        displayLabel: "Bags Today",
        value: bagsToday,
        valuePct: null,
        formulaNote: "Unique workflow bags with events in window.",
        sparkline: null,
      },
      {
        id: "units",
        displayLabel: "Units Today",
        value: units != null ? Math.round(units) : insuf(),
        valuePct: null,
        formulaNote: "Sum counter deltas and completion counts from payloads.",
        sparkline: null,
      },
      {
        id: "cycles",
        displayLabel: "Production Cycles",
        value: insuf(),
        valuePct: null,
        formulaNote: "See analytics when claim→finalize pairing is derivable.",
        sparkline: null,
      },
      {
        id: "avg_cycle",
        displayLabel: "Avg Cycle Time",
        value: insuf(),
        valuePct: null,
        formulaNote: "Requires paired cycle windows in events.",
        sparkline: null,
      },
      {
        id: "oee",
        displayLabel: qualPct != null ? "OEE" : "Estimated OEE (quality unknown)",
        value: oeeLabel,
        valuePct: oee,
        formulaNote:
          "OEE = A×P×Q; components shown when each input exists (never >100%).",
        sparkline: null,
      },
      {
        id: "on_time",
        displayLabel: "On-Time Completion",
        value: shift.productionDueMs == null ? "No target set" : insuf(),
        valuePct: null,
        formulaNote: "Needs planned due vs finalize timestamps.",
        sparkline: null,
      },
      {
        id: "rework",
        displayLabel: "Reject Rate",
        valuePct: rejectRate,
        value: rejectRate != null ? rejectRate.toFixed(2) + "%" : "No reject data",
        formulaNote: "CARD_REJECT/FORCE vs counter totals (approximation).",
        sparkline: null,
      },
    ];

    var dm = [];
    for (var si = 0; si < slots.length; si++) {
      var sl = slots[si];
      var mach = sl.stationId != null ? byId[Number(sl.stationId)] : undefined;
      dm.push(deriveMachine(sl, mach, events, shift));
    }

    var donut = {
      total: oee != null ? oee.toFixed(2) + "%" : insuf(),
      availability: availability != null ? availability.toFixed(2) + "%" : insuf(),
      performance: perf != null ? perf.toFixed(2) + "%" : insuf(),
      quality: qualPct != null ? qualPct.toFixed(2) + "%" : "No reject data",
    };

    return {
      kpis: kpis,
      machines: dm,
      oeeDonut: donut,
      notes: notes,
      genealogyBags: bags,
    };
  }

  var RULES = [
    { key: "recv", label: "Received", fn: function (e) {
        return /RECEIVE|RECEIVING|INTAKE/i.test(String(e.eventType));
      } },
    { key: "m1", label: "Assigned to station · claim", fn: function (e) {
        return e.eventType === "BAG_CLAIMED";
      } },
    { key: "bst", label: "Blister Start", fn: function (e) {
        return e.eventType === "BLISTER_START";
      } },
    { key: "bend", label: "Blister Complete", fn: function (e) {
        return e.eventType === "BLISTER_COMPLETE";
      } },
    { key: "pstg", label: "Staging", fn: function (e) {
        return /STAGING/i.test(String(e.eventType));
      } },
    { key: "hs0", label: "Heat Seal Start", fn: function (e) {
        return /SEALING_START/i.test(String(e.eventType));
      } },
    { key: "hs1", label: "Heat Seal Complete", fn: function (e) {
        return e.eventType === "SEALING_COMPLETE";
      } },
    { key: "pkg0", label: "Packaging Start", fn: function (e) {
        return /PACKAGING.*START/i.test(String(e.eventType));
      } },
    { key: "pkg1", label: "Packaging Complete", fn: function (e) {
        return e.eventType === "PACKAGING_SNAPSHOT";
      } },
    { key: "fg", label: "Finished Goods", fn: function (e) {
        return e.eventType === "BAG_FINALIZED";
      } },
  ];

  function deriveBagGenealogy(bagId, eventsAll, bags) {
    var ev = eventsAll
      .filter(function (e) {
        return e.bagId === bagId;
      })
      .sort(function (a, b) {
        return a.atMs - b.atMs;
      });
    var bm = {};
    for (var i = 0; i < bags.length; i++) {
      if (bags[i].id === bagId) bm = bags[i];
    }

    var used = {};
    function take(rule) {
      for (var i = 0; i < ev.length; i++) {
        if (used[i]) continue;
        if (rule.fn(ev[i])) {
          used[i] = true;
          return ev[i];
        }
      }
      return null;
    }
    var traceLines = [];
    var prev = null,
      dwellAcc = 0;
    for (var r = 0; r < RULES.length; r++) {
      var rule = RULES[r];
      var row = take(rule);
      var pending = !row;
      var dwell = null;
      if (row) {
        if (prev != null) {
          dwell = (row.atMs - prev) / 60000;
          dwellAcc += dwell;
        }
        prev = row.atMs;
      }
      var ctr = "—";
      if (row) {
        if (row.counterStart != null || row.counterEnd != null)
          ctr =
            String(row.counterStart != null ? row.counterStart : "—") +
            " → " +
            String(row.counterEnd != null ? row.counterEnd : "—");
        else if (row.countTotal != null) ctr = String(row.countTotal);
        else if (row.totalDisplayCount != null) ctr = "disp " + row.totalDisplayCount;
        else if (row.displayCount != null) ctr = "disp " + row.displayCount;
      }
      traceLines.push({
        key: rule.key,
        label: rule.label,
        pending: pending,
        atMs: row ? row.atMs : null,
        machineLabel: row && row.stationId != null ? "Station " + row.stationId : "",
        stationId: row ? row.stationId : null,
        operatorLabel: row && row.operatorLabel ? row.operatorLabel : "",
        counterReading: pending ? "" : ctr,
        dwellFromPrevMinutes: dwell,
        statusBadge: pending ? "Pending" : "Done",
      });
    }
    var first = ev[0] ? ev[0].atMs : null;
    var last = ev.length ? ev[ev.length - 1].atMs : null;
    var elapsed = first != null && last != null ? (last - first) / 60000 : null;

    return {
      bagId: bagId,
      sku: bm.sku || "—",
      receivedQtyDisplay: bm.qtyReceived != null ? String(bm.qtyReceived) : "—",
      traceLines: traceLines,
      totals: {
        elapsedMinutes: elapsed,
        dwellMinutes: dwellAcc > 0 ? dwellAcc : null,
        message: ev.length === 0 ? insuf() : "",
      },
    };
  }

  global.MesMetrics = {
    deriveDashboardMetrics: deriveDashboardMetrics,
    deriveBagGenealogy: deriveBagGenealogy,
    deriveQueueAging: function () {
      return { zones: [] };
    },
    deriveBottleneck: function () {
      return { label: null, stageId: null };
    },
    getMachineIntegrationStatus: getIntegration,
    insuf: insuf,
  };
})(typeof globalThis !== "undefined" ? globalThis : window);
