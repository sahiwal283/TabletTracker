(function () {
  // Conflict-resolved metrics layer: event-derived values only.
  function asNum(v) {
    var n = Number(v);
    return Number.isFinite(n) ? n : null;
  }

  function clamp(n, min, max) {
    return Math.max(min, Math.min(max, n));
  }

  function todayWindow(shiftConfig) {
    var now = asNum(shiftConfig && shiftConfig.nowMs) || Date.now();
    var dayStart = asNum(shiftConfig && shiftConfig.dayStartMs);
    if (dayStart == null) {
      var d = new Date(now);
      d.setHours(0, 0, 0, 0);
      dayStart = d.getTime();
    }
    return { now: now, dayStart: dayStart };
  }

  function eventMachineId(ev) {
    return asNum(ev && (ev.stationId != null ? ev.stationId : ev.machineId));
  }

  function eventBagId(ev) {
    return asNum(ev && (ev.bagId != null ? ev.bagId : ev.workflowBagId));
  }

  function counterDelta(ev) {
    var end = asNum(ev && ev.counterEnd);
    var start = asNum(ev && ev.counterStart);
    if (end != null && start != null && end >= start) return end - start;
    var total = asNum(ev && ev.countTotal);
    return total != null && total >= 0 ? total : 0;
  }

  function isFinalPackagingSnapshot(ev) {
    var t = String((ev && ev.eventType) || "").toUpperCase();
    return t === "PACKAGING_SNAPSHOT" && String((ev && ev.reason) || "").toLowerCase() === "final_submit";
  }

  /** Packaging snapshots that represent operator-entered output segments for Command Center. */
  function isOpsPackagingOutputSnapshot(ev) {
    var t = String((ev && ev.eventType) || "").toUpperCase();
    if (t !== "PACKAGING_SNAPSHOT") return false;
    var r = String((ev && ev.reason) || "").toLowerCase();
    return r === "final_submit" || r === "paused_end_of_day" || r === "partial_packaging" || r === "out_of_packaging";
  }

  function displayCount(ev) {
    var n = asNum(ev && (
      ev.totalDisplayCount != null ? ev.totalDisplayCount :
      ev.displayCount != null ? ev.displayCount : ev.countTotal
    ));
    return n != null && n >= 0 ? n : 0;
  }

  /** Total displays for a packaging count segment: cases × displays_per_case + loose (bag.product). */
  function finalSubmitDisplayTotal(ev, bagsById) {
    var bagKey = eventBagId(ev);
    var bag = bagKey != null ? (bagsById || {})[String(bagKey)] : null;
    var dpc =
      asNum(bag && (bag.displaysPerCase != null ? bag.displaysPerCase : bag.displays_per_case)) ||
      asNum(ev && (ev.productDisplaysPerCase != null ? ev.productDisplaysPerCase : ev.product_displays_per_case)) ||
      0;
    var breakdown = !!(ev && ev.packagingCaseBreakdown);
    if (breakdown) {
      var cases = asNum(ev.caseCount);
      if (cases == null || cases < 0) cases = 0;
      var loose = asNum(ev.looseDisplayCount != null ? ev.looseDisplayCount : ev.displayCount);
      if (loose == null || loose < 0) loose = 0;
      return Math.max(0, cases * dpc + loose);
    }
    return displayCount(ev);
  }

  function rejectUnits(ev) {
    var t = String((ev && ev.eventType) || "").toUpperCase();
    var looksReject = t.indexOf("REJECT") >= 0 || t.indexOf("REWORK") >= 0 || t === "CARD_FORCE_RELEASED";
    var reopened = asNum(ev && ev.cardsReopened);
    if (reopened != null && reopened >= 0 && t === "PACKAGING_SNAPSHOT") return reopened;
    if (!looksReject) return null;
    var explicit = asNum(ev && (ev.rejectUnits != null ? ev.rejectUnits : ev.reworkUnits));
    if (explicit != null && explicit >= 0) return explicit;
    var total = asNum(ev && ev.countTotal);
    if (total != null && total >= 0) return total;
    return 1;
  }

  function isCompletedEvent(ev) {
    var t = String((ev && ev.eventType) || "").toUpperCase();
    return t === "BLISTER_COMPLETE" || t === "SEALING_COMPLETE" || t === "PACKAGING_SNAPSHOT" || t === "BAG_FINALIZED";
  }

  function bagMap(bags) {
    var m = {};
    (bags || []).forEach(function (b) {
      if (b && b.id != null) m[String(b.id)] = b;
    });
    return m;
  }

  function getMachineIntegrationStatus(machineId, events, config) {
    var mid = asNum(machineId);
    if (mid == null) return "NOT_INTEGRATED";
    var cfg = config || {};
    var configured = !cfg.configuredMachineIds || cfg.configuredMachineIds.indexOf(mid) >= 0;
    var manual = cfg.manualMachineIds && cfg.manualMachineIds.indexOf(mid) >= 0;
    var forcedOff = cfg.forceNotIntegratedMachineIds && cfg.forceNotIntegratedMachineIds.indexOf(mid) >= 0;
    if (forcedOff || !configured) return "NOT_INTEGRATED";
    var win = todayWindow(cfg);
    var hasToday = (events || []).some(function (e) {
      var at = asNum(e && e.atMs);
      return eventMachineId(e) === mid && at != null && at >= win.dayStart;
    });
    if (manual) return "MANUAL_ENTRY";
    return hasToday ? "LIVE_QR" : "NO_ACTIVITY_TODAY";
  }

  function deriveMachineMetrics(machineId, events, shiftConfig, machineConfig) {
    var win = todayWindow(shiftConfig);
    var ms = (events || []).filter(function (e) {
      return eventMachineId(e) === asNum(machineId) && asNum(e.atMs) != null && asNum(e.atMs) >= win.dayStart;
    });
    var runtimeMin = 0;
    var cycles = [];
    var lastScan = null;
    var currentBag = null;
    var operator = null;
    var completedUnits = 0;
    var rejects = 0;
    var startByBag = {};

    var role = String(machineConfig && (machineConfig.machine_role || machineConfig.machineRole) || "").toLowerCase();
    var stationKind = String(machineConfig && (machineConfig.station_kind || machineConfig.stationKind) || "").toLowerCase();
    var unitsPerCycle = asNum(machineConfig && (machineConfig.cards_per_turn != null ? machineConfig.cards_per_turn : machineConfig.cardsPerTurn)) || 1;

    ms.forEach(function (e) {
      var et = String(e.eventType || "").toUpperCase();
      var at = asNum(e.atMs);
      if (at != null && (lastScan == null || at > lastScan)) lastScan = at;
      var bid = eventBagId(e);
      if (bid != null) currentBag = bid;
      if (e.operatorLabel) operator = String(e.operatorLabel);

      if (et === "BAG_CLAIMED" || et === "STATION_RESUMED") {
        if (bid != null) startByBag[String(bid)] = at;
      }
      if (isCompletedEvent(e)) {
        // For blister/sealing stations, counters represent cycles.
        // Convert to real output using the configured units-per-cycle.
        var eventUnits = counterDelta(e);
        if (role === "blister" || stationKind === "blister" || role === "sealing" || stationKind === "sealing") {
          eventUnits = eventUnits * unitsPerCycle;
        }
        completedUnits += eventUnits;
        if (bid != null) {
          var st = startByBag[String(bid)];
          if (st != null && at != null && at > st) {
            var cm = (at - st) / 60000;
            cycles.push(cm);
            runtimeMin += cm;
          }
        }
      }
      var rv = rejectUnits(e);
      if (rv != null && rv > 0) rejects += rv;
    });

    var targetTp = asNum(shiftConfig && shiftConfig.targetThroughputPerHour);
    var plannedShift = asNum(shiftConfig && shiftConfig.plannedShiftMinutes) || Math.max(1, (win.now - win.dayStart) / 60000);
    var runtimeHours = runtimeMin / 60;
    var throughput = runtimeHours > 0 ? completedUnits / runtimeHours : null;
    var availability = plannedShift > 0 ? clamp((runtimeMin / plannedShift) * 100, 0, 100) : null;
    var performance = targetTp && throughput != null ? clamp((throughput / targetTp) * 100, 0, 100) : null;
    var hasRejectData = ms.some(function (e) { return rejectUnits(e) != null; });
    var quality = hasRejectData && completedUnits > 0 ? clamp(((completedUnits - rejects) / completedUnits) * 100, 0, 100) : null;

    var oee = null;
    var oeeLabel = "Insufficient data";
    if (availability != null && performance != null && quality != null) {
      oee = clamp((availability / 100) * (performance / 100) * (quality / 100) * 100, 0, 100);
      oeeLabel = oee.toFixed(1) + "%";
    } else if (availability != null && performance != null) {
      oee = clamp((availability / 100) * (performance / 100) * 100, 0, 100);
      oeeLabel = "Estimated OEE " + oee.toFixed(1) + "%";
    }

    return {
      machineId: machineId,
      eventsCount: ms.length,
      currentBagId: currentBag,
      lastScanMs: lastScan,
      operator: operator,
      completedUnits: completedUnits,
      avgCycleMinutes: cycles.length ? cycles.reduce(function (a, b) { return a + b; }, 0) / cycles.length : null,
      runtimeMinutes: runtimeMin,
      throughputPerHour: throughput,
      utilizationPct: availability,
      performancePct: performance,
      qualityPct: quality,
      oeePct: oee,
      oeeLabel: oeeLabel,
      rejectRateLabel: quality == null ? "No reject data" : (100 - quality).toFixed(2) + "%",
      targetLabel: targetTp ? targetTp.toFixed(1) + " u/h" : "No target set",
    };
  }

  function deriveQueueAging(events) {
    var now = Date.now();
    var enter = {};
    var queues = [];
    (events || []).forEach(function (e) {
      var t = String(e.eventType || "").toUpperCase();
      var bid = eventBagId(e);
      if (bid == null) return;
      if (t.indexOf("STAGING") >= 0) {
        enter[String(bid)] = asNum(e.atMs);
      }
      if (t === "SEALING_COMPLETE" || t === "PACKAGING_SNAPSHOT" || t === "BAG_FINALIZED") {
        delete enter[String(bid)];
      }
    });
    Object.keys(enter).forEach(function (k) {
      if (enter[k] != null) queues.push({ bagId: Number(k), ageMinutes: Math.max(0, (now - enter[k]) / 60000) });
    });
    return queues.sort(function (a, b) { return b.ageMinutes - a.ageMinutes; });
  }


  function deriveStagingBags(events) {
    var now = Date.now();
    var byBag = {};
    (events || []).forEach(function (e) {
      var bagId = eventBagId(e);
      if (bagId == null) return;
      var et = String(e.eventType || "").toUpperCase();
      var at = asNum(e.atMs);
      var row = byBag[String(bagId)] || { bagId: bagId, enteredAtMs: null, lastStationId: null, lastEventType: null };
      row.lastStationId = eventMachineId(e);
      row.lastEventType = et;
      if (et === "BLISTER_COMPLETE" || et === "SEALING_COMPLETE" || et.indexOf("STAGING") >= 0) {
        row.enteredAtMs = at;
      }
      if (et === "BAG_CLAIMED" || et === "PACKAGING_SNAPSHOT" || et === "BAG_FINALIZED") {
        row.enteredAtMs = null;
      }
      byBag[String(bagId)] = row;
    });
    return Object.keys(byBag)
      .map(function (k) { return byBag[k]; })
      .filter(function (r) { return r.enteredAtMs != null; })
      .map(function (r) {
        return {
          bagId: r.bagId,
          enteredAtMs: r.enteredAtMs,
          idleMinutes: Math.max(0, (now - r.enteredAtMs) / 60000),
          lastStationId: r.lastStationId,
          lastStationLabel: r.lastStationId != null ? "Station " + r.lastStationId : "—",
          lastEventType: r.lastEventType || "—",
        };
      })
      .sort(function (a, b) { return a.enteredAtMs - b.enteredAtMs; });
  }
  function deriveBottleneck(events) {
    var q = deriveQueueAging(events);
    if (!q.length) return { station: "No bottleneck", reason: "No active staged queue" };
    return {
      station: "Staging",
      reason: "Oldest queue dwell " + q[0].ageMinutes.toFixed(1) + " min",
      bagId: q[0].bagId,
    };
  }

  function deriveBagGenealogy(bagId, events, bags) {
    var bid = asNum(bagId);
    if (bid == null) return { traceLines: [], totals: { message: "Insufficient data" } };
    var bagInfo = bagMap(bags)[String(bid)] || {};
    var blisterSteps = [
      { key: "RECEIVED", label: "Received", match: ["BAG_RECEIVED", "CARD_ASSIGNED"] },
      { key: "ASSIGNED", label: "Assigned to Blister Line", match: ["BAG_CLAIMED"] },
      { key: "BLISTER_START", label: "Blister Start", match: ["BAG_CLAIMED"] },
      { key: "BLISTER_COMPLETE", label: "Blister Complete", match: ["BLISTER_COMPLETE"] },
      { key: "POST_BLISTER", label: "Post-Blister Staging", match: ["STAGING_POST_BLISTER"] },
      { key: "HEAT_START", label: "Heat Seal Start", match: ["STATION_RESUMED", "BAG_CLAIMED"] },
      { key: "HEAT_COMPLETE", label: "Heat Seal Complete", match: ["SEALING_COMPLETE"] },
      { key: "PACK_START", label: "Packaging Start", match: ["PACKAGING_START", "BAG_CLAIMED"] },
      { key: "PACK_COMPLETE", label: "Packaging Complete", match: ["PACKAGING_SNAPSHOT"] },
      { key: "FINISHED", label: "Finished Goods", match: ["BAG_FINALIZED"] },
    ];
    var bottleSteps = [
      { key: "RECEIVED", label: "Received", match: ["BAG_RECEIVED", "CARD_ASSIGNED"] },
      { key: "ASSIGNED", label: "Assigned to Bottle Line", match: ["BAG_CLAIMED"] },
      { key: "HANDPACK_START", label: "Hand Pack Start", match: ["BAG_CLAIMED"] },
      { key: "HANDPACK_COMPLETE", label: "Hand Pack Complete", match: ["BOTTLE_HANDPACK_COMPLETE"] },
      { key: "POST_HANDPACK", label: "Post-Handpack Staging", match: ["STAGING_POST_HANDPACK"] },
      { key: "STICKER_START", label: "Stickering Start", match: ["STATION_RESUMED", "BAG_CLAIMED"] },
      { key: "STICKER_COMPLETE", label: "Stickering Complete", match: ["BOTTLE_STICKER_COMPLETE"] },
      { key: "CAP_SEAL_START", label: "Cap Seal Start", match: ["STATION_RESUMED", "BAG_CLAIMED"] },
      { key: "CAP_SEAL_COMPLETE", label: "Cap Seal Complete", match: ["BOTTLE_CAP_SEAL_COMPLETE"] },
      { key: "PACK_START", label: "Packaging Start", match: ["PACKAGING_START", "BAG_CLAIMED"] },
      { key: "PACK_COMPLETE", label: "Packaging Complete", match: ["PACKAGING_SNAPSHOT"] },
      { key: "FINISHED", label: "Finished Goods", match: ["BAG_FINALIZED"] },
    ];

    var bagEvents = (events || []).filter(function (e) { return eventBagId(e) === bid; }).sort(function (a, b) { return (a.atMs || 0) - (b.atMs || 0); });
    function buildLines(steps) {
      var prevAt = null;
      return steps.map(function (step) {
        var found = bagEvents.find(function (e) { return step.match.indexOf(String(e.eventType || "").toUpperCase()) >= 0; });
        if (!found) return { label: step.label, pending: true, statusBadge: "Pending" };
        var at = asNum(found.atMs);
        var dwell = prevAt != null && at != null ? (at - prevAt) / 60000 : null;
        prevAt = at;
        return {
          label: step.label,
          atMs: at,
          machineLabel: found.stationId != null ? "M" + found.stationId : null,
          operatorLabel: found.operatorLabel || null,
          counterReading: found.counterEnd != null ? found.counterEnd : found.countTotal,
          dwellFromPrevMinutes: dwell,
          statusBadge: "Done",
        };
      });
    }
    if (!bagEvents.length) {
      var emptyBlister = blisterSteps.map(function (s) { return { label: s.label, pending: true, statusBadge: "Pending" }; });
      var emptyBottle = bottleSteps.map(function (s) { return { label: s.label, pending: true, statusBadge: "Pending" }; });
      return {
        bagId: bid,
        sku: bagInfo.sku || "—",
        receivedQtyDisplay: "—",
        traceLines: emptyBlister,
        traceGroups: [
          { key: "blister", label: "Blister/Card Line", lines: emptyBlister },
          { key: "bottle", label: "Bottle Line", lines: emptyBottle },
        ],
        totals: { message: "Insufficient data" },
      };
    }

    var blisterLines = buildLines(blisterSteps);
    var bottleLines = buildLines(bottleSteps);
    var hasBottleEvents = bagEvents.some(function (e) {
      var et = String(e.eventType || "").toUpperCase();
      return et.indexOf("BOTTLE_") === 0;
    });
    var lines = hasBottleEvents ? bottleLines : blisterLines;

    var first = asNum(bagEvents[0].atMs);
    var last = asNum(bagEvents[bagEvents.length - 1].atMs);
    return {
      bagId: bid,
      sku: bagInfo.sku || "—",
      receivedQtyDisplay: bagInfo.qtyReceived != null ? String(bagInfo.qtyReceived) : "N/A",
      traceLines: lines,
      traceGroups: [
        { key: "blister", label: "Blister/Card Line", lines: blisterLines },
        { key: "bottle", label: "Bottle Line", lines: bottleLines },
      ],
      totals: {
        elapsedMinutes: first != null && last != null ? (last - first) / 60000 : null,
        dwellMinutes: lines.reduce(function (a, l) { return a + (l.dwellFromPrevMinutes || 0); }, 0),
      },
    };
  }

  function deriveDashboardMetrics(events, machines, bags, shiftConfig) {
    if (events && events.events && machines == null) {
      var inp = events;
      events = inp.events;
      machines = inp.machines;
      bags = inp.bags;
      shiftConfig = inp.shiftConfig;
    }
    var win = todayWindow(shiftConfig);
    var todays = (events || []).filter(function (e) { return asNum(e.atMs) != null && asNum(e.atMs) >= win.dayStart; });
    var bagsById = bagMap(bags);
    var machineById = {};
    (machines || []).forEach(function (m) {
      if (m && m.id != null) machineById[String(m.id)] = m;
    });
    function completedUnitsForEvent(e) {
      var units = counterDelta(e);
      var m = machineById[String(eventMachineId(e))] || {};
      var role = String(m.machine_role || m.machineRole || "").toLowerCase();
      var stationKind = String(m.station_kind || m.stationKind || "").toLowerCase();
      if (role === "blister" || stationKind === "blister" || role === "sealing" || stationKind === "sealing") {
        units = units * (asNum(m.cards_per_turn != null ? m.cards_per_turn : m.cardsPerTurn) || 1);
      }
      return units;
    }
    var bagSet = {};
    var units = 0;
    var displays = 0;
    var flavorsWithDisplays = {};
    var cycles = [];
    var rejectTotal = 0;
    var hasRejectData = false;
    var completeTotal = 0;
    var onTimeTotal = 0;
    var finalizedBagSet = {};
    var displayCaseTotal = 0;
    var displayCaseDpcValues = {};
    todays.forEach(function (e) {
      var bid = eventBagId(e);
      if (bid != null) bagSet[String(bid)] = true;
      if ((String(e.eventType || "").toUpperCase() === "BAG_FINALIZED" || isFinalPackagingSnapshot(e)) && bid != null) {
        finalizedBagSet[String(bid)] = true;
      }
      if (isOpsPackagingOutputSnapshot(e)) {
        var dc = finalSubmitDisplayTotal(e, bagsById);
        displays += dc;
        if (e && e.packagingCaseBreakdown) {
          var cases = asNum(e.caseCount);
          if (cases != null && cases >= 0) displayCaseTotal += cases;
          var b = bid != null ? (bagsById[String(bid)] || {}) : {};
          var dpc =
            asNum(b.displaysPerCase != null ? b.displaysPerCase : b.displays_per_case) ||
            asNum(e.productDisplaysPerCase != null ? e.productDisplaysPerCase : e.product_displays_per_case);
          if (dpc != null && dpc > 0) displayCaseDpcValues[String(dpc)] = true;
        }
        if (dc > 0 && bid != null) {
          var bi = bagsById[String(bid)] || {};
          flavorsWithDisplays[String(bi.sku || bi.productLabel || bid)] = true;
        }
      }
      if (isCompletedEvent(e)) {
        units += completedUnitsForEvent(e);
        completeTotal += 1;
        if (shiftConfig && shiftConfig.productionDueMs && asNum(e.atMs) != null && asNum(e.atMs) <= asNum(shiftConfig.productionDueMs)) {
          onTimeTotal += 1;
        }
      }
      var ru = rejectUnits(e);
      if (ru != null) {
        hasRejectData = true;
        rejectTotal += ru;
      }
    });

    (machines || []).forEach(function (m) {
      var mm = deriveMachineMetrics(m.id, todays, shiftConfig, m);
      if (mm.avgCycleMinutes != null) cycles.push(mm.avgCycleMinutes);
    });

    var avgCycle = cycles.length ? cycles.reduce(function (a, b) { return a + b; }, 0) / cycles.length : null;
    var q = deriveQueueAging(todays);
    var bottleneck = deriveBottleneck(todays);

    var machineMetrics = (machines || []).map(function (m) {
      var mm = deriveMachineMetrics(m.id, todays, shiftConfig, m);
      var status = getMachineIntegrationStatus(m.id, todays, {
        dayStartMs: win.dayStart,
        configuredMachineIds: (machines || []).map(function (x) { return x.id; }),
      });
      return Object.assign({ integrationStatus: status }, mm, m);
    });

    var oeeValues = machineMetrics.map(function (m) { return m.oeePct; }).filter(function (v) { return v != null; });
    var oeeAvg = oeeValues.length ? oeeValues.reduce(function (a, b) { return a + b; }, 0) / oeeValues.length : null;
    var targetTp = asNum(shiftConfig && shiftConfig.targetThroughputPerHour);
    var elapsedHours = Math.max((win.now - win.dayStart) / 3600000, 1 / 60);
    var plannedMin = asNum(shiftConfig && shiftConfig.plannedShiftMinutes) || Math.max(1, (win.now - win.dayStart) / 60000);
    var runtimeMin = machineMetrics.reduce(function (sum, m) { return sum + (asNum(m.runtimeMinutes) || 0); }, 0);
    var availabilityEstimate = plannedMin > 0
      ? clamp(((runtimeMin > 0 ? runtimeMin : Math.min(plannedMin, (win.now - win.dayStart) / 60000)) / plannedMin) * 100, 0, 100)
      : null;
    var actualDisplayRate = displays / elapsedHours;
    var performanceEstimate = targetTp && targetTp > 0 ? clamp((actualDisplayRate / targetTp) * 100, 0, 100) : null;
    var qualityEstimate = hasRejectData && displays > 0 ? clamp(((displays - rejectTotal) / displays) * 100, 0, 100) : (displays > 0 ? 100 : null);
    var aggregateOee = null;
    if (availabilityEstimate != null && performanceEstimate != null && qualityEstimate != null) {
      aggregateOee = clamp((availabilityEstimate / 100) * (performanceEstimate / 100) * (qualityEstimate / 100) * 100, 0, 100);
    }
    if (aggregateOee != null) oeeAvg = aggregateOee;

    return {
      kpis: [
        { id: "bags", value: Object.keys(finalizedBagSet).length, displayLabel: "Completed Bags", formulaNote: "Distinct bags with final packaging/BAG_FINALIZED today", sparkline: Object.keys(finalizedBagSet).length ? [0, Object.keys(finalizedBagSet).length] : [] },
        { id: "units", value: displays, displayLabel: "Final Displays", formulaNote: "PACKAGING_SNAPSHOT count segments: case_count × displays_per_case + loose", sparkline: displays ? [0, displays] : [], caseCount: displayCaseTotal, displaysPerCaseValues: Object.keys(displayCaseDpcValues).map(function (v) { return Number(v); }).filter(function (v) { return Number.isFinite(v); }).sort(function (a, b) { return a - b; }) },
        { id: "cycles", value: Object.keys(flavorsWithDisplays).length, displayLabel: "Flavors Produced", formulaNote: "Flavor/display breakdown shown below" },
        { id: "avg_cycle", value: avgCycle != null ? avgCycle.toFixed(1) + " min" : "Insufficient data", displayLabel: "Avg Cycle Time" },
        { id: "oee", value: oeeAvg != null ? Math.min(100, oeeAvg).toFixed(1) + "%" : "Insufficient data", displayLabel: "OEE" },
        { id: "on_time", value: shiftConfig && shiftConfig.productionDueMs ? (completeTotal ? clamp((onTimeTotal / completeTotal) * 100, 0, 100).toFixed(1) + "%" : "Insufficient data") : "No target set", displayLabel: "On-Time Completion" },
        { id: "rework", value: hasRejectData ? rejectTotal : "No reject data", displayLabel: "Ripped Cards" },
      ],
      machines: machineMetrics,
      queues: q,
      bottleneck: bottleneck,
      stagingBags: deriveStagingBags(todays),
      genealogySelectedBagId: Object.keys(bagSet).length ? Number(Object.keys(bagSet).pop()) : null,
      oeeDonut: {
        total: oeeAvg != null ? Math.min(100, oeeAvg).toFixed(1) + "%" : "Insufficient data",
        availability: availabilityEstimate != null ? availabilityEstimate.toFixed(1) + "%" : "Insufficient data",
        performance: performanceEstimate != null ? performanceEstimate.toFixed(1) + "%" : "No target set",
        quality: hasRejectData && units > 0 ? (100 - clamp((rejectTotal / units) * 100, 0, 100)).toFixed(1) + "%" : "No reject data",
      },
      notes: ["No fake counters", "No fake operators", "Bottle line requires real QR events"],
    };
  }

  window.OpsMetrics = {
    deriveDashboardMetrics: deriveDashboardMetrics,
    deriveMachineMetrics: deriveMachineMetrics,
    deriveBagGenealogy: deriveBagGenealogy,
    deriveQueueAging: deriveQueueAging,
    deriveBottleneck: deriveBottleneck,
    deriveStagingBags: deriveStagingBags,
    getMachineIntegrationStatus: getMachineIntegrationStatus,
    finalSubmitDisplayTotal: finalSubmitDisplayTotal,
  };
  window.MesMetrics = window.OpsMetrics;
})();
