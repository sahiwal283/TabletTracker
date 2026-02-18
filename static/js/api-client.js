/**
 * API Client - Centralized API call handling
 * Provides consistent error handling, AbortController support, and request deduplication
 */

const _requestAbortControllers = {};

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
    const loadingDiv = document.createElement('div');
    loadingDiv.id = 'loading-indicator';
    loadingDiv.className = 'fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50';
    loadingDiv.innerHTML = `
        <div class="bg-white rounded-lg p-6 flex items-center space-x-3">
            <div class="animate-spin rounded-full h-6 w-6 border-b-2 border-blue-600"></div>
            <span>${message}</span>
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
        success: 'bg-green-500',
        error: 'bg-red-500',
        info: 'bg-blue-500',
        warning: 'bg-yellow-500'
    };
    
    const notif = document.createElement('div');
    notif.className = `fixed top-4 right-4 ${bgColors[type]} text-white px-6 py-3 rounded-lg shadow-lg z-50 animate-fade-in`;
    notif.textContent = message;
    document.body.appendChild(notif);
    
    setTimeout(() => {
        notif.style.opacity = '0';
        notif.style.transition = 'opacity 0.3s';
        setTimeout(() => notif.remove(), 300);
    }, 3000);
}

