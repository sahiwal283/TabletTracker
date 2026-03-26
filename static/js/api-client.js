/**
 * API Client - Centralized API call handling
 * Provides consistent error handling, AbortController support, and request deduplication
 */

const _requestAbortControllers = {};
let _notificationOffset = 0;

function escapeHtml(value) {
    if (value == null) return '';
    return String(value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

/**
 * Abort any in-flight request for the given key (if any). Call before starting a new request with the same key.
 * @param {string} requestKey - Key used when starting the request (e.g. 'po-summary', 'receives-list')
 */
function abortPreviousRequest(requestKey) {
    if (_requestAbortControllers[requestKey]) {
        try { _requestAbortControllers[requestKey].abort(); } catch (_) { /* ignore */ }
        _requestAbortControllers[requestKey] = null;
    }
}

/**
 * Make an API call with error handling and optional abort support.
 * @param {string} url - The API endpoint
 * @param {object} options - Fetch options. Optional: signal (AbortSignal), requestKey (string; aborts previous call with same key)
 * @returns {Promise} Response data or throws error (including AbortError if cancelled)
 */
async function apiCall(url, options = {}) {
    const requestKey = options.requestKey;
    if (requestKey) {
        abortPreviousRequest(requestKey);
        const controller = new AbortController();
        _requestAbortControllers[requestKey] = controller;
        options.signal = controller.signal;
        delete options.requestKey;
    }
    try {
        const response = await fetch(url, {
            headers: {
                'Content-Type': 'application/json',
                ...options.headers
            },
            ...options
        });
        if (requestKey) _requestAbortControllers[requestKey] = null;

        if (!response.ok) {
            const error = await response.json().catch(() => ({ error: 'Request failed' }));
            throw new Error(error.error || `HTTP ${response.status}`);
        }

        return await response.json();
    } catch (error) {
        if (requestKey) _requestAbortControllers[requestKey] = null;
        if (error.name === 'AbortError') throw error;
        console.error(`API call failed: ${url}`, error);
        throw error;
    }
}

/**
 * Show loading indicator
 */
function showLoading(message = 'Loading...') {
    hideLoading();
    const loadingDiv = document.createElement('div');
    loadingDiv.id = 'loading-indicator';
    loadingDiv.className = 'fixed inset-0 bg-black bg-opacity-40 backdrop-blur-sm flex items-center justify-center z-50';
    loadingDiv.setAttribute('role', 'status');
    loadingDiv.setAttribute('aria-live', 'polite');
    loadingDiv.innerHTML = `
        <div class="bg-white rounded-2xl p-6 flex items-center space-x-3 shadow-2xl border border-slate-100">
            <div class="animate-spin rounded-full h-6 w-6 border-b-2 border-blue-600"></div>
            <span class="font-medium text-slate-700">${escapeHtml(message)}</span>
        </div>
    `;
    document.body.appendChild(loadingDiv);
}

/**
 * Hide loading indicator
 */
function hideLoading() {
    const loading = document.getElementById('loading-indicator');
    if (loading) loading.remove();
}

/**
 * Show success message
 */
function showSuccess(message) {
    showNotification(message, 'success');
}

/**
 * Show error message
 */
function showError(message) {
    showNotification(message, 'error');
}

/**
 * Show notification
 */
function showNotification(message, type = 'info') {
    const bgColors = {
        success: 'bg-emerald-600',
        error: 'bg-rose-600',
        info: 'bg-sky-600',
        warning: 'bg-amber-500'
    };
    
    const notif = document.createElement('div');
    notif.className = `fixed right-4 ${bgColors[type]} text-white px-5 py-3 rounded-xl shadow-xl z-50 transition-all duration-300`;
    notif.style.top = `${16 + _notificationOffset}px`;
    notif.setAttribute('role', type === 'error' ? 'alert' : 'status');
    notif.setAttribute('aria-live', type === 'error' ? 'assertive' : 'polite');
    notif.textContent = message;
    document.body.appendChild(notif);
    _notificationOffset += 64;
    
    setTimeout(() => {
        notif.style.opacity = '0';
        notif.style.transform = 'translateY(-6px)';
        setTimeout(() => {
            notif.remove();
            _notificationOffset = Math.max(0, _notificationOffset - 64);
        }, 280);
    }, 3000);
}

