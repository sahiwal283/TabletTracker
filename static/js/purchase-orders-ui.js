/**
 * Purchase orders page UI delegation.
 */
(function () {
    'use strict';

    function findRowData(element) {
        var row = element.closest('tr[data-po-id]');
        if (!row) return null;
        return {
            id: parseInt(row.getAttribute('data-po-id'), 10),
            number: row.getAttribute('data-po-number') || ''
        };
    }

    document.addEventListener('DOMContentLoaded', function () {
        document.addEventListener('click', function (event) {
            var filterButton = event.target.closest('[data-po-filter]');
            if (filterButton && typeof window.filterPOs === 'function') {
                event.preventDefault();
                window.filterPOs(filterButton.getAttribute('data-po-filter'));
                return;
            }

            var deleteButton = event.target.closest('[data-delete-po-id]');
            if (deleteButton && typeof window.deletePO === 'function') {
                event.stopPropagation();
                var deleteId = parseInt(deleteButton.getAttribute('data-delete-po-id'), 10);
                var deleteNumber = deleteButton.getAttribute('data-delete-po-number') || '';
                if (!Number.isNaN(deleteId)) window.deletePO(deleteId, deleteNumber);
                return;
            }

            var detailsTrigger = event.target.closest('.js-po-details-trigger');
            if (detailsTrigger && typeof window.viewPODetailsModal === 'function') {
                var poData = findRowData(detailsTrigger);
                if (poData && !Number.isNaN(poData.id)) {
                    window.viewPODetailsModal(poData.id, poData.number);
                }
            }
        });
    });
})();
