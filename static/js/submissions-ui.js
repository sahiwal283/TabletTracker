/**
 * Submissions page UI delegation.
 * Keeps server-rendered behavior while reducing inline handlers.
 */
(function () {
    'use strict';

    /** Click target may be a Text node (e.g. emoji); Element#closest is required. */
    function clickTargetEl(event) {
        var t = event.target;
        if (t && t.nodeType === 1) {
            return t;
        }
        return t && t.parentElement ? t.parentElement : null;
    }

    function onClick(event) {
        var el = clickTargetEl(event);
        if (!el) {
            return;
        }
        var toggleBtn = el.closest('.js-receipt-toggle');
        if (toggleBtn) {
            event.preventDefault();
            event.stopPropagation();
            var parentRow = toggleBtn.closest('tr.js-receipt-parent');
            if (!parentRow) {
                return;
            }
            var detailRow = parentRow.nextElementSibling;
            if (!detailRow || !detailRow.classList.contains('js-receipt-children')) {
                return;
            }
            var expanded = detailRow.classList.toggle('hidden');
            toggleBtn.setAttribute('aria-expanded', expanded ? 'false' : 'true');
            toggleBtn.textContent = expanded ? '▸' : '▾';
            return;
        }

        var deleteButton = el.closest('[data-delete-submission-id]');
        if (deleteButton && typeof window.deleteSubmission === 'function') {
            event.stopPropagation();
            var deleteId = parseInt(deleteButton.getAttribute('data-delete-submission-id'), 10);
            if (!Number.isNaN(deleteId)) window.deleteSubmission(deleteId);
            return;
        }

        var reassignButton = el.closest('[data-open-reassign-submission-id]');
        if (reassignButton && typeof window.openReassignModal === 'function') {
            event.stopPropagation();
            var subId = parseInt(reassignButton.getAttribute('data-open-reassign-submission-id'), 10);
            var needsReview = parseInt(reassignButton.getAttribute('data-needs-review') || '0', 10) || 0;
            var productName = reassignButton.getAttribute('data-product-name') || '';
            if (!Number.isNaN(subId)) window.openReassignModal(subId, null, productName, needsReview);
            return;
        }

        // Notes icon handles itself via inline onclick in templates.
        var notesButton = el.closest('.js-admin-notes-trigger');
        if (notesButton) {
            event.stopPropagation();
            return;
        }

        var row = el.closest('tr[data-submission-id]');
        if (row && typeof window.viewSubmissionDetails === 'function') {
            var rowId = parseInt(row.getAttribute('data-submission-id'), 10);
            if (!Number.isNaN(rowId)) window.viewSubmissionDetails(rowId);
        }

        var parentReceipt = el.closest('tr.js-receipt-parent');
        if (parentReceipt && !el.closest('a,button,input,textarea,select')) {
            var btn = parentReceipt.querySelector('.js-receipt-toggle');
            if (btn) {
                btn.click();
            }
        }
    }

    function init() {
        var select = document.getElementById('tablet_type_id');
        if (select && typeof window.convertToTwoLevelDropdown === 'function') {
            window.convertToTwoLevelDropdown(select);
        }
        document.addEventListener('click', onClick);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
