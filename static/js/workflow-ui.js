
(function () {
  let html5QrCode = null;
  let productScanDone = false;
  let hasLoadedBag = false;
  let stationClaimed = false;

  /** Prevent double-submit of the same action (pause vs submit are independent). ~1.5 minutes. */
  var SUBMIT_PAUSE_COOLDOWN_MS = 90 * 1000;
  var cooldownUntil = {};
  var cooldownTimers = {};

  const WF_PAGE_SESSION = (crypto.randomUUID && crypto.randomUUID()) || (Date.now() + '-' + Math.random());
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
    return [
      document.getElementById('wf-claim'),
      document.getElementById('wf-save-count'),
      document.getElementById('wf-save-blister'),
      document.getElementById('wf-save-seal'),
      document.getElementById('wf-pause-count'),
      document.getElementById('wf-finalize'),
    ].filter(Boolean);
  }
  function shownOnlyWhenBagLoaded() {
    return [
      document.getElementById('wf-count-label'),
      document.getElementById('wf-count-total'),
      document.getElementById('wf-claim'),
      document.getElementById('wf-save-count'),
      document.getElementById('wf-save-blister'),
      document.getElementById('wf-save-seal'),
      document.getElementById('wf-pause-count'),
      document.getElementById('wf-finalize'),
      document.getElementById('wf-station-hint'),
    ].filter(Boolean);
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
      ['pause', 'wf-pause-count'],
      ['submitBlister', 'wf-save-blister'],
      ['submitSeal', 'wf-save-seal'],
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
  function configureStationActions() {
    const kind = stationKind();
    const hint = document.getElementById('wf-station-hint');
    const countLabel = document.getElementById('wf-count-label');
    const countTotal = document.getElementById('wf-count-total');
    const claimBtn = document.getElementById('wf-claim');
    const finalizeBtn = document.getElementById('wf-finalize');
    const saveBtn = document.getElementById('wf-save-count');
    const saveBlisterBtn = document.getElementById('wf-save-blister');
    const saveSealBtn = document.getElementById('wf-save-seal');
    const pauseBtn = document.getElementById('wf-pause-count');
    if (!saveBtn || !pauseBtn || !claimBtn || !countTotal) return;
    if (saveBlisterBtn) saveBlisterBtn.classList.add('hidden');
    if (saveSealBtn) saveSealBtn.classList.add('hidden');
    if (finalizeBtn) finalizeBtn.classList.add('hidden');
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
    countLabel && countLabel.classList.remove('hidden');
    countTotal.classList.remove('hidden');
    saveBtn.classList.remove('hidden');
    pauseBtn.classList.remove('hidden');
    if (kind === 'blister') {
      saveBtn.textContent = 'Submit blister count';
      pauseBtn.textContent = 'Pause blister bag';
      if (countLabel) countLabel.textContent = 'Blister machine count total';
      if (hint) {
        hint.classList.remove('hidden');
        hint.textContent = 'Blister lane: submit blister machine count, or pause with current count.';
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
      saveBtn.textContent = 'Save packaging displays';
      pauseBtn.textContent = 'Pause packaging bag';
      if (countLabel) countLabel.textContent = 'Packaging display count';
      if (finalizeBtn && hasLoadedBag) finalizeBtn.classList.remove('hidden');
      if (hint) {
        hint.classList.remove('hidden');
        hint.textContent = 'Packaging lane: save display count snapshot, pause for handoff, or finalize.';
      }
    } else if (kind === 'combined') {
      saveBtn.classList.add('hidden');
      if (saveBlisterBtn) saveBlisterBtn.classList.remove('hidden');
      if (saveSealBtn) saveSealBtn.classList.remove('hidden');
      pauseBtn.textContent = 'Pause combined bag';
      if (countLabel) countLabel.textContent = 'Machine count total';
      if (hint) {
        hint.classList.remove('hidden');
        hint.textContent = 'Combined lane: submit blister or sealing count, or pause with current count.';
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
    stationClaimed = !!(data && data.facts && data.facts.station_claimed);
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
    stationClaimed = !!(data && data.facts && data.facts.station_claimed);
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
      await emitEvent('BLISTER_COMPLETE', { count_total: countTotal });
      clearCountField();
      startCooldownAfterSuccess('submit');
      statusLine('Blister count submitted.', 'success');
      return;
    }
    if (kind === 'sealing') {
      await emitEvent('SEALING_COMPLETE', {
        station_id: window.WF_STATION_ID || 1,
        count_total: countTotal,
      });
      clearCountField();
      startCooldownAfterSuccess('submit');
      statusLine('Sealing count submitted.', 'success');
      return;
    }
    if (kind === 'packaging') {
      await emitEvent('PACKAGING_SNAPSHOT', {
        display_count: countTotal,
        reason: 'live_count',
      });
      clearCountField();
      startCooldownAfterSuccess('submit');
      statusLine('Packaging count snapshot saved.', 'success');
      return;
    }
    throw new Error('Unsupported station kind: ' + kind);
  }
  async function saveBlisterCountOnly() {
    ensureLoadedBag();
    assertActionCooldown('submitBlister');
    const countTotal = selectedCountTotal();
    await emitEvent('BLISTER_COMPLETE', { count_total: countTotal });
    clearCountField();
    startCooldownAfterSuccess('submitBlister');
    statusLine('Blister count submitted.', 'success');
  }
  async function saveSealingCountOnly() {
    ensureLoadedBag();
    assertActionCooldown('submitSeal');
    const countTotal = selectedCountTotal();
    await emitEvent('SEALING_COMPLETE', {
      station_id: window.WF_STATION_ID || 1,
      count_total: countTotal,
    });
    clearCountField();
    startCooldownAfterSuccess('submitSeal');
    statusLine('Sealing count submitted.', 'success');
  }
  async function pauseWithCount() {
    ensureLoadedBag();
    assertActionCooldown('pause');
    const kind = stationKind();
    const countTotal = selectedCountTotal();
    if (kind === 'blister' || kind === 'combined') {
      await emitEvent('BLISTER_COMPLETE', {
        count_total: countTotal,
        metadata: { paused: true, reason: 'end_of_day' },
      });
      clearCountField();
      startCooldownAfterSuccess('pause');
      statusLine('Paused — blister count saved for end of day.', 'success');
      return;
    }
    if (kind === 'sealing') {
      await emitEvent('SEALING_COMPLETE', {
        station_id: window.WF_STATION_ID || 1,
        count_total: countTotal,
        metadata: { paused: true, reason: 'end_of_day' },
      });
      clearCountField();
      startCooldownAfterSuccess('pause');
      statusLine('Paused — sealing count saved for end of day.', 'success');
      return;
    }
    if (kind === 'packaging') {
      await emitEvent('PACKAGING_SNAPSHOT', {
        display_count: countTotal,
        reason: 'paused_end_of_day',
      });
      clearCountField();
      startCooldownAfterSuccess('pause');
      statusLine('Paused — packaging snapshot saved for end of day.', 'success');
      return;
    }
    throw new Error('Unsupported station kind: ' + kind);
  }
  async function emitEvent(eventType, payload) {
    const stationToken = document.getElementById('wf-station-token').value;
    const inp = productInput();
    const cardToken = inp ? inp.value.trim() : '';
    return postJson('/workflow/floor/api/event', {
      station_token: stationToken,
      card_token: cardToken,
      device_id: deviceId(),
      page_session_id: pageSessionId(),
      event_type: eventType,
      payload: payload || {},
    });
  }
  async function finalize() {
    ensureLoadedBag();
    const stationToken = document.getElementById('wf-station-token').value;
    const inp = productInput();
    const cardToken = inp ? inp.value.trim() : '';
    const data = await postJson('/workflow/floor/api/finalize', {
      station_token: stationToken,
      card_token: cardToken,
      device_id: deviceId(),
      page_session_id: pageSessionId(),
    });
    statusLine('Bag finalized.', 'success');
  }
  document.addEventListener('DOMContentLoaded', () => {
    resetLoadedBagState(true);
    configureStationActions();
    const inp = productInput();
    if (inp) {
      inp.addEventListener('input', () => {
        resetLoadedBagState(false);
      });
    }
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
    const saveSeal = document.getElementById('wf-save-seal');
    if (saveSeal) saveSeal.addEventListener('click', () => saveSealingCountOnly().catch((e) => statusLine(String(e), 'error')));
    const pause = document.getElementById('wf-pause-count');
    if (pause) pause.addEventListener('click', () => pauseWithCount().catch((e) => statusLine(String(e), 'error')));
    const f = document.getElementById('wf-finalize');
    if (f) f.addEventListener('click', () => finalize().catch((e) => statusLine(String(e), 'error')));
    const sp = document.getElementById('wf-scan-product');
    if (sp) sp.addEventListener('click', () => startProductQrScan().catch((e) => statusLine(String(e), 'error')));
    const st = document.getElementById('wf-scan-stop');
    if (st) st.addEventListener('click', () => stopProductQrScanner().catch((e) => statusLine(String(e), 'error')));
    window.addEventListener('beforeunload', () => {
      stopProductQrScanner().catch(() => {});
    });
  });
})();
