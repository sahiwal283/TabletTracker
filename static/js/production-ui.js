/**
 * Production page UI delegation for form switching and dropdown setup.
 */
(function () {
    'use strict';

    document.addEventListener('DOMContentLoaded', function () {
        var machineProduct = document.getElementById('machine_product');
        if (machineProduct && typeof window.convertToTwoLevelDropdownByDataAttr === 'function') {
            window.convertToTwoLevelDropdownByDataAttr(machineProduct, 'data-category');
        }

        document.addEventListener('click', function (event) {
            var toggle = event.target.closest('[data-production-form]');
            if (!toggle || typeof window.switchForm !== 'function') return;
            event.preventDefault();
            window.switchForm(toggle.getAttribute('data-production-form'));
        });
    });
})();
