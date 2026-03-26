/**
 * Submissions page UI delegation.
 * Keeps server-rendered behavior while reducing inline handlers.
 */
(function () {
    'use strict';

    function onClick(event) {
        var notesTrigger = event.target.closest('.js-admin-notes-trigger');
        if (notesTrigger && typeof window.showAdminNotes === 'function') {
            event.stopPropagation();
            window.showAdminNotes(notesTrigger.getAttribute('data-admin-notes') || '');
            return;
        }

        var deleteButton = event.target.closest('[data-delete-submission-id]');
        if (deleteButton && typeof window.deleteSubmission === 'function') {
            event.stopPropagation();
            var deleteId = parseInt(deleteButton.getAttribute('data-delete-submission-id'), 10);
            if (!Number.isNaN(deleteId)) window.deleteSubmission(deleteId);
            return;
        }

        var reassignButton = event.target.closest('[data-open-reassign-submission-id]');
        if (reassignButton && typeof window.openReassignModal === 'function') {
            event.stopPropagation();
            var subId = parseInt(reassignButton.getAttribute('data-open-reassign-submission-id'), 10);
            var needsReview = parseInt(reassignButton.getAttribute('data-needs-review') || '0', 10) || 0;
            var productName = reassignButton.getAttribute('data-product-name') || '';
            if (!Number.isNaN(subId)) window.openReassignModal(subId, null, productName, needsReview);
            return;
        }

        var row = event.target.closest('tr[data-submission-id]');
        if (row && typeof window.viewSubmissionDetails === 'function') {
            var rowId = parseInt(row.getAttribute('data-submission-id'), 10);
            if (!Number.isNaN(rowId)) window.viewSubmissionDetails(rowId);
        }
    }

    document.addEventListener('DOMContentLoaded', function () {
        var select = document.getElementById('tablet_type_id');
        if (select && typeof window.convertToTwoLevelDropdown === 'function') {
            window.convertToTwoLevelDropdown(select);
        }
        document.addEventListener('click', onClick);
    });
})();
