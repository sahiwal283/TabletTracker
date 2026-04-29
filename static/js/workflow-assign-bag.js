/* Bag card scan + two-level product dropdown for assign-bag forms (standalone + Command Center). */
(function () {
  document.addEventListener('DOMContentLoaded', function () {
    var el = document.getElementById('wv_assign_tablet') || document.getElementById('wv_assign_product');
    if (el && typeof convertToTwoLevelDropdownByDataAttr === 'function') {
      convertToTwoLevelDropdownByDataAttr(el, 'data-category');
    }

    var scanBtn = document.getElementById('wv-scan-card');
    var stopBtn = document.getElementById('wv-scan-stop');
    var wrap = document.getElementById('wv-cardqr-reader-wrap');
    var input = document.getElementById('wv_card_scan_token');
    var qr = null;
    var scanDone = false;

    function setScanUi(active) {
      if (wrap) wrap.classList.toggle('hidden', !active);
      if (scanBtn) scanBtn.classList.toggle('hidden', active);
      if (stopBtn) stopBtn.classList.toggle('hidden', !active);
    }

    async function stopScan() {
      scanDone = false;
      if (!qr) {
        setScanUi(false);
        return;
      }
      try {
        await qr.stop();
      } catch (_e) {}
      try {
        await qr.clear();
      } catch (_e2) {}
      qr = null;
      setScanUi(false);
    }

    async function startScan() {
      if (typeof Html5Qrcode === 'undefined') {
        window.alert('Scanner failed to load. Refresh and try again.');
        return;
      }
      await stopScan();
      scanDone = false;
      qr = new Html5Qrcode('wv-cardqr-reader');
      setScanUi(true);
      var cfg = { fps: 10, qrbox: { width: 250, height: 250 } };
      function onSuccess(decodedText) {
        if (scanDone) return;
        var t = String(decodedText || '').trim();
        if (!t) return;
        scanDone = true;
        if (input) input.value = t;
        stopScan();
      }
      function onFailure() {}
      try {
        await qr.start({ facingMode: 'environment' }, cfg, onSuccess, onFailure);
      } catch (e1) {
        try {
          var cameras = await Html5Qrcode.getCameras();
          var back =
            (cameras || []).find(function (d) {
              return /back|rear|environment|wide/i.test(d.label || '');
            }) || (cameras || [])[0];
          if (!back) throw e1;
          await qr.start(back.id, cfg, onSuccess, onFailure);
        } catch (_e2) {
          await stopScan();
          window.alert('Could not start camera. Check permissions and try again.');
        }
      }
    }

    if (scanBtn) scanBtn.addEventListener('click', function () { startScan(); });
    if (stopBtn) stopBtn.addEventListener('click', function () { stopScan(); });
    window.addEventListener('beforeunload', function () { stopScan(); });

    var form = input && input.form ? input.form : null;
    if (form && input) {
      form.addEventListener('submit', function (e) {
        if (!String(input.value || '').trim()) {
          e.preventDefault();
          window.alert('Enter the bag card token or scan the QR (token required).');
        }
      });
    }
  });
})();
