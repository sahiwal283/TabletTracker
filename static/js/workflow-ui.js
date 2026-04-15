
(function () {
  let scannerStream = null;
  let scannerRaf = null;
  let scannerDetector = null;

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
  function setScannerVisible(visible) {
    const wrap = document.getElementById('wf-scanner-wrap');
    const openBtn = document.getElementById('wf-scan-open');
    const closeBtn = document.getElementById('wf-scan-close');
    if (wrap) wrap.classList.toggle('hidden', !visible);
    if (openBtn) openBtn.classList.toggle('hidden', visible);
    if (closeBtn) closeBtn.classList.toggle('hidden', !visible);
  }
  function stopScanner() {
    if (scannerRaf) {
      cancelAnimationFrame(scannerRaf);
      scannerRaf = null;
    }
    const video = document.getElementById('wf-scanner-video');
    if (video) video.srcObject = null;
    if (scannerStream) {
      scannerStream.getTracks().forEach((track) => track.stop());
      scannerStream = null;
    }
    setScannerVisible(false);
  }
  async function scanLoop() {
    const video = document.getElementById('wf-scanner-video');
    if (!video || !scannerDetector) return;
    try {
      const codes = await scannerDetector.detect(video);
      if (codes && codes.length > 0) {
        const raw = (codes[0] && codes[0].rawValue) ? String(codes[0].rawValue).trim() : '';
        if (raw) {
          const tokenInput = document.getElementById('wf-card-token');
          if (tokenInput) tokenInput.value = raw;
          statusLine('QR scanned. Card token loaded.');
          stopScanner();
          return;
        }
      }
    } catch (_e) {
      // Keep scanning; transient detector errors are expected on some devices.
    }
    scannerRaf = requestAnimationFrame(scanLoop);
  }
  async function openScanner() {
    if (!window.BarcodeDetector) {
      statusLine('Camera QR scanning is not supported in this browser. Use the Camera app and paste the token here.');
      return;
    }
    try {
      scannerDetector = new BarcodeDetector({ formats: ['qr_code'] });
      scannerStream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: 'environment' } },
        audio: false,
      });
      const video = document.getElementById('wf-scanner-video');
      if (!video) return;
      video.srcObject = scannerStream;
      await video.play();
      setScannerVisible(true);
      statusLine('Scanning... align the QR code inside the camera preview.');
      scannerRaf = requestAnimationFrame(scanLoop);
    } catch (e) {
      stopScanner();
      statusLine('Could not start camera scanner: ' + (e && e.message ? e.message : String(e)));
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
    const cardToken = document.getElementById('wf-card-token').value.trim();
    if (!cardToken) { statusLine('Enter card token'); return; }
    const data = await postJson('/workflow/floor/api/bag', {
      station_token: stationToken,
      card_token: cardToken,
      device_id: deviceId(),
      page_session_id: pageSessionId(),
    });
    statusLine(JSON.stringify(data.facts, null, 2));
  }
  async function emitEvent(eventType, payload) {
    const stationToken = document.getElementById('wf-station-token').value;
    const cardToken = document.getElementById('wf-card-token').value.trim();
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
    const stationToken = document.getElementById('wf-station-token').value;
    const cardToken = document.getElementById('wf-card-token').value.trim();
    const data = await postJson('/workflow/floor/api/finalize', {
      station_token: stationToken,
      card_token: cardToken,
      device_id: deviceId(),
      page_session_id: pageSessionId(),
    });
    statusLine(JSON.stringify(data, null, 2));
  }
  document.addEventListener('DOMContentLoaded', () => {
    const r = document.getElementById('wf-refresh');
    if (r) r.addEventListener('click', () => refresh().catch((e) => statusLine(String(e))));
    const b = document.getElementById('wf-blister');
    if (b) b.addEventListener('click', () => emitEvent('BLISTER_COMPLETE', { count_total: 1 }).then((d) => statusLine(JSON.stringify(d.facts))).catch((e) => statusLine(String(e))));
    const s = document.getElementById('wf-seal');
    if (s) s.addEventListener('click', () => emitEvent('SEALING_COMPLETE', { station_id: window.WF_STATION_ID || 1, count_total: 1 }).then((d) => statusLine(JSON.stringify(d.facts))).catch((e) => statusLine(String(e))));
    const p = document.getElementById('wf-pack');
    if (p) p.addEventListener('click', () => emitEvent('PACKAGING_SNAPSHOT', { display_count: 1, reason: 'sample' }).then((d) => statusLine(JSON.stringify(d.facts))).catch((e) => statusLine(String(e))));
    const f = document.getElementById('wf-finalize');
    if (f) f.addEventListener('click', () => finalize().catch((e) => statusLine(String(e))));
    const so = document.getElementById('wf-scan-open');
    if (so) so.addEventListener('click', () => openScanner().catch((e) => statusLine(String(e))));
    const sc = document.getElementById('wf-scan-close');
    if (sc) sc.addEventListener('click', () => stopScanner());
    window.addEventListener('beforeunload', stopScanner);
  });
})();
