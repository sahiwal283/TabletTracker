/**
 * Dashboard UI interactions that can be delegated safely.
 * Keeps behavior parity while reducing inline template handlers.
 */
(function () {
    'use strict';

    function clickTargetEl(event) {
        var t = event.target;
        if (t && t.nodeType === 1) {
            return t;
        }
        return t && t.parentElement ? t.parentElement : null;
    }

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
        var el = clickTargetEl(event);
        if (!el) {
            return;
        }

        var recentToggle = el.closest('#recent-submissions-toggle');
        if (recentToggle) {
            toggleRecentSubmissionsPanel();
            return;
        }

        var row = el.closest('[data-receive-id]');
        if (row && typeof window.viewReceiveDetails === 'function') {
            var receiveId = parseInt(row.getAttribute('data-receive-id'), 10);
            var receiveName = row.getAttribute('data-receive-name') || '';
            if (!Number.isNaN(receiveId)) window.viewReceiveDetails(receiveId, receiveName);
            return;
        }

        var subRow = el.closest('[data-submission-id]');
        if (subRow && typeof window.viewSubmissionDetails === 'function') {
            var subId = parseInt(subRow.getAttribute('data-submission-id'), 10);
            if (!Number.isNaN(subId)) window.viewSubmissionDetails(subId);
            return;
        }

        var ambiguousRow = el.closest('[data-ambiguous-submission-id]');
        if (ambiguousRow && typeof window.viewAmbiguousSubmission === 'function') {
            var ambiguousId = parseInt(ambiguousRow.getAttribute('data-ambiguous-submission-id'), 10);
            if (!Number.isNaN(ambiguousId)) window.viewAmbiguousSubmission(ambiguousId);
        }
    }

    function onDashboardKeydown(event) {
        if (event.key !== 'Enter' && event.key !== ' ') return;
        var el = clickTargetEl(event);
        var recentToggle = el && el.closest('#recent-submissions-toggle');
        if (!recentToggle) return;
        event.preventDefault();
        toggleRecentSubmissionsPanel();
    }

    function init() {
        bindTabletTypeSelector();
        document.addEventListener('click', onDashboardClick);
        document.addEventListener('keydown', onDashboardKeydown);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
