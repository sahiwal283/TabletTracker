import requests
import json
from datetime import datetime, timedelta
from config import Config

class ZohoInventoryAPI:
    def __init__(self):
        self.base_url = 'https://www.zohoapis.com/inventory/v1'
        self.organization_id = Config.ZOHO_ORGANIZATION_ID
        self.access_token = None
        self.token_expires_at = None
        
    def get_access_token(self):
        """Get a fresh access token using refresh token"""
        if self.access_token and self.token_expires_at and datetime.now() < self.token_expires_at:
            return self.access_token
            
        url = 'https://accounts.zoho.com/oauth/v2/token'
        data = {
            'refresh_token': Config.ZOHO_REFRESH_TOKEN,
            'client_id': Config.ZOHO_CLIENT_ID,
            'client_secret': Config.ZOHO_CLIENT_SECRET,
            'grant_type': 'refresh_token'
        }
        
        # Validate credentials are present
        if not Config.ZOHO_CLIENT_ID or not Config.ZOHO_CLIENT_SECRET or not Config.ZOHO_REFRESH_TOKEN:
            error_msg = "Zoho API credentials not configured. Please set ZOHO_CLIENT_ID, ZOHO_CLIENT_SECRET, and ZOHO_REFRESH_TOKEN in .env file."
            print(error_msg)
            raise ValueError(error_msg)
        
        try:
            response = requests.post(url, data=data)
            response.raise_for_status()
            token_data = response.json()
            
            # Check if access_token is in response
            if 'access_token' not in token_data:
                error_details = token_data.get('error', 'Unknown error')
                error_msg = f"Zoho API did not return access_token. Response: {error_details}"
                print(error_msg)
                raise ValueError(error_msg)
            
            self.access_token = token_data['access_token']
            # Tokens typically expire in 1 hour, set expiry a bit earlier for safety
            self.token_expires_at = datetime.now() + timedelta(seconds=token_data.get('expires_in', 3600) - 300)
            
            return self.access_token
            
        except requests.exceptions.RequestException as e:
            print(f"Error getting access token from Zoho: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"Response body: {e.response.text}")
            raise
    
    def make_request(self, endpoint, method='GET', data=None, extra_params=None):
        """Make authenticated request to Zoho Inventory API"""
        token = self.get_access_token()
        if not token:
            return None
            
        url = f"{self.base_url}/{endpoint}"
        headers = {
            'Authorization': f'Zoho-oauthtoken {token}',
            'Content-Type': 'application/json'
        }
        
        params = {'organization_id': self.organization_id}
        if extra_params:
            params.update(extra_params)
        
        try:
            if method == 'GET':
                response = requests.get(url, headers=headers, params=params)
            elif method == 'POST':
                response = requests.post(url, headers=headers, params=params, json=data)
            elif method == 'PUT':
                response = requests.put(url, headers=headers, params=params, json=data)
            
            print(f"Request URL: {response.url}")
            print(f"Response Status: {response.status_code}")
            
            if response.status_code != 200:
                print(f"Error Response Body: {response.text}")
            
            response.raise_for_status()
            return response.json()
            
        except requests.exceptions.RequestException as e:
            print(f"Error making Zoho API request: {e}")
            return None
    
    def get_purchase_orders(self, status='all', per_page=200):
        """Get purchase orders from Zoho Inventory"""
        endpoint = 'purchaseorders'
        params = {'per_page': per_page}
        
        if status != 'all':
            params['status'] = status
            
        return self.make_request(endpoint, extra_params=params)
    
    def get_purchase_order_details(self, po_id):
        """Get detailed information for a specific PO"""
        endpoint = f'purchaseorders/{po_id}'
        return self.make_request(endpoint)
    
    def get_items(self, per_page=200):
        """Get all inventory items"""
        endpoint = 'items'
        params = {'per_page': per_page}
        return self.make_request(endpoint, extra_params=params)
    
    def sync_tablet_pos_to_db(self, db_conn):
        """Sync ONLY tablet POs from Zoho to local database"""
        # Get all POs (open, closed, draft, etc.)
        pos_data = self.get_purchase_orders(status='all')
        
        if not pos_data or 'purchaseorders' not in pos_data:
            return False, "Failed to fetch POs from Zoho"
        
        synced_count = 0
        skipped_count = 0
        
        for po in pos_data['purchaseorders']:
            # Check if it's a tablet PO AND not closed
            is_tablet_po = False
            
            # Check the tablets custom field (the one you just marked in Zoho)
            if po.get('cf_tablets_unformatted') in [True, 'true', 'True', 1, '1']:
                is_tablet_po = True
                print(f"✅ Tablet PO found: {po['purchaseorder_number']} (cf_tablets_unformatted = {po.get('cf_tablets_unformatted')})")
            elif po.get('cf_tablets') in [True, 'true', 'True', 1, '1']:
                is_tablet_po = True  
                print(f"✅ Tablet PO found: {po['purchaseorder_number']} (cf_tablets = {po.get('cf_tablets')})")
            
            if not is_tablet_po:
                skipped_count += 1
                print(f"⏭️  Skipping non-tablet PO: {po['purchaseorder_number']} (tablets field not marked)")
                continue
                
            # We'll sync closed POs too, but mark them properly for separate display
                
            # Check if PO already exists - get current closed status too
            existing = db_conn.execute(
                'SELECT id, closed FROM purchase_orders WHERE zoho_po_id = ?', 
                (po['purchaseorder_id'],)
            ).fetchone()
            
            # Map Zoho status - check multiple status fields 
            zoho_status = po.get('status', '').upper()
            delivery_status = po.get('delivery_status', '').upper()
            po_reference = po.get('reference_number', '')
            
            # Check for billing-related fields (CLOSED in UI = BILL CREATED)
            billing_status = po.get('billing_status', '').upper()
            billed_status = po.get('billed_status', '').upper()
            is_billed = po.get('is_billed', False)
            bill_count = po.get('bills_count', 0)
            
            # Check for "received" tracking fields (when you mark as received in Zoho)
            received_date = po.get('received_date', '') or po.get('delivery_date', '') or po.get('actual_delivery_date', '')
            is_received = po.get('is_received', False) or po.get('delivered', False)
            receives_count = po.get('receives_count', 0) or po.get('receipts_count', 0)
            
            # Check your custom status field 
            custom_status = po.get('cf_status', '') or po.get('cf_status_unformatted', '')
            
            # Debug all relevant fields
            print(f"PO {po['purchaseorder_number']}: status='{zoho_status}', billing_status='{billing_status}', is_billed={is_billed}, bills_count={bill_count}")
            print(f"  received_date='{received_date}', is_received={is_received}, receives_count={receives_count}, custom_status='{custom_status}'")
            
            # Check for the REAL closed status fields from debug output
            order_status = po.get('order_status', '').upper()
            current_sub_status = po.get('current_sub_status', '').upper()
            billed_status = po.get('billed_status', '').upper()
            
            # Also check the main status field (it might be "closed" directly)
            main_status = po.get('status', '').upper()
            
            # CLOSED in Zoho UI can be indicated by:
            # 1. order_status = "CLOSED"
            # 2. current_sub_status = "CLOSED"
            # 3. billed_status = "BILLED"
            # 4. main status = "CLOSED"
            # 5. Any status containing "CLOSED" or "CLOSE"
            is_closed = (order_status == 'CLOSED' or 
                        current_sub_status == 'CLOSED' or
                        billed_status == 'BILLED' or
                        main_status == 'CLOSED' or
                        'CLOSED' in main_status or
                        'CLOSED' in order_status or
                        'CLOSED' in current_sub_status or
                        (is_billed and bill_count > 0))
            
            # Additional check: if status contains "close" or "closed" anywhere
            if not is_closed:
                status_str = f"{main_status} {order_status} {current_sub_status} {billed_status}".upper()
                if 'CLOSE' in status_str or 'CLOSED' in status_str:
                    is_closed = True
            
            print(f"PO {po['purchaseorder_number']}: status='{main_status}', order_status='{order_status}', current_sub_status='{current_sub_status}', billed_status='{billed_status}'")
            print(f"Final closed determination: {is_closed}")
            
            # Get PO creation date from Zoho (they use 'date' field for PO date)
            po_date = po.get('date', '') or po.get('created_time', '') or po.get('purchaseorder_date', '')
            
            if existing:
                # Update existing PO with proper status and tablet type
                print(f"Updating existing PO {po['purchaseorder_number']}: zoho_status='{zoho_status}', closed={is_closed}")
                # Update created_at only if we have a date from Zoho and current created_at is different
                if po_date and po_date != existing.get('created_at', '')[:10]:
                    db_conn.execute('''
                        UPDATE purchase_orders 
                        SET po_number = ?, zoho_status = ?, closed = ?, created_at = ?, updated_at = CURRENT_TIMESTAMP
                        WHERE zoho_po_id = ?
                    ''', (po['purchaseorder_number'], zoho_status, is_closed, po_date, po['purchaseorder_id']))
                else:
                    # Always update closed status - this is critical for preventing assignments
                    db_conn.execute('''
                        UPDATE purchase_orders 
                        SET po_number = ?, zoho_status = ?, closed = ?, updated_at = CURRENT_TIMESTAMP
                        WHERE zoho_po_id = ?
                    ''', (po['purchaseorder_number'], zoho_status, is_closed, po['purchaseorder_id']))
                    print(f"✅ Updated PO {po['purchaseorder_number']}: closed={is_closed} (was: {existing.get('closed', False)})")
                po_id = existing['id']
            else:
                # Insert new PO with proper status and creation date
                if po_date:
                    cursor = db_conn.execute('''
                        INSERT INTO purchase_orders (po_number, zoho_po_id, zoho_status, closed, created_at)
                        VALUES (?, ?, ?, ?, ?)
                    ''', (po['purchaseorder_number'], po['purchaseorder_id'], 
                          zoho_status, is_closed, po_date))
                else:
                    cursor = db_conn.execute('''
                        INSERT INTO purchase_orders (po_number, zoho_po_id, zoho_status, closed)
                        VALUES (?, ?, ?, ?)
                    ''', (po['purchaseorder_number'], po['purchaseorder_id'], 
                          zoho_status, is_closed))
                po_id = cursor.lastrowid
            
            # Determine actual tablet type from line items  
            tablet_types_found = []
            
            # Sync line items
            po_details = self.get_purchase_order_details(po['purchaseorder_id'])
            if po_details and 'purchaseorder' in po_details:
                for line in po_details['purchaseorder'].get('line_items', []):
                    # Check if line item already exists
                    existing_line = db_conn.execute(
                        'SELECT id FROM po_lines WHERE po_id = ? AND inventory_item_id = ?',
                        (po_id, line['item_id'])
                    ).fetchone()
                    
                    if existing_line:
                        # Update existing line
                        db_conn.execute('''
                            UPDATE po_lines 
                            SET line_item_name = ?, quantity_ordered = ?
                            WHERE id = ?
                        ''', (line['name'], line['quantity'], existing_line['id']))
                    else:
                        # Insert new line
                        db_conn.execute('''
                            INSERT INTO po_lines 
                            (po_id, po_number, inventory_item_id, line_item_name, quantity_ordered)
                            VALUES (?, ?, ?, ?, ?)
                        ''', (po_id, po['purchaseorder_number'], line['item_id'], 
                              line['name'], line['quantity']))
                    
                    # Extract tablet type using inventory_item_id from configured tablet types
                    item_id = line.get('item_id', '')
                    matched_this_line = False
                    
                    if item_id:
                        # Look up the tablet type by inventory_item_id
                        tablet_type_match = db_conn.execute('''
                            SELECT tablet_type_name 
                            FROM tablet_types 
                            WHERE inventory_item_id = ?
                        ''', (item_id,)).fetchone()
                        
                        if tablet_type_match:
                            tablet_types_found.append(tablet_type_match['tablet_type_name'])
                            matched_this_line = True
                            print(f"✅ Matched line item '{line['name']}' (ID: {item_id}) to tablet type: {tablet_type_match['tablet_type_name']}")
                        else:
                            print(f"⚠️  Line item '{line['name']}' (ID: {item_id}) has no matching tablet type in config")
                    
                    # Fallback: Extract tablet type from line item name if no ID match for this specific line
                    if not matched_this_line:
                        item_name = line.get('name', '').lower()
                        if 'fix' in item_name:
                            if 'energy' in item_name:
                                tablet_types_found.append('FIX Energy')
                            elif 'focus' in item_name:
                                tablet_types_found.append('FIX Focus')
                            elif 'relax' in item_name:
                                tablet_types_found.append('FIX Relax')
                        elif '7oh' in item_name or '7-oh' in item_name:
                            if 'xl' in item_name:
                                tablet_types_found.append('XL 7OH')
                            else:
                                tablet_types_found.append('7OH')
                        elif 'pseudo' in item_name:
                            if 'xl' in item_name:
                                tablet_types_found.append('XL Pseudo')  
                            else:
                                tablet_types_found.append('Pseudo')
                        elif 'hybrid' in item_name:
                            if 'xl' in item_name:
                                tablet_types_found.append('XL Hybrid')
                            else:
                                tablet_types_found.append('Hybrid')
            
            # Auto-progress internal status based on Zoho actions
            current_internal = db_conn.execute(
                'SELECT internal_status FROM purchase_orders WHERE id = ?', 
                (po_id,)
            ).fetchone()
            
            current_status = current_internal['internal_status'] if current_internal else 'Draft'
            new_internal_status = current_status
            
            # Set internal status based on Zoho workflow progression
            if zoho_status == 'DRAFT':
                new_internal_status = 'Draft'
            elif zoho_status == 'ISSUED':
                new_internal_status = 'Issued'
            elif zoho_status == 'RECEIVED':
                new_internal_status = 'Received' 
                print(f"Auto-progressed {po['purchaseorder_number']} to Received (Zoho status={zoho_status})")
            elif zoho_status == 'PARTIALLY_RECEIVED':
                new_internal_status = 'Partially Received'
                print(f"Detected partial receive for {po['purchaseorder_number']} - waiting for additional shipments")
            elif receives_count > 0 or received_date or is_received:
                new_internal_status = 'Received' 
                print(f"Auto-progressed {po['purchaseorder_number']} to Received (receives_count={receives_count}, received_date={received_date})")
            
            print(f"Set internal status for {po['purchaseorder_number']}: {current_status} → {new_internal_status}")
            
            # Update PO with inferred tablet type and internal status
            if tablet_types_found:
                tablet_type = ', '.join(set(tablet_types_found))
                db_conn.execute('''
                    UPDATE purchase_orders 
                    SET tablet_type = ?, internal_status = ?
                    WHERE id = ?
                ''', (tablet_type, new_internal_status, po_id))
            else:
                db_conn.execute('''
                    UPDATE purchase_orders 
                    SET internal_status = ?
                    WHERE id = ?
                ''', (new_internal_status, po_id))
            
            synced_count += 1
        
        # Update remaining quantities for all POs after sync
        db_conn.execute('''
            UPDATE purchase_orders 
            SET remaining_quantity = ordered_quantity - current_good_count - current_damaged_count,
                ordered_quantity = (
                    SELECT COALESCE(SUM(quantity_ordered), 0) 
                    FROM po_lines 
                    WHERE po_id = purchase_orders.id
                )
            WHERE id IN (
                SELECT DISTINCT po_id FROM po_lines
            )
        ''')
        
        db_conn.commit()
        return True, f"✅ Synced {synced_count} tablet POs, skipped {skipped_count} non-tablet POs"

# Global instance
zoho_api = ZohoInventoryAPI()
