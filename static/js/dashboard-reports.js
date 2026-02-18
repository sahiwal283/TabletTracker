/**
 * Dashboard reports module: PO/receive selectors, report type, generate report.
 * Uses apiCall with requestKey to cancel superseded fetches; debounces report type change.
 */
(function () {
    'use strict';

    function debounce(fn, ms) {
        var t;
        return function () {
            var a = arguments;
            clearTimeout(t);
            t = setTimeout(function () { fn.apply(null, a); }, ms);
        };
    }

    async function loadAvailablePOs() {
        var selector = document.getElementById('po_selector');
        if (!selector) return;
        selector.innerHTML = '<option value="">Loading POs...</option>';
        selector.disabled = true;
        try {
            var data = await apiCall('/api/reports/po-summary', { requestKey: 'po-summary' });
            selector.innerHTML = '<option value="">Select a PO...</option>';
            selector.disabled = false;
            if (data.success && data.pos && Array.isArray(data.pos)) {
                if (data.pos.length === 0) {
                    selector.innerHTML = '<option value="">No POs found</option>';
                    return;
                }
                data.pos.forEach(function (po) {
                    if (!po || !po.po_number) return;
                    var option = document.createElement('option');
                    option.value = po.po_number;
                    option.textContent = po.po_number + ' - ' + (po.tablet_type || 'N/A') + ' (' + (po.ordered || 0) + ' tablets)';
                    option.dataset.poData = JSON.stringify(po);
                    selector.appendChild(option);
                });
            } else {
                selector.innerHTML = '<option value="">Error loading POs</option>';
                if (data.error) alert('Error loading POs: ' + data.error);
            }
        } catch (e) {
            if (e.name === 'AbortError') return;
            selector.innerHTML = '<option value="">Error loading POs</option>';
            selector.disabled = false;
            alert('Failed to load purchase orders: ' + (e.message || e));
        }
    }

    async function fetchReceives() {
        var receiveSelector = document.getElementById('receive_selector');
        if (!receiveSelector) return;
        try {
            var data = await apiCall('/api/receives/list', { requestKey: 'receives-list' });
            if (!data.success) return;
            receiveSelector.innerHTML = '<option value="">Select a receive...</option>';
            if (!data.receives || data.receives.length === 0) return;
            data.receives.forEach(function (receive) {
                var receiveName = receive.receive_name || (receive.po_number ? receive.po_number : 'Receive ' + receive.id);
                var option = document.createElement('option');
                option.value = receive.id;
                option.textContent = (receiveName || 'Receive ' + receive.id) + (receive.received_date ? ' (' + new Date(receive.received_date).toLocaleDateString() + ')' : '');
                receiveSelector.appendChild(option);
            });
            if (!receiveSelector.hasAttribute('data-listener-added')) {
                receiveSelector.addEventListener('change', function () {
                    var btn = document.getElementById('generate-report-btn');
                    if (btn) btn.disabled = !this.value;
                });
                receiveSelector.setAttribute('data-listener-added', 'true');
            }
        } catch (e) {
            if (e.name === 'AbortError') return;
        }
    }

    function handleReportTypeChange() {
        var reportType = document.getElementById('report_type_selector').value;
        var generateBtnText = document.getElementById('generate-report-btn-text');
        var generateBtn = document.getElementById('generate-report-btn');
        var poSelectorContainer = document.getElementById('po_selector_container');
        var receiveSelectorContainer = document.getElementById('receive_selector_container');
        var receiveSelector = document.getElementById('receive_selector');
        if (reportType === 'vendor') {
            generateBtnText.textContent = 'Generate Vendor Report';
            poSelectorContainer.classList.remove('hidden');
            receiveSelectorContainer.classList.add('hidden');
            generateBtn.disabled = false;
        } else if (reportType === 'production') {
            generateBtnText.textContent = 'Generate Production Report';
            poSelectorContainer.classList.remove('hidden');
            receiveSelectorContainer.classList.add('hidden');
            generateBtn.disabled = !document.getElementById('po_selector').value;
        } else if (reportType === 'receive') {
            generateBtnText.textContent = 'Generate Receive Report';
            poSelectorContainer.classList.add('hidden');
            receiveSelectorContainer.classList.remove('hidden');
            generateBtn.disabled = !receiveSelector.value;
            if (receiveSelector.options.length <= 1) fetchReceives();
        }
    }

    function setupPOSelectorListener() {
        var selector = document.getElementById('po_selector');
        if (!selector) return;
        selector.addEventListener('change', function () {
            var selectedOption = this.options[this.selectedIndex];
            var button = document.getElementById('generate-report-btn');
            var preview = document.getElementById('po_preview');
            var previewContent = document.getElementById('po_preview_content');
            var reportType = (document.getElementById('report_type_selector') || {}).value || 'vendor';
            if (reportType === 'vendor') {
                if (button) button.disabled = false;
                if (preview) preview.classList.add('hidden');
            } else if (reportType === 'production') {
                if (this.value && selectedOption.dataset.poData) {
                    if (button) button.disabled = false;
                    if (preview && previewContent) {
                        preview.classList.remove('hidden');
                        var poData = JSON.parse(selectedOption.dataset.poData);
                        previewContent.innerHTML = '<div><strong>PO Number:</strong> ' + (poData.po_number || '') + '</div><div><strong>Tablet Type:</strong> ' + (poData.tablet_type || 'N/A') + '</div><div><strong>Status:</strong> ' + (poData.status || 'Unknown') + '</div><div><strong>Ordered:</strong> ' + (poData.ordered || 0) + ' tablets</div><div><strong>Produced:</strong> ' + (poData.produced || 0) + '</div><div><strong>Damaged:</strong> ' + (poData.damaged || 0) + '</div><div><strong>Submissions:</strong> ' + (poData.submissions || 0) + '</div>' + (poData.pack_time_days ? '<div><strong>Pack Time:</strong> ' + poData.pack_time_days + ' days</div>' : '');
                    }
                } else {
                    if (button) button.disabled = true;
                    if (preview) preview.classList.add('hidden');
                }
            }
        });
    }

    document.addEventListener('DOMContentLoaded', function () {
        loadAvailablePOs();
        var reportTypeSelector = document.getElementById('report_type_selector');
        var generateBtn = document.getElementById('generate-report-btn');
        if (generateBtn) generateBtn.disabled = false;
        if (reportTypeSelector) reportTypeSelector.addEventListener('change', debounce(handleReportTypeChange, 150));
        setupPOSelectorListener();
    });

    window.loadAvailablePOs = loadAvailablePOs;
    window.fetchReceives = fetchReceives;
    window.handleReportTypeChange = handleReportTypeChange;
})();
