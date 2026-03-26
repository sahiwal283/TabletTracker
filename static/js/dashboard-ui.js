/**
 * Dashboard UI interactions that can be delegated safely.
 * Keeps behavior parity while reducing inline template handlers.
 */
(function () {
    'use strict';

    function toggleRecentSubmissionsPanel() {
        var content = document.getElementById('recent-submissions-content');
        var icon = document.getElementById('submissions-toggle-icon');
        var toggle = document.getElementById('recent-submissions-toggle');
        if (!content || !icon || !toggle) return;

        var isHidden = content.classList.contains('hidden');
        content.classList.toggle('hidden');
        icon.classList.toggle('rotate-90');
        toggle.setAttribute('aria-expanded', isHidden ? 'true' : 'false');
    }

    function bindTabletTypeSelector() {
        var select = document.getElementById('report_tablet_type');
        if (select && typeof window.convertToTwoLevelDropdown === 'function') {
            window.convertToTwoLevelDropdown(select);
        }
    }

    function onDashboardClick(event) {
        var row = event.target.closest('[data-receive-id]');
        if (row && typeof window.viewReceiveDetails === 'function') {
            var receiveId = parseInt(row.getAttribute('data-receive-id'), 10);
            var receiveName = row.getAttribute('data-receive-name') || '';
            if (!Number.isNaN(receiveId)) window.viewReceiveDetails(receiveId, receiveName);
            return;
        }

        var subRow = event.target.closest('[data-submission-id]');
        if (subRow && typeof window.viewSubmissionDetails === 'function') {
            var subId = parseInt(subRow.getAttribute('data-submission-id'), 10);
            if (!Number.isNaN(subId)) window.viewSubmissionDetails(subId);
            return;
        }

        var ambiguousRow = event.target.closest('[data-ambiguous-submission-id]');
        if (ambiguousRow && typeof window.viewAmbiguousSubmission === 'function') {
            var ambiguousId = parseInt(ambiguousRow.getAttribute('data-ambiguous-submission-id'), 10);
            if (!Number.isNaN(ambiguousId)) window.viewAmbiguousSubmission(ambiguousId);
            return;
        }

        var adminNotesTrigger = event.target.closest('.js-admin-notes-trigger');
        if (adminNotesTrigger && typeof window.showAdminNotes === 'function') {
            event.stopPropagation();
            window.showAdminNotes(adminNotesTrigger.getAttribute('data-admin-notes') || '');
            return;
        }

        var recentToggle = event.target.closest('#recent-submissions-toggle');
        if (recentToggle) {
            toggleRecentSubmissionsPanel();
        }
    }

    function onDashboardKeydown(event) {
        if (event.key !== 'Enter' && event.key !== ' ') return;
        var recentToggle = event.target.closest('#recent-submissions-toggle');
        if (!recentToggle) return;
        event.preventDefault();
        toggleRecentSubmissionsPanel();
    }

    document.addEventListener('DOMContentLoaded', function () {
        bindTabletTypeSelector();
        document.addEventListener('click', onDashboardClick);
        document.addEventListener('keydown', onDashboardKeydown);
    });
})();
