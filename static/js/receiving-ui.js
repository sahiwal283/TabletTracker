/**
 * Receiving page UI delegation for primary controls.
 */
(function () {
    'use strict';

    document.addEventListener('DOMContentLoaded', function () {
        var addButton = document.getElementById('open-add-receives-btn');
        if (addButton) {
            addButton.addEventListener('click', function () {
                if (typeof window.openAddReceivesModal === 'function') {
                    window.openAddReceivesModal();
                }
            });
        }

        document.addEventListener('click', function (event) {
            var tabButton = event.target.closest('[data-receiving-tab]');
            if (!tabButton || typeof window.switchReceivingTab !== 'function') return;
            event.preventDefault();
            window.switchReceivingTab(tabButton.getAttribute('data-receiving-tab'));
        });
    });
})();
