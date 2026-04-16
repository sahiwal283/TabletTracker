
(function () {
  let html5QrCode = null;
  let productScanDone = false;
  let hasLoadedBag = false;

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
  function statusLine(msg) {
    const el = document.getElementById('wf-status');
    if (el) el.textContent = msg;
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
    shownOnlyWhenBagLoaded().forEach(function (el) {
      if (!loaded) {
        el.classList.add('hidden');
      } else {
        // Keep combined-only buttons hidden unless configureStationActions reveals them.
        if (el.id === 'wf-save-blister' || el.id === 'wf-save-seal') return;
        el.classList.remove('hidden');
      }
    });
    if (loaded) {
      configureStationActions();
    }
  }
  function setActionsEnabled(enabled) {
    actionButtons().forEach(function (btn) {
      btn.disabled = !enabled;
      btn.classList.toggle('opacity-50', !enabled);
      btn.classList.toggle('cursor-not-allowed', !enabled);
    });
  }
  function resetLoadedBagState(showHint) {
    hasLoadedBag = false;
    setBagLoadedUi(false);
    setActionsEnabled(false);
    if (showHint) {
      statusLine('Scan or enter bag card token, then tap Refresh bag status.');
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
    const saveBtn = document.getElementById('wf-save-count');
    const saveBlisterBtn = document.getElementById('wf-save-blister');
    const saveSealBtn = document.getElementById('wf-save-seal');
    const pauseBtn = document.getElementById('wf-pause-count');
    if (!saveBtn || !pauseBtn) return;
    if (saveBlisterBtn) saveBlisterBtn.classList.add('hidden');
    if (saveSealBtn) saveSealBtn.classList.add('hidden');
    if (kind === 'blister') {
      saveBtn.textContent = 'Submit blister count';
      pauseBtn.textContent = 'Pause blister bag';
      if (countLabel) countLabel.textContent = 'Blister machine count total';
      if (hint) hint.textContent = 'Blister lane: claim bag, submit blister machine count, or pause with current count.';
    } else if (kind === 'sealing') {
      saveBtn.textContent = 'Submit sealing count';
      pauseBtn.textContent = 'Pause sealing bag';
      if (countLabel) countLabel.textContent = 'Sealing machine count total';
      if (hint) hint.textContent = 'Sealing lane: claim bag, submit sealing machine count, or pause with current count.';
    } else if (kind === 'packaging') {
      saveBtn.textContent = 'Save packaging displays';
      pauseBtn.textContent = 'Pause packaging bag';
      if (countLabel) countLabel.textContent = 'Packaging display count';
      if (hint) hint.textContent = 'Packaging lane: claim bag, save display count snapshot, or pause for handoff.';
    } else if (kind === 'combined') {
      saveBtn.classList.add('hidden');
      if (saveBlisterBtn) saveBlisterBtn.classList.remove('hidden');
      if (saveSealBtn) saveSealBtn.classList.remove('hidden');
      pauseBtn.textContent = 'Pause combined bag';
      if (countLabel) countLabel.textContent = 'Machine count total';
      if (hint) hint.textContent = 'Combined lane: claim bag, submit blister or sealing count, or pause with current count.';
    } else {
      if (countLabel) countLabel.textContent = 'Machine count total';
      if (hint) hint.textContent = 'Combined lane: claim bag and submit machine count for your lane.';
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
      statusLine('Error: open this page from your station QR first. Station token is missing.');
      return;
    }
    if (typeof Html5Qrcode === 'undefined') {
      statusLine('Scanner failed to load. Check your connection and refresh the page.');
      return;
    }
    await stopProductQrScanner();
    productScanDone = false;
    const readerId = 'wf-productqr-reader';
    const el = document.getElementById(readerId);
    if (!el) return;
    html5QrCode = new Html5Qrcode(readerId);
    setScanUi(true);
    statusLine('Point the camera at the product/bag QR code.');
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
            statusLine('Product QR captured — loading bag…');
            await refresh();
          } catch (err) {
            statusLine(String(err));
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
          statusLine('Camera permission denied. Allow camera access in Safari settings and try again.');
        } else {
          statusLine('Could not start camera: ' + msg);
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
      statusLine('Enter card token');
      return;
    }
    const data = await postJson('/workflow/floor/api/bag', {
      station_token: stationToken,
      card_token: cardToken,
      device_id: deviceId(),
      page_session_id: pageSessionId(),
    });
    hasLoadedBag = true;
    setBagLoadedUi(true);
    setActionsEnabled(true);
    statusLine(JSON.stringify(data.facts, null, 2));
  }
  async function claimBag() {
    ensureLoadedBag();
    const kind = stationKind();
    const data = await emitEvent('BAG_CLAIMED', {
      station_id: window.WF_STATION_ID || 0,
      station_kind: kind,
      note: 'claimed_on_station',
    });
    statusLine(JSON.stringify(data.facts, null, 2));
  }
  async function saveCountAndContinue() {
    ensureLoadedBag();
    const kind = stationKind();
    const countTotal = selectedCountTotal();
    if (kind === 'blister' || kind === 'combined') {
      const data = await emitEvent('BLISTER_COMPLETE', { count_total: countTotal });
      statusLine(JSON.stringify(data.facts, null, 2));
      return;
    }
    if (kind === 'sealing') {
      const data = await emitEvent('SEALING_COMPLETE', {
        station_id: window.WF_STATION_ID || 1,
        count_total: countTotal,
      });
      statusLine(JSON.stringify(data.facts, null, 2));
      return;
    }
    if (kind === 'packaging') {
      const data = await emitEvent('PACKAGING_SNAPSHOT', {
        display_count: countTotal,
        reason: 'live_count',
      });
      statusLine(JSON.stringify(data.facts, null, 2));
      return;
    }
    throw new Error('Unsupported station kind: ' + kind);
  }
  async function saveBlisterCountOnly() {
    ensureLoadedBag();
    const countTotal = selectedCountTotal();
    const data = await emitEvent('BLISTER_COMPLETE', { count_total: countTotal });
    statusLine(JSON.stringify(data.facts, null, 2));
  }
  async function saveSealingCountOnly() {
    ensureLoadedBag();
    const countTotal = selectedCountTotal();
    const data = await emitEvent('SEALING_COMPLETE', {
      station_id: window.WF_STATION_ID || 1,
      count_total: countTotal,
    });
    statusLine(JSON.stringify(data.facts, null, 2));
  }
  async function pauseWithCount() {
    ensureLoadedBag();
    const kind = stationKind();
    const countTotal = selectedCountTotal();
    if (kind === 'blister' || kind === 'combined') {
      const data = await emitEvent('BLISTER_COMPLETE', {
        count_total: countTotal,
        metadata: { paused: true, reason: 'end_of_day' },
      });
      statusLine('Paused with saved blister count. ' + JSON.stringify(data.facts));
      return;
    }
    if (kind === 'sealing') {
      const data = await emitEvent('SEALING_COMPLETE', {
        station_id: window.WF_STATION_ID || 1,
        count_total: countTotal,
        metadata: { paused: true, reason: 'end_of_day' },
      });
      statusLine('Paused with saved sealing count. ' + JSON.stringify(data.facts));
      return;
    }
    if (kind === 'packaging') {
      const data = await emitEvent('PACKAGING_SNAPSHOT', {
        display_count: countTotal,
        reason: 'paused_end_of_day',
      });
      statusLine('Paused with saved packaging count. ' + JSON.stringify(data.facts));
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
    statusLine(JSON.stringify(data, null, 2));
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
      statusLine(String(e));
    }));
    const c = document.getElementById('wf-claim');
    if (c) c.addEventListener('click', () => claimBag().catch((e) => statusLine(String(e))));
    const save = document.getElementById('wf-save-count');
    if (save) save.addEventListener('click', () => saveCountAndContinue().catch((e) => statusLine(String(e))));
    const saveBlister = document.getElementById('wf-save-blister');
    if (saveBlister) saveBlister.addEventListener('click', () => saveBlisterCountOnly().catch((e) => statusLine(String(e))));
    const saveSeal = document.getElementById('wf-save-seal');
    if (saveSeal) saveSeal.addEventListener('click', () => saveSealingCountOnly().catch((e) => statusLine(String(e))));
    const pause = document.getElementById('wf-pause-count');
    if (pause) pause.addEventListener('click', () => pauseWithCount().catch((e) => statusLine(String(e))));
    const f = document.getElementById('wf-finalize');
    if (f) f.addEventListener('click', () => finalize().catch((e) => statusLine(String(e))));
    const sp = document.getElementById('wf-scan-product');
    if (sp) sp.addEventListener('click', () => startProductQrScan().catch((e) => statusLine(String(e))));
    const st = document.getElementById('wf-scan-stop');
    if (st) st.addEventListener('click', () => stopProductQrScanner().catch((e) => statusLine(String(e))));
    window.addEventListener('beforeunload', () => {
      stopProductQrScanner().catch(() => {});
    });
  });
})();
