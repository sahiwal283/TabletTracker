
(function () {
  let html5QrCode = null;
  let html5QrCodeVerify = null;
  let html5QrCodeSource = null;
  let productScanDone = false;
  let verifyScanDone = false;
  let sourceScanDone = false;
  let hasLoadedBag = false;
  let stationClaimed = false;
  /** When true, bag was paused at this station — submit/pause blocked until Resume (server: resume_required). */
  let stationNeedsResume = false;
  let occupancyTimerHandle = null;
  /** Station has an active bag from /floor/api/station (last poll). */
  let stationHasOccupantApi = false;
  /** Block generic scan / refresh until the station occupant card is loaded (or verify flow). */
  let stationOccupancyGate = false;
  /** Server reports bag paused at this station (resume required). */
  let occupancyIsPaused = false;
  let occupancyPauseDetails = null;
  /** Expected bag card scan_token for this station occupancy. */
  let expectedOccupantCardToken = null;
  /** Showing scan/input to verify card after Pause / End / Resume. */
  let occupancyVerifyOpen = false;
  let lastOccupancyVerifyMode = null;
  /** After verifying for "End run", show only submit until counts are saved (hide pause/hand pack on blister). */
  let occupancyGateIntentEndRun = false;
  /** After occupancy verify, keep only the selected action visible. */
  let occupancyGateForcedAction = null;
  /** Packaging: pick = choose End / Pause / Taken; then only fields for that path. */
  let packagingUiPhase = 'pick';
  let pendingProductMapProductId = null;
  const isAdminUser = !!Number(window.WF_IS_ADMIN_USER || 0);

  /** Prevent double-submit of the same action (pause vs submit are independent). ~1.5 minutes. */
  var SUBMIT_PAUSE_COOLDOWN_MS = 90 * 1000;
  var cooldownUntil = {};
  var cooldownTimers = {};

  /** Appended after successful count / submit actions (not pause). */
  var MSG_SCAN_NEXT_CARD = ' Scan the next card when ready.';
  /** Shown after end-of-day pause saves the current counts. */
  var MSG_PAUSE_RESUME_TOMORROW = 'Scan same card tomorrow to resume. Have a nice day.';

  const WF_PAGE_SESSION = (crypto.randomUUID && crypto.randomUUID()) || (Date.now() + '-' + Math.random());
  var WF_EMPLOYEE_STORAGE_KEY = 'wf_employee_name';
  function pageSessionId() {
    return WF_PAGE_SESSION;
  }
  function deviceId() {
    const k = 'wf_device_id';
    let v = localStorage.getItem(k);
    if (!v) {
      v = (crypto.randomUUID && crypto.randomUUID()) || (Date.now() + '-' + Math.random());
      localStorage.setItem(k, v);
    }
    return v;
  }
  function statusLine(msg, variant) {
    const fb = document.getElementById('wf-feedback');
    if (fb) {
      fb.textContent = msg || '';
      fb.classList.remove('hidden');
      fb.classList.remove(
        'border-red-200',
        'bg-red-50',
        'text-red-800',
        'border-emerald-200',
        'bg-emerald-50',
        'text-emerald-900',
        'border-slate-200',
        'bg-slate-50',
        'text-slate-800'
      );
      if (variant === 'error') {
        fb.classList.add('border-red-200', 'bg-red-50', 'text-red-800');
      } else if (variant === 'success') {
        fb.classList.add('border-emerald-200', 'bg-emerald-50', 'text-emerald-900');
      } else {
        fb.classList.add('border-slate-200', 'bg-slate-50', 'text-slate-800');
      }
    }
    const legacy = document.getElementById('wf-status');
    if (legacy) legacy.textContent = msg;
  }
  function clearFeedback() {
    var fb = document.getElementById('wf-feedback');
    if (fb) {
      fb.textContent = '';
      fb.classList.add('hidden');
    }
  }
  function setScanSuccessVisible(visible) {
    var panel = document.getElementById('wf-scan-success');
    if (!panel) return;
    panel.classList.toggle('hidden', !visible);
  }

  function clearProductMappingPrompt() {
    pendingProductMapProductId = null;
    var panel = document.getElementById('wf-product-map-panel');
    var opts = document.getElementById('wf-product-map-options');
    var copy = document.getElementById('wf-product-map-copy');
    if (panel) panel.classList.add('hidden');
    if (opts) opts.innerHTML = '';
    if (copy) copy.textContent = '';
  }

  function renderProductMappingPrompt(details) {
    var panel = document.getElementById('wf-product-map-panel');
    var opts = document.getElementById('wf-product-map-options');
    var copy = document.getElementById('wf-product-map-copy');
    if (!panel || !opts || !copy) return;
    var tablet = (details && details.tablet_type_name) || 'this tablet';
    var flow = (details && details.production_flow) || stationKind();
    var candidates = (details && details.candidates) || [];
    opts.innerHTML = '';
    copy.textContent = 'Multiple products can use ' + tablet + ' on this ' + flow + ' station. Select the SKU being made, then the bag will be claimed.';
    candidates.forEach(function (c) {
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'btn-secondary px-4 py-3 text-left text-sm !bg-white !text-slate-900 !border-amber-300 hover:!bg-amber-100';
      btn.textContent = c.product_name || ('Product #' + c.product_id);
      btn.addEventListener('click', function () {
        pendingProductMapProductId = c.product_id || c.id;
        panel.classList.add('hidden');
        statusLine('Product selected — claiming bag…', 'info');
        claimBag().catch(function (e) {
          statusLine(String(e), 'error');
        });
      });
      opts.appendChild(btn);
    });
    panel.classList.remove('hidden');
  }

  var fullscreenSuccessTimer = null;
  var fullscreenSuccessDismissCallback = null;

  function hideFullscreenSuccess() {
    var el = document.getElementById('wf-fullscreen-success');
    if (el) el.classList.add('hidden');
    if (fullscreenSuccessTimer) {
      clearTimeout(fullscreenSuccessTimer);
      fullscreenSuccessTimer = null;
    }
    try {
      document.body.classList.remove('overflow-hidden');
    } catch (_e) {
      /* */
    }
    var cb = fullscreenSuccessDismissCallback;
    fullscreenSuccessDismissCallback = null;
    if (typeof cb === 'function') {
      cb();
    }
  }

  /** Full-screen green check for successful actions (claim, count submit, finalize) — not for bag load only. */
  function showFullscreenSuccess(message, durationMs, onDismiss) {
    var el = document.getElementById('wf-fullscreen-success');
    var msgEl = document.getElementById('wf-fullscreen-success-msg');
    if (!el || !msgEl) return;
    hideFullscreenSuccess();
    msgEl.textContent = message || '';
    fullscreenSuccessDismissCallback = typeof onDismiss === 'function' ? onDismiss : null;
    var ms =
      typeof durationMs === 'number' && durationMs >= 1500
        ? durationMs
        : 3000 + Math.floor(Math.random() * 4001);
    el.classList.remove('hidden');
    try {
      document.body.classList.add('overflow-hidden');
    } catch (_e2) {
      /* */
    }
    fullscreenSuccessTimer = setTimeout(function () {
      hideFullscreenSuccess();
    }, ms);
  }

  function fullscreenSubmitOk(message) {
    showFullscreenSuccess(message, undefined, function () {
      refreshStationOccupancy().catch(function () {});
    });
  }

  function formatElapsedMs(ms) {
    var total = Math.max(0, Math.floor(ms / 1000));
    var h = Math.floor(total / 3600);
    var m = Math.floor((total % 3600) / 60);
    var s = total % 60;
    return String(h).padStart(2, '0') + ':' + String(m).padStart(2, '0') + ':' + String(s).padStart(2, '0');
  }
  function stopOccupancyTimer() {
    if (occupancyTimerHandle) {
      clearInterval(occupancyTimerHandle);
      occupancyTimerHandle = null;
    }
  }

  var pausedUiTimer = null;
  var lastOccStartMs = 0;
  /** Elapsed pause timer uses pause submit time from server, not claim time. */
  var pausedScreenStartMs = 0;

  function stopPausedUiTimer() {
    if (pausedUiTimer) {
      clearInterval(pausedUiTimer);
      pausedUiTimer = null;
    }
  }

  function pausedScreenVisible() {
    var ps = document.getElementById('wf-paused-screen');
    return ps && !ps.classList.contains('hidden');
  }

  function hidePausedStationUi() {
    var ps = document.getElementById('wf-paused-screen');
    var aw = document.getElementById('wf-active-work');
    stopPausedUiTimer();
    if (ps) ps.classList.add('hidden');
    if (aw) aw.classList.remove('hidden');
    try {
      document.body.classList.remove('overflow-hidden');
    } catch (_e) {}
  }

  function showPausedStationUi() {
    var ps = document.getElementById('wf-paused-screen');
    var aw = document.getElementById('wf-active-work');
    var inner = document.getElementById('wf-paused-bag-body');
    var src = document.getElementById('wf-bag-verification-body');
    var elapsed = document.getElementById('wf-paused-elapsed');
    var copy = document.getElementById('wf-paused-copy');
    if (!ps || !elapsed) return;
    stopPausedUiTimer();
    if (inner && src) inner.innerHTML = src.innerHTML;
    ps.classList.remove('hidden');
    if (aw) aw.classList.add('hidden');
    var ob = document.getElementById('wf-occupied-banner');
    if (ob) ob.classList.add('hidden');
    if (copy) {
      var reason = occupancyPauseDetails && occupancyPauseDetails.reason;
      if (reason === 'material_change') {
        var material = String((occupancyPauseDetails && occupancyPauseDetails.material_type) || '').toUpperCase();
        copy.textContent = material
          ? 'Material change saved for ' + material + '. Resume this bag after the machine is ready.'
          : 'Material change saved. Resume this bag after the machine is ready.';
      } else {
        copy.textContent = 'Your pause counts are saved. Have a good evening — see you tomorrow.';
      }
    }
    stopOccupancyTimer();
    var startMs = Number(pausedScreenStartMs);
    if (!Number.isFinite(startMs) || startMs <= 0) {
      startMs = Number(lastOccStartMs);
    }
    if (!Number.isFinite(startMs) || startMs <= 0) {
      elapsed.textContent = '—';
      return;
    }
    function tick() {
      elapsed.textContent = formatElapsedMs(Date.now() - startMs);
    }
    tick();
    pausedUiTimer = setInterval(tick, 1000);
  }

  /** True when this station has no active occupant or the loaded card matches that bag. */
  function sessionMatchesStationOccupant() {
    if (!stationHasOccupantApi || !expectedOccupantCardToken) {
      return true;
    }
    var cur = productInput() ? String(productInput().value || '').trim() : '';
    return hasLoadedBag && cur === expectedOccupantCardToken;
  }

  function syncOccupancyGateFlags() {
    stationOccupancyGate =
      stationHasOccupantApi &&
      !!expectedOccupantCardToken &&
      !sessionMatchesStationOccupant() &&
      !occupancyVerifyOpen;
  }

  /** Info hint for idle stations; hidden when Pause/End/Verify gate is showing (no scan slot yet). */
  function maybeRefreshBagHint() {
    var hideMain =
      occupancyVerifyOpen ||
      (stationHasOccupantApi && !!expectedOccupantCardToken && !sessionMatchesStationOccupant());
    var showChoice =
      stationHasOccupantApi &&
      !!expectedOccupantCardToken &&
      !sessionMatchesStationOccupant() &&
      !occupancyVerifyOpen;
    if (showChoice) {
      clearFeedback();
      return;
    }
    if (hideMain) {
      return;
    }
    if (!hasLoadedBag) {
      statusLine('Scan the bag card or enter the token, then press Enter to load.', 'info');
    }
  }

  function syncIdleStationBanner() {
    var idleBanner = document.getElementById('wf-idle-banner');
    if (!idleBanner || pausedScreenVisible()) return;
    var hideMain =
      occupancyVerifyOpen ||
      (stationHasOccupantApi && !!expectedOccupantCardToken && !sessionMatchesStationOccupant());
    var showChoice =
      stationHasOccupantApi &&
      !!expectedOccupantCardToken &&
      !sessionMatchesStationOccupant() &&
      !occupancyVerifyOpen;
    var show =
      !stationHasOccupantApi &&
      !hasLoadedBag &&
      !occupancyVerifyOpen &&
      !showChoice &&
      !hideMain;
    idleBanner.classList.toggle('hidden', !show);
  }

  function applyOccupancyGateUi() {
    syncOccupancyGateFlags();
    var hideMain =
      occupancyVerifyOpen ||
      (stationHasOccupantApi && !!expectedOccupantCardToken && !sessionMatchesStationOccupant());
    var showChoice =
      stationHasOccupantApi &&
      !!expectedOccupantCardToken &&
      !sessionMatchesStationOccupant() &&
      !occupancyVerifyOpen;

    var cardEntry = document.getElementById('wf-card-entry');
    var fields = document.getElementById('wf-workflow-fields');
    var actions = document.getElementById('wf-workflow-actions');
    var choice = document.getElementById('wf-occupied-choice');
    var verifyPan = document.getElementById('wf-verify-panel');
    var pauseB = document.getElementById('wf-gate-pause');
    var endB = document.getElementById('wf-gate-end');
    var opB = document.getElementById('wf-gate-operator');
    var materialB = document.getElementById('wf-gate-material');
    var takenG = document.getElementById('wf-gate-taken');
    var currentKind = stationKind();
    var isPackaging = currentKind === 'packaging';
    var isBlister = currentKind === 'blister';

    if (verifyPan) {
      verifyPan.classList.toggle('hidden', !occupancyVerifyOpen);
    }

    if (cardEntry) cardEntry.classList.toggle('hidden', hideMain || hasLoadedBag);
    if (fields) fields.classList.toggle('hidden', hideMain);
    if (actions) actions.classList.toggle('hidden', hideMain);

    if (choice && pauseB && endB) {
      if (!showChoice) {
        choice.classList.add('hidden');
        if (takenG) takenG.classList.add('hidden');
      } else {
        choice.classList.remove('hidden');
        if (occupancyIsPaused) {
          // Resume is handled in the paused modal; the gate action row should stay hidden.
          choice.classList.add('hidden');
          pauseB.classList.add('hidden');
          endB.classList.add('hidden');
          if (opB) opB.classList.add('hidden');
          if (materialB) materialB.classList.add('hidden');
          if (takenG) takenG.classList.add('hidden');
        } else {
          pauseB.classList.remove('hidden');
          endB.classList.remove('hidden');
          if (opB) opB.classList.toggle('hidden', !isBlister);
          if (materialB) {
            var showMaterialGate =
              stationKind() === 'blister' || stationKind() === 'combined';
            materialB.classList.toggle('hidden', !showMaterialGate);
          }
          if (takenG) {
            var showTakenGate = isPackaging;
            takenG.classList.toggle('hidden', !showTakenGate);
          }
        }
      }
    }
    if (!isPackaging && takenG) {
      takenG.classList.add('hidden');
    }
    var intentPanGate = document.getElementById('wf-packaging-intent');
    if (intentPanGate && (showChoice || occupancyVerifyOpen)) {
      intentPanGate.classList.add('hidden');
    }
    syncIdleStationBanner();
    maybeRefreshBagHint();
  }

  function openOccupancyVerify(mode) {
    hidePausedStationUi();
    lastOccupancyVerifyMode = mode || null;
    occupancyVerifyOpen = true;
    clearFeedback();
    var inst = document.getElementById('wf-verify-instruction');
    var vi = document.getElementById('wf-verify-input');
    if (vi) vi.value = '';
    if (inst) {
      if (mode === 'pause') {
        inst.textContent = 'Scan the bag card QR to verify before pausing.';
      } else if (mode === 'end') {
        inst.textContent =
          'Scan the bag card QR to verify before ending this run (submit counts).';
      } else if (mode === 'taken') {
        inst.textContent =
          'Scan the bag card QR to verify before recording taken-for-delivery displays.';
      } else if (mode === 'material') {
        inst.textContent =
          'Scan the bag card QR to verify before recording material change.';
      } else if (mode === 'operator') {
        inst.textContent =
          'Scan the bag card QR to verify before recording operator change.';
      } else if (mode === 'resume') {
        inst.textContent = 'Scan the bag card QR to verify, then the station will resume.';
      } else {
        inst.textContent = 'Scan the bag card QR to verify before continuing.';
      }
    }
    applyOccupancyGateUi();
  }

  function cancelOccupancyVerify() {
    occupancyVerifyOpen = false;
    lastOccupancyVerifyMode = null;
    occupancyGateIntentEndRun = false;
    occupancyGateForcedAction = null;
    if (stationKind() === 'packaging') {
      packagingUiPhase = 'pick';
    }
    stopVerifyQrScanner().catch(function () {});
    applyOccupancyGateUi();
    if (occupancyIsPaused && stationNeedsResume) {
      showPausedStationUi();
    }
  }

  async function confirmOccupancyVerify() {
    var vi = document.getElementById('wf-verify-input');
    var tok = vi && String(vi.value || '').trim();
    if (!tok) {
      statusLine('Scan or enter the bag card token.', 'error');
      return;
    }
    var exp = expectedOccupantCardToken && String(expectedOccupantCardToken).trim();
    if (!exp || tok !== exp) {
      statusLine('This QR code does not match the current bag at this station.', 'error');
      return;
    }
    await stopVerifyQrScanner();
    occupancyVerifyOpen = false;
    var gateMode = lastOccupancyVerifyMode;
    var intentEndRun = gateMode === 'end';
    lastOccupancyVerifyMode = null;
    var pin = productInput();
    if (pin) pin.value = tok;
    await refresh();
    if (stationKind() === 'packaging') {
      if (gateMode === 'end') {
        packagingUiPhase = 'end';
        occupancyGateIntentEndRun = true;
        occupancyGateForcedAction = 'end';
      } else if (gateMode === 'pause') {
        packagingUiPhase = 'pause';
        occupancyGateIntentEndRun = false;
        occupancyGateForcedAction = 'pause';
      } else if (gateMode === 'taken') {
        packagingUiPhase = 'taken';
        occupancyGateIntentEndRun = false;
        occupancyGateForcedAction = 'taken';
      } else {
        packagingUiPhase = 'pick';
        occupancyGateIntentEndRun = false;
        occupancyGateForcedAction = null;
      }
    } else {
      if (intentEndRun) {
        occupancyGateIntentEndRun = true;
      }
      occupancyGateForcedAction = gateMode || null;
      if (gateMode === 'material') {
        openMaterialChangePanel();
      }
    }
    configureStationActions();
    applyOccupancyGateUi();
    /* After verify for Resume, server is still paused until STATION_RESUMED — emit it now or UI loops back to paused screen. */
    if (gateMode === 'resume') {
      try {
        await resumeBag();
      } catch (e) {
        statusLine(String(e), 'error');
      }
      return;
    }
    refreshStationOccupancy().catch(function () {});
  }

  function setVerifyScanUi(scanning) {
    var wrap = document.getElementById('wf-verify-reader-wrap');
    var stopBtn = document.getElementById('wf-verify-scan-stop');
    var scanBtn = document.getElementById('wf-verify-scan');
    if (wrap) wrap.classList.toggle('hidden', !scanning);
    if (stopBtn) stopBtn.classList.toggle('hidden', !scanning);
    if (scanBtn) scanBtn.classList.toggle('hidden', scanning);
  }

  async function stopVerifyQrScanner() {
    verifyScanDone = false;
    if (html5QrCodeVerify) {
      try {
        await html5QrCodeVerify.stop();
      } catch (_e) {
        /* */
      }
      try {
        await html5QrCodeVerify.clear();
      } catch (_e2) {
        /* */
      }
      html5QrCodeVerify = null;
    }
    setVerifyScanUi(false);
  }

  async function startVerifyQrScan() {
    if (!stationReady()) {
      statusLine('Error: open this page from your station QR first. Station token is missing.', 'error');
      return;
    }
    if (typeof Html5Qrcode === 'undefined') {
      statusLine('Scanner failed to load. Check your connection and refresh the page.', 'error');
      return;
    }
    await stopVerifyQrScanner();
    verifyScanDone = false;
    var readerId = 'wf-verify-qr-reader';
    var el = document.getElementById(readerId);
    if (!el) return;
    html5QrCodeVerify = new Html5Qrcode(readerId);
    setVerifyScanUi(true);
    statusLine('Point the camera at the bag card QR code.', 'info');
    var config = { fps: 10, qrbox: { width: 250, height: 250 } };
    function onScanSuccess(decodedText) {
      if (verifyScanDone) return;
      var text = String(decodedText || '').trim();
      if (!text) return;
      verifyScanDone = true;
      setTimeout(function () {
        (async function () {
          try {
            await stopVerifyQrScanner();
            var vi = document.getElementById('wf-verify-input');
            if (vi) vi.value = text;
            try {
              if (navigator.vibrate) navigator.vibrate(15);
            } catch (_v) {
              /* */
            }
            statusLine('QR captured. Tap Confirm verification when ready.', 'info');
          } catch (err) {
            statusLine(String(err), 'error');
          }
        })();
      }, 0);
    }
    function onScanFailure() {
      /* ignore */
    }
    try {
      await html5QrCodeVerify.start({ facingMode: 'environment' }, config, onScanSuccess, onScanFailure);
    } catch (e1) {
      try {
        await html5QrCodeVerify.stop();
      } catch (_s) {
        /* */
      }
      try {
        await html5QrCodeVerify.clear();
      } catch (_c) {
        /* */
      }
      html5QrCodeVerify = null;
      try {
        var devices = await Html5Qrcode.getCameras();
        if (!devices || devices.length === 0) {
          throw e1;
        }
        var back =
          devices.find(function (d) {
            return /back|rear|environment|wide/i.test(d.label || '');
          }) || devices[0];
        html5QrCodeVerify = new Html5Qrcode(readerId);
        await html5QrCodeVerify.start(back.id, config, onScanSuccess, onScanFailure);
      } catch (e2) {
        await stopVerifyQrScanner();
        var msg = (e1 && e1.message) || String(e1);
        if (/Permission|NotAllowed|denied/i.test(msg)) {
          statusLine('Camera permission denied. Allow camera access in Safari settings and try again.', 'error');
        } else {
          statusLine('Could not start camera: ' + msg, 'error');
        }
      }
    }
  }

  function renderOccupancyBanner(facts, _bagId) {
    var banner = document.getElementById('wf-occupied-banner');
    var elapsed = document.getElementById('wf-occupied-elapsed');
    if (!banner || !elapsed) return;
    stopOccupancyTimer();
    var startMs = Number(facts && facts.occupancy_started_at_ms);
    if (!Number.isFinite(startMs) || startMs <= 0) {
      banner.classList.add('hidden');
      return;
    }
    function tick() {
      elapsed.textContent = formatElapsedMs(Date.now() - startMs);
    }
    tick();
    banner.classList.remove('hidden');
    occupancyTimerHandle = setInterval(tick, 1000);
  }
  function actionButtons() {
    /* Resume is not in this list so a submit/pause cooldown cannot block the next-day Resume action. */
    return [
      document.getElementById('wf-save-count'),
      document.getElementById('wf-save-blister'),
      document.getElementById('wf-handpack-rest'),
      document.getElementById('wf-save-seal'),
      document.getElementById('wf-pause-count'),
      document.getElementById('wf-taken-delivery'),
      document.getElementById('wf-material-change-open'),
      document.getElementById('wf-material-change-submit'),
      document.getElementById('wf-material-change-cancel'),
    ].filter(Boolean);
  }
  function shownOnlyWhenBagLoaded() {
    return [
      document.getElementById('wf-loaded-bag-header'),
      document.getElementById('wf-count-label'),
      document.getElementById('wf-count-total'),
      document.getElementById('wf-employee-name-label'),
      document.getElementById('wf-employee-name'),
      document.getElementById('wf-save-count'),
      document.getElementById('wf-save-blister'),
      document.getElementById('wf-handpack-rest'),
      document.getElementById('wf-save-seal'),
      document.getElementById('wf-material-change-open'),
      document.getElementById('wf-material-change-panel'),
      document.getElementById('wf-pause-count'),
      document.getElementById('wf-taken-delivery'),
      document.getElementById('wf-resume-bag'),
      document.getElementById('wf-station-hint'),
      document.getElementById('wf-packs-remaining-label'),
      document.getElementById('wf-packs-remaining'),
      document.getElementById('wf-cards-reopened-label'),
      document.getElementById('wf-cards-reopened-help'),
      document.getElementById('wf-cards-reopened'),
      document.getElementById('wf-taken-displays-label'),
      document.getElementById('wf-taken-displays-help'),
      document.getElementById('wf-taken-displays'),
    ].filter(Boolean);
  }
  function renderBagVerification(facts) {
    var wrap = document.getElementById('wf-bag-verification');
    var inner = document.getElementById('wf-bag-verification-body');
    if (!wrap || !inner) return;
    var bv = facts && facts.bag_verification;
    inner.innerHTML = '';
    if (!bv) {
      wrap.classList.add('hidden');
      return;
    }
    var receiptLine = (bv.receipt_number || bv.shipment_label || '').trim();
    var rows = [
      ['Product', bv.product_name],
      ['Tablet', bv.tablet_type_name],
      ['Receipt #', receiptLine],
      ['Box', bv.box_display],
      ['Bag', bv.bag_display],
      ['PO #', bv.po_number],
    ];
    var any = false;
    rows.forEach(function (pair) {
      if (!pair[1]) return;
      any = true;
      var dt = document.createElement('dt');
      dt.className = 'text-slate-500';
      dt.textContent = pair[0];
      inner.appendChild(dt);
      var dd = document.createElement('dd');
      dd.className = 'text-slate-900 font-medium';
      dd.textContent = String(pair[1]);
      inner.appendChild(dd);
    });
    if (!any) {
      wrap.classList.add('hidden');
    } else {
      wrap.classList.remove('hidden');
    }
  }
  function renderLoadedBagHeader(facts) {
    var wrap = document.getElementById('wf-loaded-bag-header');
    var text = document.getElementById('wf-loaded-bag-header-text');
    if (!wrap || !text) return;
    var bv = facts && facts.bag_verification;
    if (!bv) {
      wrap.classList.add('hidden');
      text.textContent = '';
      return;
    }
    var product = String((bv.product_name || '').trim() || 'Bag loaded');
    var boxRaw = String((bv.box_display || '').trim() || '');
    var bagRaw = String((bv.bag_display || '').trim() || '');
    var bx = (boxRaw.match(/(\d+)/) || [])[1] || '';
    var bg = (bagRaw.match(/(\d+)/) || [])[1] || '';
    var boxBag = bx && bg ? (bx + '-' + bg) : (boxRaw || bagRaw || '');
    text.textContent = boxBag ? (product + ' · ' + boxBag) : product;
    wrap.classList.remove('hidden');
  }
  function applyStationFacts(data) {
    if (!data || !data.facts) {
      return;
    }
    if (data.facts.station_claimed !== undefined) {
      stationClaimed = !!data.facts.station_claimed;
    }
    stationNeedsResume = !!data.facts.resume_required;
    occupancyPauseDetails = data.facts.pause_details || occupancyPauseDetails;
    renderBagVerification(data.facts);
    renderLoadedBagHeader(data.facts);
    renderOccupancyBanner(data.facts, data.workflow_bag_id);
  }
  function setBagLoadedUi(loaded) {
    var cardEntry = document.getElementById('wf-card-entry');
    if (!loaded) {
      shownOnlyWhenBagLoaded().forEach(function (el) {
        el.classList.add('hidden');
      });
      if (cardEntry) cardEntry.classList.remove('hidden');
      renderLoadedBagHeader(null);
    }
    if (loaded) {
      if (cardEntry) cardEntry.classList.add('hidden');
      configureStationActions();
    }
  }
  function clearAllActionCooldowns() {
    Object.keys(cooldownTimers).forEach(function (k) {
      clearTimeout(cooldownTimers[k]);
      delete cooldownTimers[k];
    });
    Object.keys(cooldownUntil).forEach(function (k) {
      delete cooldownUntil[k];
    });
  }

  function clearCountField() {
    var el = countInput();
    if (el) el.value = '';
  }
  function clearEmployeeNameField() {
    var el = employeeNameInput();
    if (el) el.value = '';
    try {
      localStorage.removeItem(WF_EMPLOYEE_STORAGE_KEY);
    } catch (_e) {
      /* */
    }
  }
  function clearQaCheckedField() {
    var el = document.getElementById('wf-qa-checked');
    if (el) el.checked = false;
  }

  function assertActionCooldown(actionKey) {
    var until = cooldownUntil[actionKey];
    if (until && Date.now() < until) {
      var sec = Math.ceil((until - Date.now()) / 1000);
      throw new Error('Please wait ' + sec + 's before repeating this action.');
    }
  }

  function applyActionCooldownUi() {
    var now = Date.now();
    var pairs = [
      ['submit', 'wf-save-count'],
      ['handpackRest', 'wf-handpack-rest'],
      ['pause', 'wf-pause-count'],
      ['submitBlister', 'wf-save-blister'],
      ['materialChange', 'wf-material-change-submit'],
      ['submitSeal', 'wf-save-seal'],
      ['taken', 'wf-taken-delivery'],
    ];
    pairs.forEach(function (pair) {
      var key = pair[0];
      var btn = document.getElementById(pair[1]);
      if (!btn) return;
      var until = cooldownUntil[key];
      if (until && now < until) {
        btn.disabled = true;
        btn.classList.add('opacity-50', 'cursor-not-allowed');
        var sec = Math.ceil((until - now) / 1000);
        btn.setAttribute('title', 'Wait ' + sec + 's before repeating this action');
      } else {
        if (until && now >= until) {
          delete cooldownUntil[key];
        }
        btn.removeAttribute('title');
        btn.disabled = false;
        btn.classList.remove('opacity-50', 'cursor-not-allowed');
      }
    });
  }

  function startCooldownAfterSuccess(actionKey) {
    cooldownUntil[actionKey] = Date.now() + SUBMIT_PAUSE_COOLDOWN_MS;
    if (cooldownTimers[actionKey]) {
      clearTimeout(cooldownTimers[actionKey]);
    }
    cooldownTimers[actionKey] = setTimeout(function () {
      delete cooldownTimers[actionKey];
      delete cooldownUntil[actionKey];
      if (hasLoadedBag) {
        setActionsEnabled(true);
        configureStationActions();
      }
    }, SUBMIT_PAUSE_COOLDOWN_MS);
    applyActionCooldownUi();
  }

  function setActionsEnabled(enabled) {
    actionButtons().forEach(function (btn) {
      btn.disabled = !enabled;
      btn.classList.toggle('opacity-50', !enabled);
      btn.classList.toggle('cursor-not-allowed', !enabled);
    });
    if (enabled) {
      applyActionCooldownUi();
    }
  }
  function resetLoadedBagState(showHint) {
    hasLoadedBag = false;
    stationClaimed = false;
    stationNeedsResume = false;
    occupancyGateIntentEndRun = false;
    occupancyGateForcedAction = null;
    packagingUiPhase = 'pick';
    renderBagVerification(null);
    setScanSuccessVisible(false);
    clearAllActionCooldowns();
    setBagLoadedUi(false);
    setActionsEnabled(false);
    applyOccupancyGateUi();
    if (showHint) {
      statusLine('Scan the bag card or enter the token, then press Enter to load.', 'info');
    }
  }
  function ensureLoadedBag() {
    if (!hasLoadedBag) {
      throw new Error('Scan or enter bag card token and load bag first.');
    }
  }
  function productInput() {
    return document.getElementById('product_input');
  }
  function countInput() {
    return document.getElementById('wf-count-total');
  }
  function employeeNameInput() {
    return document.getElementById('wf-employee-name');
  }
  function loadEmployeeNameFromStorage() {
    var el = employeeNameInput();
    if (!el) return;
    try {
      var v = localStorage.getItem(WF_EMPLOYEE_STORAGE_KEY);
      if (v) el.value = v;
    } catch (_e) {
      /* */
    }
  }
  function persistEmployeeName() {
    var el = employeeNameInput();
    if (!el) return;
    try {
      var s = String(el.value || '').trim();
      if (s) localStorage.setItem(WF_EMPLOYEE_STORAGE_KEY, s);
    } catch (_e) {
      /* */
    }
  }
  function requiredEmployeeName() {
    var el = employeeNameInput();
    var s = el && String(el.value || '').trim();
    if (!s) {
      throw new Error('Enter your name (for submissions history).');
    }
    return s;
  }
  function stationKind() {
    const el = document.getElementById('wf-station-kind');
    return ((el && el.value) || window.WF_STATION_KIND || 'sealing').toString().trim().toLowerCase();
  }
  function selectedCountTotal() {
    const raw = countInput() ? String(countInput().value || '').trim() : '';
    if (!raw) throw new Error('Enter a machine count total first.');
    const n = Number(raw);
    if (!Number.isFinite(n) || n < 0 || !Number.isInteger(n)) {
      throw new Error('Machine count must be a whole number 0 or greater.');
    }
    return n;
  }
  function requiredQaChecked() {
    var el = document.getElementById('wf-qa-checked');
    if (el && !el.checked) {
      throw new Error('Confirm the second-person bottle check before submitting.');
    }
    return true;
  }
  function optionalNonNegativeInt(elementId, labelText) {
    var el = document.getElementById(elementId);
    var raw = el ? String(el.value || '').trim() : '';
    if (!raw) {
      return 0;
    }
    var n = Number(raw);
    if (!Number.isFinite(n) || n < 0 || !Number.isInteger(n)) {
      throw new Error(labelText + ' must be a whole number 0 or greater.');
    }
    return n;
  }
  function selectedTakenDisplaysTotal() {
    var el = document.getElementById('wf-taken-displays');
    var raw = el && String(el.value || '').trim();
    if (!raw) {
      throw new Error('Enter how many displays were taken for delivery or order.');
    }
    var n = Number(raw);
    if (!Number.isFinite(n) || n < 1 || !Number.isInteger(n)) {
      throw new Error('Displays taken must be a whole number 1 or greater.');
    }
    return n;
  }
  function selectedPackagingCaseCount() {
    var el = countInput();
    var raw = el ? String(el.value || '').trim() : '';
    if (!raw) return 0;
    var n = Number(raw);
    if (!Number.isFinite(n) || n < 0 || !Number.isInteger(n)) {
      throw new Error('Cases made must be a whole number 0 or greater.');
    }
    return n;
  }
  function selectedMaterialType() {
    var checked = document.querySelector('input[name="wf-material-type"]:checked');
    var value = checked ? String(checked.value || '').trim().toLowerCase() : '';
    if (value !== 'foil' && value !== 'pvc') {
      throw new Error('Select the new material (Foil or PVC).');
    }
    return value;
  }
  function closeMaterialChangePanel() {
    var panel = document.getElementById('wf-material-change-panel');
    if (panel) panel.classList.add('hidden');
  }
  function openMaterialChangePanel() {
    if (stationKind() !== 'blister' && stationKind() !== 'combined') {
      return;
    }
    if (!hasLoadedBag || !stationClaimed || stationNeedsResume) {
      return;
    }
    var panel = document.getElementById('wf-material-change-panel');
    if (!panel) return;
    panel.classList.remove('hidden');
    var selected = document.querySelector('input[name="wf-material-type"]:checked');
    if (!selected) {
      var foil = document.getElementById('wf-material-type-foil');
      if (foil) foil.checked = true;
    }
    statusLine('Select the new material, enter current count total, then save material change.', 'info');
  }
  function hidePackagingStationExtra() {
    [
      'wf-packs-remaining-label',
      'wf-packs-remaining',
      'wf-loose-displays-label',
      'wf-loose-displays',
      'wf-cards-reopened-label',
      'wf-cards-reopened-help',
      'wf-cards-reopened',
      'wf-taken-displays-label',
      'wf-taken-displays-help',
      'wf-taken-displays',
    ].forEach(function (id) {
      var el = document.getElementById(id);
      if (el) el.classList.add('hidden');
    });
    var tb = document.getElementById('wf-taken-delivery');
    if (tb) tb.classList.add('hidden');
  }
  function showPackagingStationExtra() {
    [
      'wf-packs-remaining-label',
      'wf-packs-remaining',
      'wf-loose-displays-label',
      'wf-loose-displays',
      'wf-cards-reopened-label',
      'wf-cards-reopened-help',
      'wf-cards-reopened',
    ].forEach(function (id) {
      var el = document.getElementById(id);
      if (el) el.classList.remove('hidden');
    });
  }
  function showPackagingTakenFields() {
    ['wf-taken-displays-label', 'wf-taken-displays-help', 'wf-taken-displays'].forEach(function (id) {
      var el = document.getElementById(id);
      if (el) el.classList.remove('hidden');
    });
  }
  function clearPackagingSnapshotFields() {
    ['wf-packs-remaining', 'wf-loose-displays', 'wf-cards-reopened', 'wf-taken-displays'].forEach(function (id) {
      var el = document.getElementById(id);
      if (el) el.value = '';
    });
  }
  function setSourceScanUi(scanning) {
    var wrap = document.getElementById('wf-source-reader-wrap');
    var stopBtn = document.getElementById('wf-source-scan-stop');
    var scanBtn = document.getElementById('wf-source-scan');
    if (wrap) wrap.classList.toggle('hidden', !scanning);
    if (stopBtn) stopBtn.classList.toggle('hidden', !scanning);
    if (scanBtn) scanBtn.classList.toggle('hidden', scanning);
  }
  function sourceBagTokens() {
    var el = document.getElementById('wf-source-card-tokens');
    if (!el) return [];
    var seen = {};
    return String(el.value || '')
      .split(/\s+/)
      .map(function (x) {
        return String(x || '').trim();
      })
      .filter(function (x) {
        if (!x || seen[x]) return false;
        seen[x] = true;
        return true;
      });
  }
  function setSourceBagTokens(tokens) {
    var el = document.getElementById('wf-source-card-tokens');
    if (el) el.value = (tokens || []).join('\n');
  }
  function addSourceBagToken(token) {
    var t = String(token || '').trim();
    if (!t) return;
    var tokens = sourceBagTokens();
    if (!tokens.includes(t)) tokens.push(t);
    setSourceBagTokens(tokens);
  }
  function clearSourceBagTokens() {
    setSourceBagTokens([]);
  }
  function configureStationActions() {
    const kind = stationKind();
    const hint = document.getElementById('wf-station-hint');
    const countLabel = document.getElementById('wf-count-label');
    const countTotal = document.getElementById('wf-count-total');
    const saveBtn = document.getElementById('wf-save-count');
    const saveBlisterBtn = document.getElementById('wf-save-blister');
    const handpackBtn = document.getElementById('wf-handpack-rest');
    const saveSealBtn = document.getElementById('wf-save-seal');
    const materialChangeOpenBtn = document.getElementById('wf-material-change-open');
    const materialChangePanel = document.getElementById('wf-material-change-panel');
    const pauseBtn = document.getElementById('wf-pause-count');
    const resumeBtn = document.getElementById('wf-resume-bag');
    const empLabel = document.getElementById('wf-employee-name-label');
    const empInput = document.getElementById('wf-employee-name');
    const qaLabel = document.getElementById('wf-qa-checked-label');
    const sourcePanel = document.getElementById('wf-source-bags-panel');
    const sourceHelp = document.getElementById('wf-source-bags-help');
    const sourceScanBtn = document.getElementById('wf-source-scan');
    const sourceStopBtn = document.getElementById('wf-source-scan-stop');
    const sourceClearBtn = document.getElementById('wf-source-clear');
    const sourceTokensInput = document.getElementById('wf-source-card-tokens');
    const takenBtn = document.getElementById('wf-taken-delivery');
    const takenGateBtn = document.getElementById('wf-gate-taken');
    const takenIntentBtn = document.getElementById('wf-intent-taken');
    function applyPauseTone(btn, enabled) {
      if (!btn) return;
      btn.classList.toggle('!bg-amber-400', !!enabled);
      btn.classList.toggle('!border-amber-300', !!enabled);
      btn.classList.toggle('!text-slate-900', !!enabled);
      btn.classList.toggle('hover:!bg-amber-300', !!enabled);
    }
    function applyEndTone(btn, enabled) {
      if (!btn) return;
      btn.classList.toggle('!bg-red-600', !!enabled);
      btn.classList.toggle('!border-red-500', !!enabled);
      btn.classList.toggle('!text-white', !!enabled);
      btn.classList.toggle('hover:!bg-red-500', !!enabled);
    }
    if (!saveBtn || !pauseBtn || !countTotal) return;
    if (resumeBtn) resumeBtn.classList.add('hidden');
    if (empLabel) empLabel.classList.add('hidden');
    if (empInput) empInput.classList.add('hidden');
    if (qaLabel) qaLabel.classList.add('hidden');
    if (qaLabel) qaLabel.classList.remove('flex');
    if (sourcePanel) sourcePanel.classList.add('hidden');
    if (sourceScanBtn) sourceScanBtn.disabled = false;
    if (sourceStopBtn) sourceStopBtn.disabled = false;
    if (sourceClearBtn) sourceClearBtn.disabled = false;
    if (sourceTokensInput) sourceTokensInput.readOnly = false;
    if (takenBtn) takenBtn.classList.add('hidden');
    if (kind !== 'packaging') {
      if (takenGateBtn) takenGateBtn.classList.add('hidden');
      if (takenIntentBtn) takenIntentBtn.classList.add('hidden');
    }
    hidePackagingStationExtra();
    if (saveBlisterBtn) saveBlisterBtn.classList.add('hidden');
    if (handpackBtn) handpackBtn.classList.add('hidden');
    if (saveSealBtn) saveSealBtn.classList.add('hidden');
    if (materialChangeOpenBtn) materialChangeOpenBtn.classList.add('hidden');
    if (materialChangePanel) materialChangePanel.classList.add('hidden');
    saveBtn.classList.add('hidden');
    pauseBtn.classList.add('hidden');
    countLabel && countLabel.classList.add('hidden');
    countTotal.classList.add('hidden');
    if (!hasLoadedBag) {
      return;
    }
    if (!stationClaimed) return;
    if (stationNeedsResume) {
      if (resumeBtn) {
        resumeBtn.classList.remove('hidden');
        resumeBtn.disabled = false;
        resumeBtn.classList.remove('opacity-50', 'cursor-not-allowed');
      }
      if (hint) {
        hint.classList.remove('hidden');
        hint.textContent =
          'This bag was paused — confirm the card is still loaded, then tap Resume to continue.';
      }
      return;
    }
    countLabel && countLabel.classList.remove('hidden');
    countTotal.classList.remove('hidden');
    if (empLabel) {
      empLabel.classList.remove('hidden');
      empLabel.textContent = 'Your name';
    }
    if (empInput) {
      empInput.classList.remove('hidden');
      empInput.placeholder = 'name / nombre';
    }
    saveBtn.classList.remove('hidden');
    pauseBtn.classList.remove('hidden');
    applyPauseTone(pauseBtn, true);
    applyEndTone(saveBtn, true);
    if (kind === 'blister') {
      saveBtn.textContent = 'Submit blister count';
      pauseBtn.textContent = 'Pause blister bag';
      if (handpackBtn) handpackBtn.classList.toggle('hidden', !isAdminUser);
      if (materialChangeOpenBtn) materialChangeOpenBtn.classList.remove('hidden');
      if (countLabel) countLabel.textContent = 'Blister machine count total';
      if (hint) {
        hint.classList.remove('hidden');
        hint.textContent = occupancyGateIntentEndRun
          ? 'End run: enter the final blister count and tap Submit below. Station opens for the next bag after submit.'
          : 'Blister lane: submit blister count, record material changes (Foil/PVC), use Hand pack the rest if machine stopped mid-bag, or pause with current count.';
      }
      if (occupancyGateIntentEndRun) {
        if (pauseBtn) pauseBtn.classList.add('hidden');
        if (handpackBtn) handpackBtn.classList.add('hidden');
        if (materialChangeOpenBtn) materialChangeOpenBtn.classList.add('hidden');
      }
    } else if (kind === 'sealing') {
      saveBtn.textContent = 'Submit sealing count';
      pauseBtn.textContent = 'Pause sealing bag';
      if (countLabel) countLabel.textContent = 'Sealing machine count total';
      if (hint) {
        hint.classList.remove('hidden');
        hint.textContent = occupancyGateIntentEndRun
          ? 'End run: enter the sealing count and tap Submit below.'
          : 'Sealing lane: submit sealing machine count, or pause with current count.';
      }
      if (occupancyGateIntentEndRun && pauseBtn) pauseBtn.classList.add('hidden');
    } else if (kind === 'bottle_handpack') {
      saveBtn.textContent = 'Submit hand-pack count';
      pauseBtn.textContent = 'Pause hand-pack bag';
      if (countLabel) countLabel.textContent = 'Filled bottle count total';
      if (qaLabel) {
        qaLabel.classList.remove('hidden');
        qaLabel.classList.add('flex');
      }
      if (sourcePanel) sourcePanel.classList.remove('hidden');
      var sourceReady = hasLoadedBag && stationClaimed && !stationNeedsResume;
      if (sourceScanBtn) sourceScanBtn.disabled = !sourceReady;
      if (sourceStopBtn) sourceStopBtn.disabled = !sourceReady;
      if (sourceClearBtn) sourceClearBtn.disabled = !sourceReady;
      if (sourceTokensInput) sourceTokensInput.readOnly = !sourceReady;
      if (sourcePanel) sourcePanel.classList.toggle('opacity-70', !sourceReady);
      if (sourceHelp) {
        sourceHelp.innerHTML = sourceReady
          ? 'Scan each source bag QR one by one, then submit hand-pack count.'
          : 'Load and claim the active bag first, then scan all source bag QRs here.';
      }
      if (hint) {
        hint.classList.remove('hidden');
        hint.textContent = occupancyGateIntentEndRun
          ? 'End run: enter the filled bottle count and tap Submit below.'
          : 'Hand pack: enter filled bottle count after packing and QA check; for variety packs, scan each source bag in "Variety source bag cards", then submit or pause.';
      }
      if (occupancyGateIntentEndRun && pauseBtn) pauseBtn.classList.add('hidden');
    } else if (kind === 'bottle_cap_seal') {
      saveBtn.textContent = 'Submit bottle seal count';
      pauseBtn.textContent = 'Pause bottle seal bag';
      if (countLabel) countLabel.textContent = 'Bottle sealer count total';
      if (hint) {
        hint.classList.remove('hidden');
        hint.textContent = occupancyGateIntentEndRun
          ? 'End run: enter the bottle sealer count and tap Submit below.'
          : 'Bottle seal: submit the bottle sealer counter, or pause with current count.';
      }
      if (occupancyGateIntentEndRun && pauseBtn) pauseBtn.classList.add('hidden');
    } else if (kind === 'bottle_stickering') {
      saveBtn.textContent = 'Submit sticker count';
      pauseBtn.textContent = 'Pause sticker bag';
      if (countLabel) countLabel.textContent = 'Stickering machine count total';
      if (hint) {
        hint.classList.remove('hidden');
        hint.textContent = occupancyGateIntentEndRun
          ? 'End run: enter the stickering count and tap Submit below.'
          : 'Stickering: submit the sticker machine counter, or pause with current count.';
      }
      if (occupancyGateIntentEndRun && pauseBtn) pauseBtn.classList.add('hidden');
    } else if (kind === 'packaging') {
      var intentPan = document.getElementById('wf-packaging-intent');
      hidePackagingStationExtra();
      ['wf-taken-displays-label', 'wf-taken-displays-help', 'wf-taken-displays'].forEach(function (id) {
        var el = document.getElementById(id);
        if (el) el.classList.add('hidden');
      });
      if (takenBtn) takenBtn.classList.add('hidden');
      pauseBtn.textContent = 'Pause packaging bag';
      saveBtn.textContent = 'Submit';
      if (countLabel) countLabel.textContent = 'Cases made';
      if (!hasLoadedBag) {
        if (intentPan) intentPan.classList.add('hidden');
        return;
      }
      if (!stationClaimed) {
        if (intentPan) intentPan.classList.add('hidden');
        if (hint) {
          hint.classList.remove('hidden');
          hint.textContent = 'Loading station state…';
        }
        return;
      }
      if (stationNeedsResume) {
        if (intentPan) intentPan.classList.add('hidden');
        if (hint) {
          hint.classList.remove('hidden');
          hint.textContent =
            'This bag was paused — confirm the card is still loaded, then tap Resume to continue.';
        }
        return;
      }
      if (packagingUiPhase === 'pick') {
        if (intentPan) intentPan.classList.remove('hidden');
        countLabel.classList.add('hidden');
        countTotal.classList.add('hidden');
        if (empLabel) empLabel.classList.add('hidden');
        if (empInput) empInput.classList.add('hidden');
        saveBtn.classList.add('hidden');
        pauseBtn.classList.add('hidden');
        if (takenBtn) takenBtn.classList.add('hidden');
        if (hint) {
          hint.classList.remove('hidden');
          hint.textContent =
            'Pick one step above. You will only see the fields and buttons for that step.';
        }
        return;
      }
      if (intentPan) intentPan.classList.add('hidden');
      if (packagingUiPhase === 'taken') {
        countLabel.classList.add('hidden');
        countTotal.classList.add('hidden');
        showPackagingTakenFields();
        if (empLabel) {
          empLabel.classList.remove('hidden');
          empLabel.textContent = 'Taken by';
        }
        if (empInput) {
          empInput.classList.remove('hidden');
          empInput.placeholder = 'Name';
        }
        saveBtn.classList.add('hidden');
        pauseBtn.classList.add('hidden');
        if (takenBtn) {
          takenBtn.classList.remove('hidden');
          takenBtn.disabled = false;
          takenBtn.classList.remove('opacity-50', 'cursor-not-allowed');
        }
        if (hint) {
          hint.classList.remove('hidden');
          hint.textContent =
            'Enter displays taken from this batch, who took them, then tap Taken for delivery.';
        }
        return;
      }
      countLabel.classList.remove('hidden');
      countTotal.classList.remove('hidden');
      if (empLabel) {
        empLabel.classList.remove('hidden');
        empLabel.textContent = 'Your name';
      }
      if (empInput) {
        empInput.classList.remove('hidden');
        empInput.placeholder = 'name / nombre';
      }
      showPackagingStationExtra();
      if (packagingUiPhase === 'end') {
        occupancyGateIntentEndRun = true;
        saveBtn.classList.remove('hidden');
        pauseBtn.classList.add('hidden');
        if (takenBtn) takenBtn.classList.add('hidden');
        if (hint) {
          hint.classList.remove('hidden');
          hint.textContent =
            'End run: enter cases, displays not in a full case, and remaining loose cards or bottles, then tap Submit to finish this bag.';
        }
      } else if (packagingUiPhase === 'pause') {
        occupancyGateIntentEndRun = false;
        saveBtn.classList.add('hidden');
        pauseBtn.classList.remove('hidden');
        if (takenBtn) takenBtn.classList.add('hidden');
        if (hint) {
          hint.classList.remove('hidden');
          hint.textContent =
            'Pause: enter current cases, displays not in a full case, and remaining loose cards or bottles, then tap Pause packaging bag.';
        }
      } else {
        packagingUiPhase = 'pick';
        if (intentPan) intentPan.classList.remove('hidden');
        countLabel.classList.add('hidden');
        countTotal.classList.add('hidden');
        if (empLabel) empLabel.classList.add('hidden');
        if (empInput) empInput.classList.add('hidden');
        saveBtn.classList.add('hidden');
        pauseBtn.classList.add('hidden');
        if (takenBtn) takenBtn.classList.add('hidden');
        if (hint) {
          hint.classList.remove('hidden');
          hint.textContent =
            'Pick one step above. You will only see the fields and buttons for that step.';
        }
      }
    } else if (kind === 'combined') {
      saveBtn.classList.add('hidden');
      if (saveBlisterBtn) saveBlisterBtn.classList.remove('hidden');
      if (handpackBtn) handpackBtn.classList.toggle('hidden', !isAdminUser);
      if (saveSealBtn) saveSealBtn.classList.remove('hidden');
      pauseBtn.textContent = 'Pause combined bag';
      if (countLabel) countLabel.textContent = 'Machine count total';
      if (hint) {
        hint.classList.remove('hidden');
        hint.textContent = occupancyGateIntentEndRun
          ? 'End run: submit the remaining count for this step (blister or sealing) with the buttons below.'
          : 'Combined lane: submit blister or sealing count, use Hand pack the rest when blister machine fails mid-bag, or pause with current count.';
      }
      if (occupancyGateIntentEndRun) {
        if (pauseBtn) pauseBtn.classList.add('hidden');
        if (handpackBtn) handpackBtn.classList.add('hidden');
      }
    } else {
      if (countLabel) countLabel.textContent = 'Machine count total';
      if (hint) {
        hint.classList.remove('hidden');
        hint.textContent = 'Submit machine count for this station, or pause with current count.';
      }
    }
    if (kind !== 'packaging') {
      var forced = occupancyGateForcedAction;
      if (forced === 'pause') {
        saveBtn.classList.add('hidden');
        if (saveBlisterBtn) saveBlisterBtn.classList.add('hidden');
        if (saveSealBtn) saveSealBtn.classList.add('hidden');
        if (handpackBtn) handpackBtn.classList.add('hidden');
        if (materialChangeOpenBtn) materialChangeOpenBtn.classList.add('hidden');
        pauseBtn.classList.remove('hidden');
        applyPauseTone(pauseBtn, true);
      } else if (forced === 'end') {
        pauseBtn.classList.add('hidden');
        if (saveBlisterBtn) saveBlisterBtn.classList.add('hidden');
        if (saveSealBtn) saveSealBtn.classList.add('hidden');
        if (handpackBtn) handpackBtn.classList.add('hidden');
        if (materialChangeOpenBtn) materialChangeOpenBtn.classList.add('hidden');
        saveBtn.classList.remove('hidden');
        applyEndTone(saveBtn, true);
      } else if (forced === 'material') {
        saveBtn.classList.add('hidden');
        pauseBtn.classList.add('hidden');
        if (saveBlisterBtn) saveBlisterBtn.classList.add('hidden');
        if (saveSealBtn) saveSealBtn.classList.add('hidden');
        if (handpackBtn) handpackBtn.classList.add('hidden');
        if (materialChangeOpenBtn) materialChangeOpenBtn.classList.add('hidden');
        if (materialChangePanel) materialChangePanel.classList.remove('hidden');
      } else if (forced === 'operator') {
        pauseBtn.classList.add('hidden');
        if (saveBlisterBtn) saveBlisterBtn.classList.add('hidden');
        if (saveSealBtn) saveSealBtn.classList.add('hidden');
        if (handpackBtn) handpackBtn.classList.add('hidden');
        if (materialChangeOpenBtn) materialChangeOpenBtn.classList.add('hidden');
        saveBtn.classList.remove('hidden');
        saveBtn.textContent = 'Operator change';
      }
    }
  }
  function stationReady() {
    const t = document.getElementById('wf-station-token');
    const v = t && t.value ? String(t.value).trim() : '';
    return v.length > 0;
  }
  function setScanUi(scanning) {
    const wrap = document.getElementById('wf-productqr-reader-wrap');
    const stopBtn = document.getElementById('wf-scan-stop');
    const scanBtn = document.getElementById('wf-scan-product');
    if (wrap) wrap.classList.toggle('hidden', !scanning);
    if (stopBtn) stopBtn.classList.toggle('hidden', !scanning);
    if (scanBtn) scanBtn.classList.toggle('hidden', scanning);
  }
  async function stopProductQrScanner() {
    productScanDone = false;
    if (html5QrCode) {
      try {
        await html5QrCode.stop();
      } catch (_e) {
        /* already stopped */
      }
      try {
        await html5QrCode.clear();
      } catch (_e) {
        /* */
      }
      html5QrCode = null;
    }
    setScanUi(false);
  }
  async function startProductQrScan() {
    if (!stationReady()) {
      statusLine('Error: open this page from your station QR first. Station token is missing.', 'error');
      return;
    }
    if (typeof Html5Qrcode === 'undefined') {
      statusLine('Scanner failed to load. Check your connection and refresh the page.', 'error');
      return;
    }
    await stopProductQrScanner();
    productScanDone = false;
    const readerId = 'wf-productqr-reader';
    const el = document.getElementById(readerId);
    if (!el) return;
    html5QrCode = new Html5Qrcode(readerId);
    setScanUi(true);
    statusLine('Point the camera at the product/bag QR code.', 'info');
    const config = {
      fps: 10,
      qrbox: { width: 250, height: 250 },
    };
    function onScanSuccess(decodedText) {
      if (productScanDone) return;
      const text = String(decodedText || '').trim();
      if (!text) return;
      productScanDone = true;
      setTimeout(function () {
        (async function () {
          try {
            await stopProductQrScanner();
            const inp = productInput();
            if (inp) inp.value = text;
            try {
              if (navigator.vibrate) navigator.vibrate(15);
            } catch (_v) {
              /* */
            }
            syncOccupancyGateFlags();
            if (stationOccupancyGate) {
              statusLine('This station has a bag in progress. Use Pause or End run first.', 'error');
              if (inp) inp.value = '';
              return;
            }
            statusLine('Product QR captured — loading bag…', 'info');
            await refresh();
          } catch (err) {
            statusLine(String(err), 'error');
          }
        })();
      }, 0);
    }
    function onScanFailure() {
      /* per-frame noise; ignore */
    }
    try {
      await html5QrCode.start({ facingMode: 'environment' }, config, onScanSuccess, onScanFailure);
    } catch (e1) {
      try {
        await html5QrCode.stop();
      } catch (_s) {
        /* */
      }
      try {
        await html5QrCode.clear();
      } catch (_c) {
        /* */
      }
      html5QrCode = null;
      try {
        const devices = await Html5Qrcode.getCameras();
        if (!devices || devices.length === 0) {
          throw e1;
        }
        const back =
          devices.find(function (d) {
            return /back|rear|environment|wide/i.test(d.label || '');
          }) || devices[0];
        html5QrCode = new Html5Qrcode(readerId);
        await html5QrCode.start(back.id, config, onScanSuccess, onScanFailure);
      } catch (e2) {
        await stopProductQrScanner();
        const msg = (e1 && e1.message) || String(e1);
        if (/Permission|NotAllowed|denied/i.test(msg)) {
          statusLine('Camera permission denied. Allow camera access in Safari settings and try again.', 'error');
        } else {
          statusLine('Could not start camera: ' + msg, 'error');
        }
      }
    }
  }
  async function stopSourceQrScanner() {
    sourceScanDone = false;
    if (html5QrCodeSource) {
      try {
        await html5QrCodeSource.stop();
      } catch (_e) {
        /* already stopped */
      }
      try {
        await html5QrCodeSource.clear();
      } catch (_e2) {
        /* */
      }
      html5QrCodeSource = null;
    }
    setSourceScanUi(false);
  }
  async function startSourceQrScan() {
    if (typeof Html5Qrcode === 'undefined') {
      statusLine('Scanner failed to load. Check your connection and refresh the page.', 'error');
      return;
    }
    await stopSourceQrScanner();
    sourceScanDone = false;
    var readerId = 'wf-source-qr-reader';
    var el = document.getElementById(readerId);
    if (!el) return;
    html5QrCodeSource = new Html5Qrcode(readerId);
    setSourceScanUi(true);
    statusLine('Point the camera at a variety source bag QR code.', 'info');
    var config = { fps: 10, qrbox: { width: 250, height: 250 } };
    function onScanSuccess(decodedText) {
      if (sourceScanDone) return;
      var text = String(decodedText || '').trim();
      if (!text) return;
      sourceScanDone = true;
      setTimeout(function () {
        (async function () {
          try {
            addSourceBagToken(text);
            try {
              if (navigator.vibrate) navigator.vibrate(15);
            } catch (_v) {
              /* */
            }
            statusLine('Source bag QR captured. Scan another source bag if needed.', 'success');
            await stopSourceQrScanner();
          } catch (err) {
            statusLine(String(err), 'error');
          }
        })();
      }, 0);
    }
    function onScanFailure() {
      /* per-frame noise; ignore */
    }
    try {
      await html5QrCodeSource.start({ facingMode: 'environment' }, config, onScanSuccess, onScanFailure);
    } catch (e1) {
      try {
        await html5QrCodeSource.stop();
      } catch (_s) {
        /* */
      }
      try {
        await html5QrCodeSource.clear();
      } catch (_c) {
        /* */
      }
      html5QrCodeSource = null;
      try {
        var devices = await Html5Qrcode.getCameras();
        if (!devices || devices.length === 0) throw e1;
        var back =
          devices.find(function (d) {
            return /back|rear|environment|wide/i.test(d.label || '');
          }) || devices[0];
        html5QrCodeSource = new Html5Qrcode(readerId);
        await html5QrCodeSource.start(back.id, config, onScanSuccess, onScanFailure);
      } catch (e2) {
        await stopSourceQrScanner();
        var msg = (e1 && e1.message) || String(e1);
        statusLine('Could not start camera: ' + msg, 'error');
      }
    }
  }
  async function postJson(path, body) {
    const r = await fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) {
      const code = data.code || 'error';
      const reason = (data.details && data.details.reason) || '';
      if (code === 'WORKFLOW_VALIDATION') {
        if (reason === 'wrong_station_type') {
          throw new Error('This scan step is too early or not allowed for this station.');
        }
        if (reason === 'claim_required') {
          throw new Error('Claim this bag at the station first, then submit counts.');
        }
        if (reason === 'resume_required') {
          throw new Error('Resume this bag before submitting more counts.');
        }
        var msg = String(data.message || '').toLowerCase();
        if (msg.includes('cannot finalize')) {
          var finalReasons = (((data.details || {}).reasons) || []).map(String);
          if (finalReasons.includes('missing_blister')) throw new Error('Bag scanned too early. Blister step is still required.');
          if (finalReasons.includes('missing_sealing')) throw new Error('Bag scanned too early. Sealing step is still required.');
          if (finalReasons.includes('missing_packaging')) throw new Error('Bag scanned too early. Packaging counts are still required.');
        }
      }
      if (code === 'WORKFLOW_PRODUCT_MAPPING') {
        if (reason === 'ambiguous_product_mapping') {
          renderProductMappingPrompt(data.details || {});
        }
        if (reason === 'no_product_mapping') {
          throw new Error('No product is configured for this tablet on this station type. Update Product Configuration, then scan again.');
        }
      }
      throw new Error((data.message || (code + ': ' + r.status)).toString());
    }
    return data;
  }
  async function refresh() {
    syncOccupancyGateFlags();
    const stationToken = document.getElementById('wf-station-token').value;
    const inp = productInput();
    const cardToken = inp ? inp.value.trim() : '';
    if (!cardToken) {
      statusLine('Enter card token', 'error');
      return;
    }
    if (
      stationHasOccupantApi &&
      expectedOccupantCardToken &&
      cardToken !== expectedOccupantCardToken
    ) {
      statusLine('This QR code does not match the current bag at this station.', 'error');
      return;
    }
    var bypassGateForOccupantLoad =
      stationHasOccupantApi &&
      expectedOccupantCardToken &&
      cardToken === expectedOccupantCardToken;
    if (stationOccupancyGate && !bypassGateForOccupantLoad) {
      statusLine(
        'This station has a bag in progress. Use Pause or End run and verify the card first.',
        'error'
      );
      return;
    }
    const data = await postJson('/workflow/floor/api/bag', {
      station_token: stationToken,
      card_token: cardToken,
      device_id: deviceId(),
      page_session_id: pageSessionId(),
    });
    hasLoadedBag = true;
    clearProductMappingPrompt();
    applyStationFacts(data);
    var facts = data.facts || {};
    var shouldAutoClaim =
      (!facts.resume_required && !!facts.claim_required) ||
      (!facts.resume_required && !stationHasOccupantApi && !stationClaimed);
    if (shouldAutoClaim) {
      setBagLoadedUi(true);
      setActionsEnabled(true);
      clearFeedback();
      await claimBag();
      if (stationKind() === 'packaging') {
        packagingUiPhase = 'pick';
      }
      applyOccupancyGateUi();
      return;
    }
    setBagLoadedUi(true);
    setActionsEnabled(true);
    configureStationActions();
    applyOccupancyGateUi();
    if (!stationClaimed) {
      setScanSuccessVisible(false);
      statusLine('Bag loaded, but station claim state is not ready yet. Try scanning again.', 'info');
    } else {
      setScanSuccessVisible(false);
      clearFeedback();
      statusLine('Bag loaded — enter counts below.', 'info');
      refreshStationOccupancy().catch(function () {});
    }
  }
  async function refreshStationOccupancy() {
    const stationToken = document.getElementById('wf-station-token').value;
    if (!stationToken) return;
    const data = await postJson('/workflow/floor/api/station', {
      station_token: stationToken,
      device_id: deviceId(),
      page_session_id: pageSessionId(),
    });
    const occ = data && data.occupancy;
    if (!occ || occ.status === 'idle') {
      stationHasOccupantApi = false;
      occupancyIsPaused = false;
      occupancyPauseDetails = null;
      expectedOccupantCardToken = null;
      occupancyVerifyOpen = false;
      occupancyGateIntentEndRun = false;
      stopOccupancyTimer();
      hidePausedStationUi();
      lastOccStartMs = 0;
      pausedScreenStartMs = 0;
      renderOccupancyBanner(null, null);
      renderBagVerification(null);
      applyOccupancyGateUi();
      return;
    }
    stationHasOccupantApi = true;
    occupancyIsPaused = occ.status === 'paused';
    expectedOccupantCardToken = occ.card_token ? String(occ.card_token).trim() : null;
    lastOccStartMs = Number(occ.occupancy_started_at_ms) || 0;
    pausedScreenStartMs = Number(occ.paused_at_ms) || 0;
    if (occ.facts) {
      if (occ.facts.station_claimed !== undefined) {
        stationClaimed = !!occ.facts.station_claimed;
      }
      stationNeedsResume = !!occ.facts.resume_required;
      occupancyPauseDetails = occ.facts.pause_details || null;
      renderBagVerification(occ.facts);
      if (occ.status === 'paused') {
        stopOccupancyTimer();
        var ob0 = document.getElementById('wf-occupied-banner');
        if (ob0) ob0.classList.add('hidden');
      } else {
        renderOccupancyBanner(
          Object.assign({}, occ.facts, {
            occupancy_started_at_ms: occ.occupancy_started_at_ms,
            occupying_card_token: occ.card_token,
          }),
          occ.workflow_bag_id
        );
      }
    }
    setScanSuccessVisible(false);
    applyOccupancyGateUi();
    if (
      occ.status === 'paused' &&
      stationNeedsResume &&
      !occupancyVerifyOpen
    ) {
      showPausedStationUi();
    } else if (occ.status !== 'paused') {
      hidePausedStationUi();
    }
  }
  async function claimBag() {
    ensureLoadedBag();
    const kind = stationKind();
    const data = await emitEvent('BAG_CLAIMED', {
      station_id: window.WF_STATION_ID || 0,
      station_kind: kind,
      note: 'claimed_on_station',
      metadata: pendingProductMapProductId ? { selected_product_id: pendingProductMapProductId } : {},
    });
    clearProductMappingPrompt();
    applyStationFacts(data);
    configureStationActions();
    setActionsEnabled(true);
    setScanSuccessVisible(false);
    clearFeedback();
    if (stationKind() === 'packaging') {
      packagingUiPhase = 'pick';
    }
    configureStationActions();
    showFullscreenSuccess('Bag claimed at this station.', undefined, function () {
      refreshStationOccupancy().catch(function () {});
    });
  }
  async function saveCountAndContinue() {
    ensureLoadedBag();
    if (occupancyGateForcedAction === 'operator') {
      await saveOperatorChangeWithCount();
      return;
    }
    assertActionCooldown('submit');
    const kind = stationKind();
    if (kind === 'packaging') {
      await submitPackagingAndFinalize();
      return;
    }
    const countTotal = selectedCountTotal();
    if (kind === 'blister' || kind === 'combined') {
      await emitEvent('BLISTER_COMPLETE', {
        count_total: countTotal,
        employee_name: requiredEmployeeName(),
      });
      occupancyGateIntentEndRun = false;
      clearCountField();
      clearEmployeeNameField();
      configureStationActions();
      startCooldownAfterSuccess('submit');
      statusLine('Blister count submitted.' + MSG_SCAN_NEXT_CARD, 'success');
      fullscreenSubmitOk('Blister count submitted.');
      return;
    }
    if (kind === 'sealing') {
      await emitEvent('SEALING_COMPLETE', {
        station_id: window.WF_STATION_ID || 1,
        count_total: countTotal,
        employee_name: requiredEmployeeName(),
      });
      occupancyGateIntentEndRun = false;
      clearCountField();
      clearEmployeeNameField();
      configureStationActions();
      startCooldownAfterSuccess('submit');
      statusLine('Sealing count submitted.' + MSG_SCAN_NEXT_CARD, 'success');
      fullscreenSubmitOk('Sealing count submitted.');
      return;
    }
    if (kind === 'bottle_handpack') {
      requiredQaChecked();
      await emitEvent('BOTTLE_HANDPACK_COMPLETE', {
        count_total: countTotal,
        employee_name: requiredEmployeeName(),
        qa_checked: true,
        source_card_tokens: sourceBagTokens(),
      });
      occupancyGateIntentEndRun = false;
      clearCountField();
      clearEmployeeNameField();
      clearQaCheckedField();
      clearSourceBagTokens();
      configureStationActions();
      startCooldownAfterSuccess('submit');
      statusLine('Bottle hand-pack count submitted.' + MSG_SCAN_NEXT_CARD, 'success');
      fullscreenSubmitOk('Bottle hand-pack saved.');
      return;
    }
    if (kind === 'bottle_cap_seal') {
      await emitEvent('BOTTLE_CAP_SEAL_COMPLETE', {
        station_id: window.WF_STATION_ID || 1,
        count_total: countTotal,
        employee_name: requiredEmployeeName(),
      });
      occupancyGateIntentEndRun = false;
      clearCountField();
      clearEmployeeNameField();
      configureStationActions();
      startCooldownAfterSuccess('submit');
      statusLine('Bottle seal count submitted.' + MSG_SCAN_NEXT_CARD, 'success');
      fullscreenSubmitOk('Bottle seal count submitted.');
      return;
    }
    if (kind === 'bottle_stickering') {
      await emitEvent('BOTTLE_STICKER_COMPLETE', {
        station_id: window.WF_STATION_ID || 1,
        count_total: countTotal,
        employee_name: requiredEmployeeName(),
      });
      occupancyGateIntentEndRun = false;
      clearCountField();
      clearEmployeeNameField();
      configureStationActions();
      startCooldownAfterSuccess('submit');
      statusLine('Bottle sticker count submitted.' + MSG_SCAN_NEXT_CARD, 'success');
      fullscreenSubmitOk('Bottle sticker count submitted.');
      return;
    }
    throw new Error('Unsupported station kind: ' + kind);
  }
  async function saveBlisterCountOnly() {
    ensureLoadedBag();
    assertActionCooldown('submitBlister');
    const countTotal = selectedCountTotal();
    await emitEvent('BLISTER_COMPLETE', {
      count_total: countTotal,
      employee_name: requiredEmployeeName(),
    });
    occupancyGateIntentEndRun = false;
    clearCountField();
    clearEmployeeNameField();
    configureStationActions();
    startCooldownAfterSuccess('submitBlister');
    statusLine('Blister count submitted.' + MSG_SCAN_NEXT_CARD, 'success');
    fullscreenSubmitOk('Blister count submitted.');
  }
  async function saveSealingCountOnly() {
    ensureLoadedBag();
    assertActionCooldown('submitSeal');
    const countTotal = selectedCountTotal();
    await emitEvent('SEALING_COMPLETE', {
      station_id: window.WF_STATION_ID || 1,
      count_total: countTotal,
      employee_name: requiredEmployeeName(),
    });
    occupancyGateIntentEndRun = false;
    clearCountField();
    clearEmployeeNameField();
    configureStationActions();
    startCooldownAfterSuccess('submitSeal');
    statusLine('Sealing count submitted.' + MSG_SCAN_NEXT_CARD, 'success');
    fullscreenSubmitOk('Sealing count submitted.');
  }
  async function handPackRestAfterBlister() {
    ensureLoadedBag();
    const kind = stationKind();
    if (kind !== 'blister' && kind !== 'combined') {
      throw new Error('Hand pack rest is only available for blister lanes.');
    }
    if (!isAdminUser) {
      throw new Error('Hand pack the rest is restricted to admin users.');
    }
    assertActionCooldown('handpackRest');
    const countTotal = selectedCountTotal();
    await emitEvent('BLISTER_COMPLETE', {
      count_total: countTotal,
      employee_name: requiredEmployeeName(),
      metadata: {
        handpack_rest: true,
        reason: 'machine_partial_handpack_rest',
      },
    });
    occupancyGateIntentEndRun = false;
    clearCountField();
    clearEmployeeNameField();
    configureStationActions();
    startCooldownAfterSuccess('handpackRest');
    statusLine(
      'Blister count submitted and flagged for hand-packed remainder.' + MSG_SCAN_NEXT_CARD,
      'success'
    );
    fullscreenSubmitOk('Hand-pack remainder saved.');
  }
  async function pauseWithCount() {
    ensureLoadedBag();
    occupancyGateIntentEndRun = false;
    assertActionCooldown('pause');
    const kind = stationKind();
    if (kind === 'packaging') {
      await emitEvent('PACKAGING_SNAPSHOT', {
        case_count: selectedPackagingCaseCount(),
        display_count: optionalNonNegativeInt('wf-loose-displays', 'Displays not in a full case'),
        packs_remaining: optionalNonNegativeInt('wf-packs-remaining', 'Loose cards / bottles remaining'),
        cards_reopened: optionalNonNegativeInt('wf-cards-reopened', 'Cards re-opened'),
        reason: 'paused_end_of_day',
        employee_name: requiredEmployeeName(),
      });
      clearCountField();
      clearEmployeeNameField();
      clearPackagingSnapshotFields();
      packagingUiPhase = 'pick';
      configureStationActions();
      startCooldownAfterSuccess('pause');
      statusLine(MSG_PAUSE_RESUME_TOMORROW, 'success');
      showFullscreenSuccess('Pause saved. Station is paused.', undefined, function () {
        refreshStationOccupancy().catch(function () {});
      });
      return;
    }
    const countTotal = selectedCountTotal();
    if (kind === 'blister' || kind === 'combined') {
      await emitEvent('BLISTER_COMPLETE', {
        count_total: countTotal,
        employee_name: requiredEmployeeName(),
        metadata: { paused: true, reason: 'end_of_day' },
      });
      clearCountField();
      clearEmployeeNameField();
      configureStationActions();
      startCooldownAfterSuccess('pause');
      statusLine(MSG_PAUSE_RESUME_TOMORROW, 'success');
      showFullscreenSuccess('Pause saved. Station is paused.', undefined, function () {
        refreshStationOccupancy().catch(function () {});
      });
      return;
    }
    if (kind === 'sealing') {
      await emitEvent('SEALING_COMPLETE', {
        station_id: window.WF_STATION_ID || 1,
        count_total: countTotal,
        employee_name: requiredEmployeeName(),
        metadata: { paused: true, reason: 'end_of_day' },
      });
      clearCountField();
      clearEmployeeNameField();
      configureStationActions();
      startCooldownAfterSuccess('pause');
      statusLine(MSG_PAUSE_RESUME_TOMORROW, 'success');
      showFullscreenSuccess('Pause saved. Station is paused.', undefined, function () {
        refreshStationOccupancy().catch(function () {});
      });
      return;
    }
    if (kind === 'bottle_handpack' || kind === 'bottle_cap_seal' || kind === 'bottle_stickering') {
      var bottleEventType =
        kind === 'bottle_handpack'
          ? 'BOTTLE_HANDPACK_COMPLETE'
          : kind === 'bottle_cap_seal'
            ? 'BOTTLE_CAP_SEAL_COMPLETE'
            : 'BOTTLE_STICKER_COMPLETE';
      var bottlePayload = {
        count_total: countTotal,
        employee_name: requiredEmployeeName(),
        metadata: { paused: true, reason: 'end_of_day' },
      };
      if (kind !== 'bottle_handpack') bottlePayload.station_id = window.WF_STATION_ID || 1;
      if (kind === 'bottle_handpack') {
        requiredQaChecked();
        bottlePayload.qa_checked = true;
        bottlePayload.source_card_tokens = sourceBagTokens();
      }
      await emitEvent(bottleEventType, bottlePayload);
      clearCountField();
      clearEmployeeNameField();
      clearQaCheckedField();
      clearSourceBagTokens();
      configureStationActions();
      startCooldownAfterSuccess('pause');
      statusLine(MSG_PAUSE_RESUME_TOMORROW, 'success');
      showFullscreenSuccess('Pause saved. Station is paused.', undefined, function () {
        refreshStationOccupancy().catch(function () {});
      });
      return;
    }
    throw new Error('Unsupported station kind: ' + kind);
  }
  async function saveMaterialChangeWithCount() {
    ensureLoadedBag();
    const kind = stationKind();
    if (kind !== 'blister' && kind !== 'combined') {
      throw new Error('Material change is only available for blister lanes.');
    }
    if (stationNeedsResume) {
      throw new Error('Resume this bag before recording a material change.');
    }
    assertActionCooldown('materialChange');
    const countTotal = selectedCountTotal();
    const materialType = selectedMaterialType();
    await emitEvent('BLISTER_COMPLETE', {
      count_total: countTotal,
      employee_name: requiredEmployeeName(),
      reason: 'material_change',
      pause_reason: 'material_change',
      metadata: {
        paused: true,
        material_change: true,
        reason: 'material_change',
        material_type: materialType,
      },
    });
    occupancyGateIntentEndRun = false;
    clearCountField();
    configureStationActions();
    closeMaterialChangePanel();
    startCooldownAfterSuccess('materialChange');
    statusLine(
      'Material change saved (' + materialType.toUpperCase() + '). Station is paused until Resume.',
      'success'
    );
    showFullscreenSuccess('Material change saved.', undefined, function () {
      refreshStationOccupancy().catch(function () {});
    });
  }
  async function saveOperatorChangeWithCount() {
    ensureLoadedBag();
    const kind = stationKind();
    if (kind !== 'blister') {
      throw new Error('Operator change is only available on blister stations.');
    }
    const countTotal = selectedCountTotal();
    const payload = {
      count_total: countTotal,
      employee_name: requiredEmployeeName(),
      metadata: {
        operator_change: true,
        reason: 'operator_change',
      },
    };
    payload.station_id = window.WF_STATION_ID || 1;
    await emitEvent('OPERATOR_CHANGE', payload);
    clearCountField();
    clearEmployeeNameField();
    occupancyGateForcedAction = null;
    occupancyGateIntentEndRun = false;
    configureStationActions();
    statusLine('Operator change saved with current count.', 'success');
    fullscreenSubmitOk('Operator change saved.');
  }
  async function submitPackagingAndFinalize() {
    ensureLoadedBag();
    assertActionCooldown('submit');
    await emitEvent('PACKAGING_SNAPSHOT', {
      case_count: selectedPackagingCaseCount(),
      display_count: optionalNonNegativeInt('wf-loose-displays', 'Displays not in a full case'),
      packs_remaining: optionalNonNegativeInt('wf-packs-remaining', 'Loose cards / bottles remaining'),
      cards_reopened: optionalNonNegativeInt('wf-cards-reopened', 'Cards re-opened'),
      reason: 'final_submit',
      employee_name: requiredEmployeeName(),
    });
    const stationToken = document.getElementById('wf-station-token').value;
    const cardToken = productInput() ? String(productInput().value || '').trim() : '';
    await postJson('/workflow/floor/api/finalize', {
      station_token: stationToken,
      card_token: cardToken,
      device_id: deviceId(),
      page_session_id: pageSessionId(),
    });
    clearCountField();
    clearEmployeeNameField();
    clearPackagingSnapshotFields();
    var pinp = productInput();
    if (pinp) pinp.value = '';
    resetLoadedBagState(false);
    configureStationActions();
    refreshStationOccupancy().catch(function () {});
    startCooldownAfterSuccess('submit');
    statusLine('Packaging counts saved and bag finalized.' + MSG_SCAN_NEXT_CARD, 'success');
    fullscreenSubmitOk('Packaging saved — bag finalized.');
  }
  async function takenForDelivery() {
    ensureLoadedBag();
    if (stationKind() !== 'packaging') {
      throw new Error('Taken for delivery is only for packaging stations.');
    }
    assertActionCooldown('taken');
    await emitEvent('PACKAGING_TAKEN_FOR_ORDER', {
      displays_taken: selectedTakenDisplaysTotal(),
      employee_name: requiredEmployeeName(),
      note: 'taken_for_delivery',
    });
    var td = document.getElementById('wf-taken-displays');
    if (td) td.value = '';
    clearEmployeeNameField();
    packagingUiPhase = 'pick';
    configureStationActions();
    setActionsEnabled(true);
    startCooldownAfterSuccess('taken');
    statusLine('Taken-for-order displays recorded.' + MSG_SCAN_NEXT_CARD, 'success');
    fullscreenSubmitOk('Taken-for-order recorded.');
  }
  async function emitEvent(eventType, payload) {
    const stationToken = document.getElementById('wf-station-token').value;
    const inp = productInput();
    const cardToken = inp ? inp.value.trim() : '';
    const data = await postJson('/workflow/floor/api/event', {
      station_token: stationToken,
      card_token: cardToken,
      device_id: deviceId(),
      page_session_id: pageSessionId(),
      event_type: eventType,
      payload: payload || {},
    });
    applyStationFacts(data);
    refreshStationOccupancy().catch(function () {});
    return data;
  }
  async function resumeBag() {
    ensureLoadedBag();
    const kind = stationKind();
    const data = await emitEvent('STATION_RESUMED', {
      station_id: window.WF_STATION_ID || 0,
      station_kind: kind,
      note: 'resumed_after_pause',
    });
    if (data.idempotent_duplicate) {
      statusLine('Station already resumed.', 'success');
    } else {
      statusLine('Station resumed — enter counts for this run.', 'success');
    }
    if (stationKind() === 'packaging') {
      packagingUiPhase = 'pick';
    }
    configureStationActions();
    setActionsEnabled(true);
  }
  document.addEventListener('DOMContentLoaded', () => {
    loadEmployeeNameFromStorage();
    resetLoadedBagState(false);
    configureStationActions();
    applyOccupancyGateUi();
    refreshStationOccupancy()
      .then(function () {
        if (stationOccupancyGate && productInput()) {
          productInput().value = '';
        }
        applyOccupancyGateUi();
      })
      .catch(function (e) {
        statusLine(String(e), 'error');
      });
    const inp = productInput();
    if (inp) {
      inp.addEventListener('input', () => {
        resetLoadedBagState(false);
        refreshStationOccupancy().catch(function () {});
      });
      inp.addEventListener('keydown', function (ev) {
        if (ev.key === 'Enter') {
          ev.preventDefault();
          refresh().catch(function (e) {
            statusLine(String(e), 'error');
          });
        }
      });
    }
    const emp = employeeNameInput();
    if (emp) emp.addEventListener('blur', () => persistEmployeeName());
    const save = document.getElementById('wf-save-count');
    if (save) save.addEventListener('click', () => saveCountAndContinue().catch((e) => statusLine(String(e), 'error')));
    const saveBlister = document.getElementById('wf-save-blister');
    if (saveBlister) saveBlister.addEventListener('click', () => saveBlisterCountOnly().catch((e) => statusLine(String(e), 'error')));
    const handpack = document.getElementById('wf-handpack-rest');
    if (handpack) handpack.addEventListener('click', () => handPackRestAfterBlister().catch((e) => statusLine(String(e), 'error')));
    const saveSeal = document.getElementById('wf-save-seal');
    if (saveSeal) saveSeal.addEventListener('click', () => saveSealingCountOnly().catch((e) => statusLine(String(e), 'error')));
    const pause = document.getElementById('wf-pause-count');
    if (pause) pause.addEventListener('click', () => pauseWithCount().catch((e) => statusLine(String(e), 'error')));
    const matOpen = document.getElementById('wf-material-change-open');
    if (matOpen) matOpen.addEventListener('click', () => openMaterialChangePanel());
    const matSubmit = document.getElementById('wf-material-change-submit');
    if (matSubmit) matSubmit.addEventListener('click', () => saveMaterialChangeWithCount().catch((e) => statusLine(String(e), 'error')));
    const matCancel = document.getElementById('wf-material-change-cancel');
    if (matCancel) matCancel.addEventListener('click', () => closeMaterialChangePanel());
    const taken = document.getElementById('wf-taken-delivery');
    if (taken) taken.addEventListener('click', () => takenForDelivery().catch((e) => statusLine(String(e), 'error')));
    const resume = document.getElementById('wf-resume-bag');
    if (resume) resume.addEventListener('click', () => resumeBag().catch((e) => statusLine(String(e), 'error')));
    const sp = document.getElementById('wf-scan-product');
    if (sp) sp.addEventListener('click', () => startProductQrScan().catch((e) => statusLine(String(e), 'error')));
    const st = document.getElementById('wf-scan-stop');
    if (st) st.addEventListener('click', () => stopProductQrScanner().catch((e) => statusLine(String(e), 'error')));
    const ss = document.getElementById('wf-source-scan');
    if (ss) ss.addEventListener('click', () => startSourceQrScan().catch((e) => statusLine(String(e), 'error')));
    const sst = document.getElementById('wf-source-scan-stop');
    if (sst) sst.addEventListener('click', () => stopSourceQrScanner().catch((e) => statusLine(String(e), 'error')));
    const sc = document.getElementById('wf-source-clear');
    if (sc) sc.addEventListener('click', () => clearSourceBagTokens());
    const gp = document.getElementById('wf-gate-pause');
    if (gp) gp.addEventListener('click', () => openOccupancyVerify('pause'));
    const ge = document.getElementById('wf-gate-end');
    if (ge) ge.addEventListener('click', () => openOccupancyVerify('end'));
    const go = document.getElementById('wf-gate-operator');
    if (go) go.addEventListener('click', () => openOccupancyVerify('operator'));
    const gm = document.getElementById('wf-gate-material');
    if (gm) gm.addEventListener('click', () => openOccupancyVerify('material'));
    const gt = document.getElementById('wf-gate-taken');
    if (gt) gt.addEventListener('click', () => openOccupancyVerify('taken'));
    const ie = document.getElementById('wf-intent-end');
    if (ie) {
      ie.addEventListener('click', function () {
        packagingUiPhase = 'end';
        occupancyGateIntentEndRun = true;
        configureStationActions();
        applyOccupancyGateUi();
      });
    }
    const ip = document.getElementById('wf-intent-pause');
    if (ip) {
      ip.addEventListener('click', function () {
        packagingUiPhase = 'pause';
        occupancyGateIntentEndRun = false;
        configureStationActions();
        applyOccupancyGateUi();
      });
    }
    const it = document.getElementById('wf-intent-taken');
    if (it) {
      it.addEventListener('click', function () {
        packagingUiPhase = 'taken';
        occupancyGateIntentEndRun = false;
        configureStationActions();
        applyOccupancyGateUi();
      });
    }
    const pr = document.getElementById('wf-paused-resume');
    if (pr) pr.addEventListener('click', () => openOccupancyVerify('resume'));
    const vScan = document.getElementById('wf-verify-scan');
    if (vScan) vScan.addEventListener('click', () => startVerifyQrScan().catch((e) => statusLine(String(e), 'error')));
    const vStop = document.getElementById('wf-verify-scan-stop');
    if (vStop) vStop.addEventListener('click', () => stopVerifyQrScanner().catch((e) => statusLine(String(e), 'error')));
    const vOk = document.getElementById('wf-verify-confirm');
    if (vOk) vOk.addEventListener('click', () => confirmOccupancyVerify().catch((e) => statusLine(String(e), 'error')));
    const vCx = document.getElementById('wf-verify-cancel');
    if (vCx) vCx.addEventListener('click', () => cancelOccupancyVerify());
    window.addEventListener('beforeunload', () => {
      stopProductQrScanner().catch(() => {});
      stopVerifyQrScanner().catch(() => {});
      stopSourceQrScanner().catch(() => {});
    });
  });
})();
