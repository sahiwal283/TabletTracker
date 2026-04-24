
(function () {
  let html5QrCode = null;
  let productScanDone = false;
  let hasLoadedBag = false;
  let stationClaimed = false;
  /** When true, bag was paused at this station — submit/pause blocked until Resume (server: resume_required). */
  let stationNeedsResume = false;

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
  function actionButtons() {
    /* Resume is not in this list so a submit/pause cooldown cannot block the next-day Resume action. */
    return [
      document.getElementById('wf-claim'),
      document.getElementById('wf-save-count'),
      document.getElementById('wf-save-blister'),
      document.getElementById('wf-handpack-rest'),
      document.getElementById('wf-save-seal'),
      document.getElementById('wf-pause-count'),
      document.getElementById('wf-taken-delivery'),
    ].filter(Boolean);
  }
  function shownOnlyWhenBagLoaded() {
    return [
      document.getElementById('wf-count-label'),
      document.getElementById('wf-count-total'),
      document.getElementById('wf-employee-name-label'),
      document.getElementById('wf-employee-name'),
      document.getElementById('wf-claim'),
      document.getElementById('wf-save-count'),
      document.getElementById('wf-save-blister'),
      document.getElementById('wf-handpack-rest'),
      document.getElementById('wf-save-seal'),
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
  function applyStationFacts(data) {
    if (!data || !data.facts) {
      return;
    }
    if (data.facts.station_claimed !== undefined) {
      stationClaimed = !!data.facts.station_claimed;
    }
    stationNeedsResume = !!data.facts.resume_required;
    renderBagVerification(data.facts);
  }
  function setBagLoadedUi(loaded) {
    if (!loaded) {
      shownOnlyWhenBagLoaded().forEach(function (el) {
        el.classList.add('hidden');
      });
    }
    if (loaded) {
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
    renderBagVerification(null);
    clearAllActionCooldowns();
    setBagLoadedUi(false);
    setActionsEnabled(false);
    if (showHint) {
      statusLine('Scan or enter bag card token, then tap Refresh bag status.', 'info');
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
  function hidePackagingStationExtra() {
    [
      'wf-packs-remaining-label',
      'wf-packs-remaining',
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
      'wf-cards-reopened-label',
      'wf-cards-reopened-help',
      'wf-cards-reopened',
      'wf-taken-displays-label',
      'wf-taken-displays-help',
      'wf-taken-displays',
    ].forEach(function (id) {
      var el = document.getElementById(id);
      if (el) el.classList.remove('hidden');
    });
    var tb = document.getElementById('wf-taken-delivery');
    if (tb) {
      tb.classList.remove('hidden');
      tb.disabled = false;
      tb.classList.remove('opacity-50', 'cursor-not-allowed');
    }
  }
  function clearPackagingSnapshotFields() {
    ['wf-packs-remaining', 'wf-cards-reopened', 'wf-taken-displays'].forEach(function (id) {
      var el = document.getElementById(id);
      if (el) el.value = '';
    });
  }
  function configureStationActions() {
    const kind = stationKind();
    const hint = document.getElementById('wf-station-hint');
    const countLabel = document.getElementById('wf-count-label');
    const countTotal = document.getElementById('wf-count-total');
    const claimBtn = document.getElementById('wf-claim');
    const saveBtn = document.getElementById('wf-save-count');
    const saveBlisterBtn = document.getElementById('wf-save-blister');
    const handpackBtn = document.getElementById('wf-handpack-rest');
    const saveSealBtn = document.getElementById('wf-save-seal');
    const pauseBtn = document.getElementById('wf-pause-count');
    const resumeBtn = document.getElementById('wf-resume-bag');
    const empLabel = document.getElementById('wf-employee-name-label');
    const empInput = document.getElementById('wf-employee-name');
    if (!saveBtn || !pauseBtn || !claimBtn || !countTotal) return;
    if (resumeBtn) resumeBtn.classList.add('hidden');
    if (empLabel) empLabel.classList.add('hidden');
    if (empInput) empInput.classList.add('hidden');
    hidePackagingStationExtra();
    if (saveBlisterBtn) saveBlisterBtn.classList.add('hidden');
    if (handpackBtn) handpackBtn.classList.add('hidden');
    if (saveSealBtn) saveSealBtn.classList.add('hidden');
    claimBtn.classList.add('hidden');
    saveBtn.classList.add('hidden');
    pauseBtn.classList.add('hidden');
    countLabel && countLabel.classList.add('hidden');
    countTotal.classList.add('hidden');
    if (!hasLoadedBag) {
      return;
    }
    if (!stationClaimed) {
      claimBtn.classList.remove('hidden');
      if (hint) {
        hint.classList.remove('hidden');
        hint.textContent = 'Claim bag at this station to unlock count and pause actions.';
      }
      return;
    }
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
    if (empLabel) empLabel.classList.remove('hidden');
    if (empInput) empInput.classList.remove('hidden');
    saveBtn.classList.remove('hidden');
    pauseBtn.classList.remove('hidden');
    if (kind === 'blister') {
      saveBtn.textContent = 'Submit blister count';
      pauseBtn.textContent = 'Pause blister bag';
      if (handpackBtn) handpackBtn.classList.remove('hidden');
      if (countLabel) countLabel.textContent = 'Blister machine count total';
      if (hint) {
        hint.classList.remove('hidden');
        hint.textContent =
          'Blister lane: submit blister count, or use Hand pack the rest if machine stopped mid-bag, or pause with current count.';
      }
    } else if (kind === 'sealing') {
      saveBtn.textContent = 'Submit sealing count';
      pauseBtn.textContent = 'Pause sealing bag';
      if (countLabel) countLabel.textContent = 'Sealing machine count total';
      if (hint) {
        hint.classList.remove('hidden');
        hint.textContent = 'Sealing lane: submit sealing machine count, or pause with current count.';
      }
    } else if (kind === 'packaging') {
      saveBtn.textContent = 'Submit';
      pauseBtn.textContent = 'Pause packaging bag';
      if (countLabel) countLabel.textContent = 'Packaging display count';
      showPackagingStationExtra();
      if (hint) {
        hint.classList.remove('hidden');
        hint.textContent =
          'Submit saves counts and finishes the bag. Pause for handoff, or Taken when displays leave for delivery/order.';
      }
    } else if (kind === 'combined') {
      saveBtn.classList.add('hidden');
      if (saveBlisterBtn) saveBlisterBtn.classList.remove('hidden');
      if (handpackBtn) handpackBtn.classList.remove('hidden');
      if (saveSealBtn) saveSealBtn.classList.remove('hidden');
      pauseBtn.textContent = 'Pause combined bag';
      if (countLabel) countLabel.textContent = 'Machine count total';
      if (hint) {
        hint.classList.remove('hidden');
        hint.textContent =
          'Combined lane: submit blister or sealing count, use Hand pack the rest when blister machine fails mid-bag, or pause with current count.';
      }
    } else {
      if (countLabel) countLabel.textContent = 'Machine count total';
      if (hint) {
        hint.classList.remove('hidden');
        hint.textContent = 'Submit machine count for this station, or pause with current count.';
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
  async function postJson(path, body) {
    const r = await fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) {
      const code = data.code || 'error';
      throw new Error(code + ': ' + (data.message || r.status));
    }
    return data;
  }
  async function refresh() {
    const stationToken = document.getElementById('wf-station-token').value;
    const inp = productInput();
    const cardToken = inp ? inp.value.trim() : '';
    if (!cardToken) {
      statusLine('Enter card token', 'error');
      return;
    }
    const data = await postJson('/workflow/floor/api/bag', {
      station_token: stationToken,
      card_token: cardToken,
      device_id: deviceId(),
      page_session_id: pageSessionId(),
    });
    hasLoadedBag = true;
    applyStationFacts(data);
    setBagLoadedUi(true);
    setActionsEnabled(true);
    configureStationActions();
    if (!stationClaimed) {
      statusLine('Bag loaded. Claim it at this station to continue.', 'info');
    } else {
      statusLine('Bag loaded.', 'success');
    }
  }
  async function claimBag() {
    ensureLoadedBag();
    const kind = stationKind();
    const data = await emitEvent('BAG_CLAIMED', {
      station_id: window.WF_STATION_ID || 0,
      station_kind: kind,
      note: 'claimed_on_station',
    });
    applyStationFacts(data);
    configureStationActions();
    setActionsEnabled(true);
    statusLine('Bag claimed at this station.', 'success');
  }
  async function saveCountAndContinue() {
    ensureLoadedBag();
    assertActionCooldown('submit');
    const kind = stationKind();
    const countTotal = selectedCountTotal();
    if (kind === 'blister' || kind === 'combined') {
      await emitEvent('BLISTER_COMPLETE', {
        count_total: countTotal,
        employee_name: requiredEmployeeName(),
      });
      clearCountField();
      clearEmployeeNameField();
      configureStationActions();
      startCooldownAfterSuccess('submit');
      statusLine('Blister count submitted.' + MSG_SCAN_NEXT_CARD, 'success');
      return;
    }
    if (kind === 'sealing') {
      await emitEvent('SEALING_COMPLETE', {
        station_id: window.WF_STATION_ID || 1,
        count_total: countTotal,
        employee_name: requiredEmployeeName(),
      });
      clearCountField();
      clearEmployeeNameField();
      configureStationActions();
      startCooldownAfterSuccess('submit');
      statusLine('Sealing count submitted.' + MSG_SCAN_NEXT_CARD, 'success');
      return;
    }
    if (kind === 'packaging') {
      await submitPackagingAndFinalize();
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
    clearCountField();
    clearEmployeeNameField();
    configureStationActions();
    startCooldownAfterSuccess('submitBlister');
    statusLine('Blister count submitted.' + MSG_SCAN_NEXT_CARD, 'success');
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
    clearCountField();
    clearEmployeeNameField();
    configureStationActions();
    startCooldownAfterSuccess('submitSeal');
    statusLine('Sealing count submitted.' + MSG_SCAN_NEXT_CARD, 'success');
  }
  async function handPackRestAfterBlister() {
    ensureLoadedBag();
    const kind = stationKind();
    if (kind !== 'blister' && kind !== 'combined') {
      throw new Error('Hand pack rest is only available for blister lanes.');
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
    clearCountField();
    clearEmployeeNameField();
    configureStationActions();
    startCooldownAfterSuccess('handpackRest');
    statusLine(
      'Blister count submitted and flagged for hand-packed remainder.' + MSG_SCAN_NEXT_CARD,
      'success'
    );
  }
  async function pauseWithCount() {
    ensureLoadedBag();
    assertActionCooldown('pause');
    const kind = stationKind();
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
      return;
    }
    if (kind === 'packaging') {
      await emitEvent('PACKAGING_SNAPSHOT', {
        display_count: countTotal,
        packs_remaining: optionalNonNegativeInt('wf-packs-remaining', 'Cards remaining'),
        cards_reopened: optionalNonNegativeInt('wf-cards-reopened', 'Cards re-opened'),
        reason: 'paused_end_of_day',
        employee_name: requiredEmployeeName(),
      });
      clearCountField();
      clearEmployeeNameField();
      clearPackagingSnapshotFields();
      configureStationActions();
      startCooldownAfterSuccess('pause');
      statusLine(MSG_PAUSE_RESUME_TOMORROW, 'success');
      return;
    }
    throw new Error('Unsupported station kind: ' + kind);
  }
  async function submitPackagingAndFinalize() {
    ensureLoadedBag();
    assertActionCooldown('submit');
    const countTotal = selectedCountTotal();
    await emitEvent('PACKAGING_SNAPSHOT', {
      display_count: countTotal,
      packs_remaining: optionalNonNegativeInt('wf-packs-remaining', 'Cards remaining'),
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
    startCooldownAfterSuccess('submit');
    statusLine('Packaging counts saved and bag finalized.' + MSG_SCAN_NEXT_CARD, 'success');
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
    configureStationActions();
    setActionsEnabled(true);
    startCooldownAfterSuccess('taken');
    statusLine('Taken-for-order displays recorded.' + MSG_SCAN_NEXT_CARD, 'success');
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
    configureStationActions();
    setActionsEnabled(true);
  }
  document.addEventListener('DOMContentLoaded', () => {
    loadEmployeeNameFromStorage();
    resetLoadedBagState(true);
    configureStationActions();
    const inp = productInput();
    if (inp) {
      inp.addEventListener('input', () => {
        resetLoadedBagState(false);
      });
    }
    const emp = employeeNameInput();
    if (emp) emp.addEventListener('blur', () => persistEmployeeName());
    const r = document.getElementById('wf-refresh');
    if (r) r.addEventListener('click', () => refresh().catch((e) => {
      resetLoadedBagState(false);
      statusLine(String(e), 'error');
    }));
    const c = document.getElementById('wf-claim');
    if (c) c.addEventListener('click', () => claimBag().catch((e) => statusLine(String(e), 'error')));
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
    const taken = document.getElementById('wf-taken-delivery');
    if (taken) taken.addEventListener('click', () => takenForDelivery().catch((e) => statusLine(String(e), 'error')));
    const resume = document.getElementById('wf-resume-bag');
    if (resume) resume.addEventListener('click', () => resumeBag().catch((e) => statusLine(String(e), 'error')));
    const sp = document.getElementById('wf-scan-product');
    if (sp) sp.addEventListener('click', () => startProductQrScan().catch((e) => statusLine(String(e), 'error')));
    const st = document.getElementById('wf-scan-stop');
    if (st) st.addEventListener('click', () => stopProductQrScanner().catch((e) => statusLine(String(e), 'error')));
    window.addEventListener('beforeunload', () => {
      stopProductQrScanner().catch(() => {});
    });
  });
})();
