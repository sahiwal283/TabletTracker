/**
 * Modal Manager - Reusable modal components
 * Handles PO Details Modal and Receive Details Modal
 */

/**
 * View PO Details Modal
 * Shows purchase order details with line items and submissions
 */
async function viewPODetailsModal(poId, poNumber) {
    try {
        const response = await fetch(`/api/po/${poId}/details`);
        if (!response.ok) throw new Error('Failed to fetch PO details');
        
        const data = await response.json();
        
        // Build modal HTML
        const modalHTML = `
            <div class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50" onclick="closePODetailsModal(event)">
                <div class="bg-white rounded-lg shadow-xl max-w-4xl w-full mx-4 max-h-[90vh] overflow-y-auto" onclick="event.stopPropagation()">
                    <div class="bg-gradient-to-r from-blue-600 to-indigo-600 text-white p-6 rounded-t-lg sticky top-0 z-10">
                        <div class="flex justify-between items-start">
                            <div>
                                <h2 class="text-2xl font-bold mb-2">PO ${poNumber}</h2>
                                ${data.parent_po ? `
                                    <button onclick="closePODetailsModal(); setTimeout(() => viewPODetailsModal(${data.parent_po.id}, '${data.parent_po.po_number}'), 100);" 
                                            class="text-sm bg-white bg-opacity-20 hover:bg-opacity-30 px-3 py-1 rounded transition-all">
                                        ← Parent PO: ${data.parent_po.po_number}
                                    </button>
                                ` : ''}
                                ${data.overs_po ? `
                                    <button onclick="closePODetailsModal(); setTimeout(() => viewPODetailsModal(${data.overs_po.id}, '${data.overs_po.po_number}'), 100);" 
                                            class="text-sm bg-white bg-opacity-20 hover:bg-opacity-30 px-3 py-1 rounded transition-all ml-2">
                                        Overs PO: ${data.overs_po.po_number} →
                                    </button>
                                ` : ''}
                            </div>
                            <button onclick="closePODetailsModal()" class="text-white hover:text-gray-200 text-2xl font-bold">
                                ×
                            </button>
                        </div>
                    </div>
                    
                    <div class="p-6">
                        <!-- PO Lines Table -->
                        <h3 class="text-lg font-semibold mb-4">Line Items</h3>
                        <table class="min-w-full divide-y divide-gray-200 mb-6">
                            <thead class="bg-gray-50">
                                <tr>
                                    <th class="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Product</th>
                                    <th class="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Ordered</th>
                                    <th class="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Good</th>
                                    <th class="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Damaged</th>
                                    <th class="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Remaining</th>
                                </tr>
                            </thead>
                            <tbody class="divide-y divide-gray-200">
                                ${data.po_lines.map(line => `
                                    <tr>
                                        <td class="px-4 py-2">${line.line_item_name || 'N/A'}</td>
                                        <td class="px-4 py-2">${line.quantity_ordered.toLocaleString()}</td>
                                        <td class="px-4 py-2 text-green-600">${line.good_count.toLocaleString()}</td>
                                        <td class="px-4 py-2 text-red-600">${line.damaged_count.toLocaleString()}</td>
                                        <td class="px-4 py-2">${(line.quantity_ordered - line.good_count - line.damaged_count).toLocaleString()}</td>
                                    </tr>
                                `).join('')}
                            </tbody>
                        </table>
                        
                        <div class="flex justify-end">
                            <button onclick="closePODetailsModal()" class="btn-secondary">Close</button>
                        </div>
                    </div>
                </div>
            </div>
        `;
        
        // Insert modal into DOM
        const modalDiv = document.createElement('div');
        modalDiv.id = 'po-details-modal';
        modalDiv.innerHTML = modalHTML;
        
        const modalContainer = document.getElementById('po-details-modal-container') || document.body;
        modalContainer.appendChild(modalDiv);
        
    } catch (error) {
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
    try {
        const response = await fetch(`/api/receiving/${receiveId}/details`);
        if (!response.ok) throw new Error('Failed to fetch receive details');
        
        const data = await response.json();
        
        // Build modal HTML
        const modalHTML = `
            <div class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50" onclick="closeReceiveDetailsModal(event)">
                <div class="bg-white rounded-lg shadow-xl max-w-4xl w-full mx-4 max-h-[90vh] overflow-y-auto" onclick="event.stopPropagation()">
                    <div class="bg-gradient-to-r from-green-600 to-teal-600 text-white p-6 rounded-t-lg sticky top-0 z-10">
                        <div class="flex justify-between items-start">
                            <h2 class="text-2xl font-bold">${receiveName}</h2>
                            <button onclick="closeReceiveDetailsModal()" class="text-white hover:text-gray-200 text-2xl font-bold">
                                ×
                            </button>
                        </div>
                    </div>
                    
                    <div class="p-6">
                        <!-- Boxes and Bags -->
                        <h3 class="text-lg font-semibold mb-4">Boxes and Bags</h3>
                        <div class="space-y-4">
                            ${data.boxes.map(box => `
                                <div class="border rounded-lg p-4">
                                    <h4 class="font-semibold">Box #${box.box_number}</h4>
                                    <div class="mt-2 space-y-1">
                                        ${box.bags.map(bag => `
                                            <div class="text-sm">Bag #${bag.bag_number} - ${bag.count} tablets</div>
                                        `).join('')}
                                    </div>
                                </div>
                            `).join('')}
                        </div>
                        
                        <div class="flex justify-end mt-6">
                            <button onclick="closeReceiveDetailsModal()" class="btn-secondary">Close</button>
                        </div>
                    </div>
                </div>
            </div>
        `;
        
        // Insert modal into DOM
        const modalDiv = document.createElement('div');
        modalDiv.id = 'receive-details-modal';
        modalDiv.innerHTML = modalHTML;
        document.body.appendChild(modalDiv);
        
    } catch (error) {
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

