import requests
import json
import logging
from datetime import datetime, timedelta
from config import Config

logger = logging.getLogger(__name__)

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
            logger.error(error_msg)
            raise ValueError(error_msg)
        
        try:
            # Add timeout to prevent hanging (30 seconds)
            response = requests.post(url, data=data, timeout=30)
            response.raise_for_status()
            token_data = response.json()
            
            # Check if access_token is in response
            if 'access_token' not in token_data:
                error_details = token_data.get('error', 'Unknown error')
                error_msg = f"Zoho API did not return access_token. Response: {error_details}"
                logger.error(error_msg)
                raise ValueError(error_msg)
            
            self.access_token = token_data['access_token']
            # Tokens typically expire in 1 hour, set expiry a bit earlier for safety
            self.token_expires_at = datetime.now() + timedelta(seconds=token_data.get('expires_in', 3600) - 300)
            
            return self.access_token
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Error getting access token from Zoho: {e}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Response body: {e.response.text}")
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
            # Add timeout to prevent hanging (30 seconds)
            timeout = 30
            if method == 'GET':
                response = requests.get(url, headers=headers, params=params, timeout=timeout)
            elif method == 'POST':
                response = requests.post(url, headers=headers, params=params, json=data, timeout=timeout)
            elif method == 'PUT':
                response = requests.put(url, headers=headers, params=params, json=data, timeout=timeout)
            
            logger.debug(f"Request URL: {response.url}")
            logger.debug(f"Response Status: {response.status_code}")
            
            if response.status_code != 200:
                logger.error(f"Error Response Body: {response.text}")
            
            response.raise_for_status()
            return response.json()
            
        except requests.exceptions.Timeout as e:
            logger.error(f"Zoho API request timed out after {timeout} seconds: {e}")
            return None
        except requests.exceptions.RequestException as e:
            logger.error(f"Error making Zoho API request: {e}")
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
    
    def create_purchase_order(self, po_data):
        """Create a purchase order in Zoho Inventory"""
        endpoint = 'purchaseorders'
        return self.make_request(endpoint, method='POST', data=po_data)
    
    def create_purchase_receive(self, purchaseorder_id, line_items, date, notes=None, image_bytes=None, image_filename=None):
        """
        Create a purchase receive in Zoho Inventory.
        
        Args:
            purchaseorder_id: The Zoho purchase order ID
            line_items: List of dicts with 'item_id' and 'quantity'
            date: Date string in ISO format (YYYY-MM-DD)
            notes: Optional notes string
            image_bytes: Optional bytes of image to attach
            image_filename: Optional filename for the image
            
        Returns:
            Dict with receive data including 'purchasereceive_id', or None on error
        """
        endpoint = 'purchasereceives'
        
        # Build the receive data payload
        receive_data = {
            'purchaseorder_id': purchaseorder_id,
            'date': date,
            'line_items': line_items
        }
        
        if notes:
            receive_data['notes'] = notes
        
        # Create the purchase receive first
        result = self.make_request(endpoint, method='POST', data=receive_data)
        
        if not result:
            logger.error("Failed to create purchase receive - no response from API")
            return None
        
        # Check for errors in response
        if result.get('code') and result.get('code') != 0:
            error_msg = result.get('message', 'Unknown error')
            logger.error(f"Failed to create purchase receive: {error_msg}")
            return result
        
        # If we have an image to attach, upload it
        if image_bytes and image_filename and result.get('purchasereceive'):
            receive_id = result['purchasereceive'].get('purchasereceive_id')
            if receive_id:
                attach_result = self.attach_file_to_receive(receive_id, image_bytes, image_filename)
                if attach_result:
                    logger.info(f"Successfully attached image to purchase receive {receive_id}")
                else:
                    logger.warning(f"Failed to attach image to purchase receive {receive_id}")
        
        return result
    
    def attach_file_to_receive(self, receive_id, file_bytes, filename):
        """
        Attach a file to a purchase receive.
        
        Args:
            receive_id: The Zoho purchase receive ID
            file_bytes: Bytes of the file to attach
            filename: Filename for the attachment
            
        Returns:
            True if successful, False otherwise
        """
        token = self.get_access_token()
        if not token:
            return False
        
        url = f"{self.base_url}/purchasereceives/{receive_id}/attachment"
        headers = {
            'Authorization': f'Zoho-oauthtoken {token}'
            # Note: Don't set Content-Type for multipart/form-data, requests handles it
        }
        
        params = {'organization_id': self.organization_id}
        
        try:
            # Prepare the file for upload
            files = {
                'attachment': (filename, file_bytes, 'image/png')
            }
            
            response = requests.post(
                url,
                headers=headers,
                params=params,
                files=files,
                timeout=30
            )
            
            logger.debug(f"Attachment upload response status: {response.status_code}")
            
            if response.status_code in [200, 201]:
                return True
            else:
                logger.error(f"Failed to attach file: {response.status_code} - {response.text}")
                return False
                
        except requests.exceptions.Timeout as e:
            logger.error(f"Attachment upload timed out: {e}")
            return False
        except requests.exceptions.RequestException as e:
            logger.error(f"Error uploading attachment: {e}")
            return False
    
    def sync_tablet_pos_to_db(self, db_conn):
        """Sync ONLY tablet POs from Zoho to local database"""
        # Get all POs (open, closed, draft, etc.)
        pos_data = self.get_purchase_orders(status='all')
        
        if not pos_data:
            return False, "Failed to fetch POs from Zoho - API returned no data. Check Zoho API credentials and connection."
        
        if 'purchaseorders' not in pos_data:
            error_msg = pos_data.get('message', 'Unknown error') if isinstance(pos_data, dict) else 'Invalid response format'
            return False, f"Failed to fetch POs from Zoho: {error_msg}"
        
        synced_count = 0
        skipped_count = 0
        total_pos = len(pos_data.get('purchaseorders', []))
        logger.info(f"📊 Processing {total_pos} total POs from Zoho...")
        
        for idx, po in enumerate(pos_data['purchaseorders'], 1):
            if idx % 10 == 0:
                logger.debug(f"📊 Progress: {idx}/{total_pos} POs processed ({synced_count} synced, {skipped_count} skipped)")
            # Check if it's a tablet PO AND not closed
            is_tablet_po = False
            po_number = po.get('purchaseorder_number', '')
            is_overs_po = po_number.upper().endswith('-OVERS')
            
            # Check the tablets custom field (the one you just marked in Zoho)
            if po.get('cf_tablets_unformatted') in [True, 'true', 'True', 1, '1']:
                is_tablet_po = True
                logger.debug(f"✅ Tablet PO found: {po_number} (cf_tablets_unformatted = {po.get('cf_tablets_unformatted')})")
            elif po.get('cf_tablets') in [True, 'true', 'True', 1, '1']:
                is_tablet_po = True  
                logger.debug(f"✅ Tablet PO found: {po_number} (cf_tablets = {po.get('cf_tablets')})")
            
            # Also check if it's an overs PO (ends with -OVERS)
            if is_overs_po:
                is_tablet_po = True
                logger.debug(f"✅ Overs PO detected: {po_number}")
            
            if not is_tablet_po:
                skipped_count += 1
                logger.debug(f"⏭️  Skipping non-tablet PO: {po_number} (tablets field not marked)")
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
            logger.debug(f"PO {po['purchaseorder_number']}: status='{zoho_status}', billing_status='{billing_status}', is_billed={is_billed}, bills_count={bill_count}")
            logger.debug(f"  received_date='{received_date}', is_received={is_received}, receives_count={receives_count}, custom_status='{custom_status}'")
            
            # Check for the REAL closed status fields from debug output
            order_status = po.get('order_status', '').upper()
            current_sub_status = po.get('current_sub_status', '').upper()
            billed_status = po.get('billed_status', '').upper()
            
            # Also check the main status field (it might be "closed" directly)
            main_status = po.get('status', '').upper()
            
            # Check if PO is CANCELLED (separate from closed)
            is_cancelled = (order_status == 'CANCELLED' or 
                          order_status == 'CANCELED' or
                          current_sub_status == 'CANCELLED' or
                          current_sub_status == 'CANCELED' or
                          main_status == 'CANCELLED' or
                          main_status == 'CANCELED' or
                          'CANCELLED' in main_status or
                          'CANCELLED' in order_status or
                          'CANCELLED' in current_sub_status or
                          'CANCELED' in main_status or
                          'CANCELED' in order_status or
                          'CANCELED' in current_sub_status)
            
            # Additional check: if status contains "cancel" or "cancelled" anywhere
            if not is_cancelled:
                status_str = f"{main_status} {order_status} {current_sub_status} {billed_status}".upper()
                if 'CANCEL' in status_str or 'CANCELLED' in status_str:
                    is_cancelled = True
            
            # CLOSED in Zoho UI can be indicated by:
            # 1. order_status = "CLOSED"
            # 2. current_sub_status = "CLOSED"
            # 3. billed_status = "BILLED"
            # 4. main status = "CLOSED"
            # 5. Any status containing "CLOSED" or "CLOSE"
            # Note: CANCELLED is handled separately above
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
            
            # Log cancelled status specifically for debugging
            if is_cancelled:
                logger.warning(f"⚠️  CANCELLED PO detected: {po['purchaseorder_number']} - setting internal_status to 'Cancelled'")
            
            logger.debug(f"PO {po['purchaseorder_number']}: status='{main_status}', order_status='{order_status}', current_sub_status='{current_sub_status}', billed_status='{billed_status}'")
            logger.debug(f"Final status determination: cancelled={is_cancelled}, closed={is_closed}")
            
            # Get PO creation date from Zoho (they use 'date' field for PO date)
            po_date = po.get('date', '') or po.get('created_time', '') or po.get('purchaseorder_date', '')
            
            # Detect parent PO for overs POs (e.g., PO-00127-OVERS -> PO-00127)
            parent_po_number = None
            if is_overs_po and po_number:
                # Extract parent PO number by removing "-OVERS" suffix
                parent_po_number = po_number[:-6]  # Remove "-OVERS" (6 characters)
                logger.info(f"📋 Overs PO {po_number} linked to parent PO: {parent_po_number}")
            
            if existing:
                # Convert Row to dict for .get() method access
                existing = dict(existing)
                
                # Get current status
                current_internal_status = existing.get('internal_status', 'Active')
                was_closed = bool(existing.get('closed', False))
                was_cancelled = (current_internal_status == 'Cancelled')
                po_id = existing['id']
                
                # Determine new internal status
                if is_cancelled:
                    new_internal_status = 'Cancelled'
                    # Cancelled POs should also be marked as closed to prevent submissions
                    is_now_closed = True
                elif is_closed:
                    # Only update to closed if not already cancelled (preserve cancelled status)
                    if current_internal_status != 'Cancelled':
                        new_internal_status = current_internal_status  # Keep existing status if already set
                    else:
                        new_internal_status = 'Cancelled'  # Keep cancelled status
                    is_now_closed = True
                else:
                    # PO is open - reset cancelled status if it was cancelled before
                    if was_cancelled:
                        new_internal_status = 'Active'  # Reset from cancelled to active
                    else:
                        new_internal_status = current_internal_status  # Keep existing status
                    is_now_closed = False
                
                # Update existing PO with proper status and tablet type
                status_msg = "CANCELLED" if is_cancelled else ("CLOSED" if is_closed else "OPEN")
                logger.debug(f"Updating existing PO {po['purchaseorder_number']}: zoho_status='{zoho_status}', closed={is_now_closed}, internal_status='{new_internal_status}'")
                
                # Update created_at only if we have a date from Zoho and current created_at is different
                if po_date and po_date != existing.get('created_at', '')[:10]:
                    db_conn.execute('''
                        UPDATE purchase_orders 
                        SET po_number = ?, zoho_status = ?, closed = ?, internal_status = ?, parent_po_number = ?, created_at = ?, updated_at = CURRENT_TIMESTAMP
                        WHERE zoho_po_id = ?
                    ''', (po['purchaseorder_number'], zoho_status, is_now_closed, new_internal_status, parent_po_number, po_date, po['purchaseorder_id']))
                else:
                    # Always update closed status and internal status - this is critical for preventing assignments
                    db_conn.execute('''
                        UPDATE purchase_orders 
                        SET po_number = ?, zoho_status = ?, closed = ?, internal_status = ?, parent_po_number = ?, updated_at = CURRENT_TIMESTAMP
                        WHERE zoho_po_id = ?
                    ''', (po['purchaseorder_number'], zoho_status, is_now_closed, new_internal_status, parent_po_number, po['purchaseorder_id']))
                
                # Log status changes
                if (was_closed != is_now_closed) or (was_cancelled != is_cancelled):
                    if (is_now_closed and not was_closed) or (is_cancelled and not was_cancelled):
                        logger.warning(f"⚠️  PO {po['purchaseorder_number']} changed from OPEN to {status_msg}")
                    else:
                        logger.info(f"✅ PO {po['purchaseorder_number']} changed from CLOSED/CANCELLED to OPEN")
                elif was_closed == is_now_closed and was_cancelled == is_cancelled:
                    if is_now_closed:
                        status_display = "cancelled" if is_cancelled else "closed"
                        logger.debug(f"✅ Updated PO {po['purchaseorder_number']}: {status_display}={is_now_closed} (already {status_display})")
                    else:
                        logger.debug(f"✅ Updated PO {po['purchaseorder_number']}: closed={is_now_closed} (still open)")
            else:
                # Insert new PO with proper status and creation date
                # Determine internal status for new PO
                if is_cancelled:
                    new_internal_status = 'Cancelled'
                    is_now_closed = True  # Cancelled POs should be closed
                elif is_closed:
                    new_internal_status = 'Active'  # Will be updated later based on workflow
                    is_now_closed = True
                else:
                    new_internal_status = 'Active'
                    is_now_closed = False
                
                if po_date:
                    cursor = db_conn.execute('''
                        INSERT INTO purchase_orders (po_number, zoho_po_id, zoho_status, closed, internal_status, parent_po_number, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    ''', (po['purchaseorder_number'], po['purchaseorder_id'], 
                          zoho_status, is_now_closed, new_internal_status, parent_po_number, po_date))
                else:
                    cursor = db_conn.execute('''
                        INSERT INTO purchase_orders (po_number, zoho_po_id, zoho_status, closed, internal_status, parent_po_number)
                        VALUES (?, ?, ?, ?, ?, ?)
                    ''', (po['purchaseorder_number'], po['purchaseorder_id'], 
                          zoho_status, is_now_closed, new_internal_status, parent_po_number))
                po_id = cursor.lastrowid
            
            # Determine actual tablet type from line items  
            tablet_types_found = []
            
            # Sync line items - ONLY sync tablet line items (filter out non-tablet items)
            po_details = self.get_purchase_order_details(po['purchaseorder_id'])
            if po_details and 'purchaseorder' in po_details:
                # Get all configured tablet inventory_item_ids to filter line items
                tablet_item_ids = db_conn.execute('''
                    SELECT inventory_item_id FROM tablet_types WHERE inventory_item_id IS NOT NULL AND inventory_item_id != ''
                ''').fetchall()
                tablet_item_ids_set = {row['inventory_item_id'] for row in tablet_item_ids}
                
                for line in po_details['purchaseorder'].get('line_items', []):
                    item_id = line.get('item_id', '')
                    
                    # Only sync line items that match configured tablet types
                    if item_id and item_id not in tablet_item_ids_set:
                        logger.debug(f"⏭️  Skipping non-tablet line item '{line['name']}' (ID: {item_id}) - not in tablet_types")
                        continue
                    
                    # Check if line item already exists
                    existing_line = db_conn.execute(
                        'SELECT id FROM po_lines WHERE po_id = ? AND inventory_item_id = ?',
                        (po_id, item_id)
                    ).fetchone()
                    
                    if existing_line:
                        # Convert Row to dict
                        existing_line = dict(existing_line)
                        
                        # Update existing line
                        db_conn.execute('''
                            UPDATE po_lines 
                            SET line_item_name = ?, quantity_ordered = ?
                            WHERE id = ?
                        ''', (line['name'], line['quantity'], existing_line['id']))
                    else:
                        # Insert new line (only tablet items reach here)
                        db_conn.execute('''
                            INSERT INTO po_lines 
                            (po_id, po_number, inventory_item_id, line_item_name, quantity_ordered)
                            VALUES (?, ?, ?, ?, ?)
                        ''', (po_id, po['purchaseorder_number'], item_id, 
                              line['name'], line['quantity']))
                        logger.debug(f"✅ Synced tablet line item '{line['name']}' (ID: {item_id})")
                    
                    # Extract tablet type using inventory_item_id from configured tablet types
                    # (Only tablet items reach this point due to filtering above)
                    matched_this_line = False
                    
                    if item_id:
                        # Look up the tablet type by inventory_item_id
                        tablet_type_match = db_conn.execute('''
                            SELECT tablet_type_name 
                            FROM tablet_types 
                            WHERE inventory_item_id = ?
                        ''', (item_id,)).fetchone()
                        
                        if tablet_type_match:
                            # Convert Row to dict
                            tablet_type_match = dict(tablet_type_match)
                            tablet_types_found.append(tablet_type_match['tablet_type_name'])
                            matched_this_line = True
                            logger.debug(f"✅ Matched line item '{line['name']}' (ID: {item_id}) to tablet type: {tablet_type_match['tablet_type_name']}")
                    
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
            
            if current_internal:
                current_internal = dict(current_internal)
            
            current_status = current_internal['internal_status'] if current_internal else 'Draft'
            new_internal_status = current_status
            
            # Set internal status based on Zoho workflow progression
            if zoho_status == 'DRAFT':
                new_internal_status = 'Draft'
            elif zoho_status == 'ISSUED':
                new_internal_status = 'Issued'
            elif zoho_status == 'RECEIVED':
                new_internal_status = 'Received' 
                logger.info(f"Auto-progressed {po['purchaseorder_number']} to Received (Zoho status={zoho_status})")
            elif zoho_status == 'PARTIALLY_RECEIVED':
                new_internal_status = 'Partially Received'
                logger.info(f"Detected partial receive for {po['purchaseorder_number']} - waiting for additional shipments")
            elif receives_count > 0 or received_date or is_received:
                new_internal_status = 'Received' 
                logger.info(f"Auto-progressed {po['purchaseorder_number']} to Received (receives_count={receives_count}, received_date={received_date})")
            
            logger.debug(f"Set internal status for {po['purchaseorder_number']}: {current_status} → {new_internal_status}")
            
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
