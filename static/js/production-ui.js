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
        var combinedProduct = document.getElementById('combined_product');
        if (combinedProduct && typeof window.convertToTwoLevelDropdownByDataAttr === 'function') {
            window.convertToTwoLevelDropdownByDataAttr(combinedProduct, 'data-category');
        }
        var blisterProduct = document.getElementById('blister_product');
        if (blisterProduct && typeof window.convertToTwoLevelDropdownByDataAttr === 'function') {
            window.convertToTwoLevelDropdownByDataAttr(blisterProduct, 'data-category');
        }

        document.addEventListener('click', function (event) {
            var toggle = event.target.closest('[data-production-form]');
            if (!toggle || typeof window.switchForm !== 'function') return;
            event.preventDefault();
            window.switchForm(toggle.getAttribute('data-production-form'));
        });
    });
})();
