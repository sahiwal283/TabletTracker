/* Bag card scan + two-level product dropdown for assign-bag forms (standalone + Command Center). */
(function () {
  document.addEventListener('DOMContentLoaded', function () {
    var el = document.getElementById('wv_assign_tablet') || document.getElementById('wv_assign_product');
    if (el && typeof convertToTwoLevelDropdownByDataAttr === 'function') {
      convertToTwoLevelDropdownByDataAttr(el, 'data-category');
    }

    var activeScanner = null;

    function scanner(opts) {
      var qr = null;
      var scanDone = false;
      var scanBtn = document.getElementById(opts.scanBtnId);
      var stopBtn = document.getElementById(opts.stopBtnId);
      var wrap = document.getElementById(opts.wrapId);

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
        if (activeScanner === stopScan) activeScanner = null;
        setScanUi(false);
      }

      async function startScan() {
        if (activeScanner && activeScanner !== stopScan) {
          await activeScanner();
        }
        activeScanner = stopScan;
        if (typeof Html5Qrcode === 'undefined') {
          window.alert('Scanner failed to load. Refresh and try again.');
          return;
        }
        await stopScan();
        activeScanner = stopScan;
        scanDone = false;
        qr = new Html5Qrcode(opts.readerId);
        setScanUi(true);
        var cfg = { fps: 10, qrbox: { width: 250, height: 250 } };
        function onSuccess(decodedText) {
          if (scanDone && !opts.continuous) return;
          var t = String(decodedText || '').trim();
          if (!t) return;
          scanDone = true;
          opts.onToken(t);
          if (!opts.continuous) stopScan();
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
      return { stop: stopScan };
    }

    var input = document.getElementById('wv_card_scan_token');
    scanner({
      scanBtnId: 'wv-scan-card',
      stopBtnId: 'wv-scan-stop',
      wrapId: 'wv-cardqr-reader-wrap',
      readerId: 'wv-cardqr-reader',
      onToken: function (token) {
        if (input) input.value = token;
      },
    });

    var sourceInput = document.getElementById('wv_variety_source_card_tokens');
    function addSourceToken(token) {
      if (!sourceInput) return;
      var t = String(token || '').trim();
      if (!t) return;
      var current = String(sourceInput.value || '')
        .split(/[\s,]+/)
        .map(function (x) { return x.trim(); })
        .filter(Boolean);
      if (current.indexOf(t) === -1) current.push(t);
      sourceInput.value = current.join('\n');
      sourceInput.dispatchEvent(new Event('input', { bubbles: true }));
    }
    scanner({
      scanBtnId: 'wv-scan-variety-source',
      stopBtnId: 'wv-scan-variety-source-stop',
      wrapId: 'wv-variety-source-reader-wrap',
      readerId: 'wv-variety-source-reader',
      continuous: true,
      onToken: addSourceToken,
    });
    var clearSources = document.getElementById('wv-clear-variety-sources');
    if (clearSources && sourceInput) {
      clearSources.addEventListener('click', function () {
        sourceInput.value = '';
        sourceInput.focus();
      });
    }

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
