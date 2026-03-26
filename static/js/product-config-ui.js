/**
 * Product configuration page UI delegation for top-level controls.
 */
(function () {
    'use strict';

    document.addEventListener('DOMContentLoaded', function () {
        document.addEventListener('click', function (event) {
            var tabButton = event.target.closest('[data-config-tab]');
            if (!tabButton || typeof window.switchTab !== 'function') return;
            event.preventDefault();
            window.switchTab(tabButton.getAttribute('data-config-tab'));
        });

        document.addEventListener('change', function (event) {
            if (!event.target.classList.contains('js-product-type-radio')) return;
            if (typeof window.toggleProductTypeFields === 'function') {
                window.toggleProductTypeFields();
            }
        });
    });
})();
