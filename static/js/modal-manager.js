/**
 * Modal Manager - Reusable modal components
 * Handles PO Details Modal and Receive Details Modal.
 * Uses apiCall with requestKey to cancel previous fetch when reopening.
 */

function escapeHtml(s) {
    if (s == null) return '';
    const t = String(s);
    return t
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

/**
 * View PO Details Modal
 * Shows purchase order details with line items and submissions
 */
async function viewPODetailsModal(poId, poNumber) {
    if (typeof abortPreviousRequest === 'function') abortPreviousRequest('po-details');
    try {
        const data = await apiCall(`/api/po/${poId}/details`, { requestKey: 'po-details' });
        const safePo = escapeHtml(poNumber);
        const parentBtn = data.parent_po
            ? `<button onclick="closePODetailsModal(); setTimeout(() => viewPODetailsModal(${data.parent_po.id}, '${escapeHtml(data.parent_po.po_number)}'), 100);" class="text-sm bg-white bg-opacity-20 hover:bg-opacity-30 px-3 py-1 rounded transition-all">← Parent PO: ${escapeHtml(data.parent_po.po_number)}</button>`
            : '';
        const oversBtn = data.overs_po
            ? `<button onclick="closePODetailsModal(); setTimeout(() => viewPODetailsModal(${data.overs_po.id}, '${escapeHtml(data.overs_po.po_number)}'), 100);" class="text-sm bg-white bg-opacity-20 hover:bg-opacity-30 px-3 py-1 rounded transition-all ml-2">Overs PO: ${escapeHtml(data.overs_po.po_number)} →</button>`
            : '';
        const rows = (data.po_lines || []).map(function (line) {
            const name = escapeHtml(line.line_item_name || 'N/A');
            const ord = Number(line.quantity_ordered) || 0;
            const good = Number(line.good_count) || 0;
            const dmg = Number(line.damaged_count) || 0;
            const rem = ord - good - dmg;
            return '<tr><td class="px-4 py-2">' + name + '</td><td class="px-4 py-2">' + ord.toLocaleString() + '</td><td class="px-4 py-2 text-green-600">' + good.toLocaleString() + '</td><td class="px-4 py-2 text-red-600">' + dmg.toLocaleString() + '</td><td class="px-4 py-2">' + rem.toLocaleString() + '</td></tr>';
        }).join('');
        const modalHTML =
            '<div class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50" onclick="closePODetailsModal(event)">' +
            '<div class="bg-white rounded-lg shadow-xl max-w-4xl w-full mx-4 max-h-[90vh] overflow-y-auto" onclick="event.stopPropagation()">' +
            '<div class="bg-gradient-to-r from-blue-600 to-indigo-600 text-white p-6 rounded-t-lg sticky top-0 z-10">' +
            '<div class="flex justify-between items-start"><div><h2 class="text-2xl font-bold mb-2">PO ' + safePo + '</h2>' + parentBtn + ' ' + oversBtn + '</div>' +
            '<button onclick="closePODetailsModal()" class="text-white hover:text-gray-200 text-2xl font-bold">×</button></div></div>' +
            '<div class="p-6"><h3 class="text-lg font-semibold mb-4">Line Items</h3>' +
            '<table class="min-w-full divide-y divide-gray-200 mb-6"><thead class="bg-gray-50"><tr><th class="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Product</th><th class="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Ordered</th><th class="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Good</th><th class="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Damaged</th><th class="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Remaining</th></tr></thead><tbody class="divide-y divide-gray-200">' + rows + '</tbody></table>' +
            '<div class="flex justify-end"><button onclick="closePODetailsModal()" class="btn-secondary">Close</button></div></div></div></div>';
        const modalDiv = document.createElement('div');
        modalDiv.id = 'po-details-modal';
        modalDiv.innerHTML = modalHTML;
        (document.getElementById('po-details-modal-container') || document.body).appendChild(modalDiv);
    } catch (error) {
        if (error.name === 'AbortError') return;
        console.error('Error loading PO details:', error);
        alert('Failed to load PO details. Please try again.');
    }
}

/**
 * Close PO Details Modal
 */
function closePODetailsModal(event) {
    if (event && event.target !== event.currentTarget) return;
    const modal = document.getElementById('po-details-modal');
    if (modal) modal.remove();
}

/**
 * View Receive Details Modal
 * Shows receiving record with boxes and bags
 */
async function viewReceiveDetailsModal(receiveId, receiveName) {
    if (typeof abortPreviousRequest === 'function') abortPreviousRequest('receive-details');
    try {
        const data = await apiCall(`/api/receiving/${receiveId}/details`, { requestKey: 'receive-details' });
        const safeName = escapeHtml(receiveName);
        const boxesHtml = (data.boxes || []).map(function (box) {
            const bagLines = (box.bags || []).map(function (bag) {
                return '<div class="text-sm">Bag #' + escapeHtml(String(bag.bag_number)) + ' - ' + escapeHtml(String(bag.count)) + ' tablets</div>';
            }).join('');
            return '<div class="border rounded-lg p-4"><h4 class="font-semibold">Box #' + escapeHtml(String(box.box_number)) + '</h4><div class="mt-2 space-y-1">' + bagLines + '</div></div>';
        }).join('');
        const modalHTML =
            '<div class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50" onclick="closeReceiveDetailsModal(event)">' +
            '<div class="bg-white rounded-lg shadow-xl max-w-4xl w-full mx-4 max-h-[90vh] overflow-y-auto" onclick="event.stopPropagation()">' +
            '<div class="bg-gradient-to-r from-green-600 to-teal-600 text-white p-6 rounded-t-lg sticky top-0 z-10">' +
            '<div class="flex justify-between items-start"><h2 class="text-2xl font-bold">' + safeName + '</h2>' +
            '<button onclick="closeReceiveDetailsModal()" class="text-white hover:text-gray-200 text-2xl font-bold">×</button></div></div>' +
            '<div class="p-6"><h3 class="text-lg font-semibold mb-4">Boxes and Bags</h3><div class="space-y-4">' + boxesHtml + '</div>' +
            '<div class="flex justify-end mt-6"><button onclick="closeReceiveDetailsModal()" class="btn-secondary">Close</button></div></div></div></div>';
        const modalDiv = document.createElement('div');
        modalDiv.id = 'receive-details-modal';
        modalDiv.innerHTML = modalHTML;
        document.body.appendChild(modalDiv);
    } catch (error) {
        if (error.name === 'AbortError') return;
        console.error('Error loading receive details:', error);
        alert('Failed to load receive details. Please try again.');
    }
}

/**
 * Close Receive Details Modal
 */
function closeReceiveDetailsModal(event) {
    if (event && event.target !== event.currentTarget) return;
    const modal = document.getElementById('receive-details-modal');
    if (modal) modal.remove();
}

