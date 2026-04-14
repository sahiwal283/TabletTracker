
(function () {
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
  });
})();
