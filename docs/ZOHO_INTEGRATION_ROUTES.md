# Zoho Integration Routes and API Endpoints

This document lists all routes and Zoho API endpoints used by the TabletTracker application for seamless integration service migration.

## Application Routes (Flask Endpoints)

### Purchase Order Sync
- **Route**: `POST /api/sync_zoho_pos`
- **Method**: POST (also accepts GET)
- **Auth**: Requires `dashboard` role permission
- **Description**: Syncs Purchase Orders from Zoho Inventory to local database
- **Handler**: `app/blueprints/api_purchase_orders.py::sync_zoho_pos()`
- **Service Method**: `zoho_api.sync_tablet_pos_to_db(conn)`
- **Returns**: JSON with `success` and `message` or `error`

### Test Zoho Connection
- **Route**: `GET /api/test_zoho_connection`
- **Method**: GET
- **Auth**: Admin only (`@admin_required`)
- **Description**: Tests if Zoho API credentials are working
- **Handler**: `app/blueprints/api.py::test_zoho_connection()`
- **Service Methods**: 
  - `zoho_api.get_access_token()`
  - `zoho_api.make_request('items', method='GET', extra_params={'per_page': 10})`
- **Returns**: JSON with `success`, `message`/`error`, and `organization_id`

### Push Bag to Zoho
- **Route**: `POST /api/bag/<int:bag_id>/push_to_zoho`
- **Method**: POST
- **Auth**: Requires `dashboard` role permission (managers/admins only)
- **Description**: Pushes a closed bag to Zoho as a purchase receive
- **Handler**: `app/blueprints/api_receiving.py::push_bag_to_zoho(bag_id)`
- **Request Body** (optional JSON):
  ```json
  {
    "custom_notes": "Additional notes to append"
  }
  ```
- **Service Method**: `zoho_api.create_purchase_receive(...)`
- **Returns**: JSON with `success`, `message`, and `zoho_receive_id`

### Create Overs PO
- **Route**: `POST /api/create_overs_po/<int:po_id>`
- **Method**: POST
- **Auth**: Requires `dashboard` role permission
- **Description**: Creates an overs PO in Zoho for a parent PO
- **Handler**: `app/blueprints/api_purchase_orders.py::create_overs_po(po_id)`
- **Service Methods**:
  - `zoho_api.get_purchase_order_details(zoho_po_id)`
  - `zoho_api.create_purchase_order(po_data)`
- **Returns**: JSON with `success`, `message`, `overs_po_number`, `zoho_po_id`, `total_overs`

### Get Overs PO Info
- **Route**: `GET /api/create_overs_po_info/<int:po_id>`
- **Method**: GET
- **Auth**: Requires `dashboard` role permission
- **Description**: Gets information needed to create an overs PO (for preview)
- **Handler**: `app/blueprints/api_purchase_orders.py::get_overs_po_info(po_id)`
- **Returns**: JSON with `success`, `parent_po_number`, `overs_po_number`, `tablet_type`, `total_overs`, `line_items`

### Find Organization ID
- **Route**: `GET /api/find_org_id`
- **Method**: GET
- **Auth**: Admin only (`@admin_required`)
- **Description**: Finds Zoho organization ID from API
- **Handler**: `app/blueprints/api.py::find_organization_id()`
- **Service Method**: `zoho_api.make_request('organizations', method='GET')`
- **Returns**: JSON with `success`, `organizations` array, or `error`

---

## Zoho API Endpoints Used

### Base Configuration
- **Base URL**: `https://www.zohoapis.com/inventory/v1`
- **OAuth Token URL**: `https://accounts.zoho.com/oauth/v2/token`
- **Required Parameters**: All requests include `organization_id` as query parameter

### Authentication
- **Endpoint**: `POST https://accounts.zoho.com/oauth/v2/token`
- **Method**: POST
- **Purpose**: Get access token using refresh token
- **Request Body**:
  ```
  refresh_token: <ZOHO_REFRESH_TOKEN>
  client_id: <ZOHO_CLIENT_ID>
  client_secret: <ZOHO_CLIENT_SECRET>
  grant_type: refresh_token
  ```
- **Response**: JSON with `access_token`, `expires_in`
- **Used By**: `zoho_api.get_access_token()`

### Purchase Orders

#### Get Purchase Orders
- **Endpoint**: `GET /purchaseorders`
- **Method**: GET
- **Query Parameters**:
  - `organization_id` (required)
  - `per_page` (default: 200)
  - `status` (optional: 'all', 'open', 'closed', etc.)
- **Response**: JSON with `purchaseorders` array
- **Used By**: `zoho_api.get_purchase_orders(status='all', per_page=200)`
- **Called From**: `sync_tablet_pos_to_db()`

#### Get Purchase Order Details
- **Endpoint**: `GET /purchaseorders/{po_id}`
- **Method**: GET
- **Query Parameters**: `organization_id` (required)
- **Response**: JSON with `purchaseorder` object containing `line_items` array
- **Used By**: `zoho_api.get_purchase_order_details(po_id)`
- **Called From**: 
  - `sync_tablet_pos_to_db()` (to get line items)
  - `create_overs_po()` (to get parent PO details)

#### Create Purchase Order
- **Endpoint**: `POST /purchaseorders`
- **Method**: POST
- **Query Parameters**: `organization_id` (required)
- **Request Body** (JSON):
  ```json
  {
    "purchaseorder_number": "PO-00127-OVERS",
    "date": "2025-01-07",
    "line_items": [
      {
        "item_id": "5254962000001245053",
        "name": "FIX Tablets Relax (Red) 30mg* PHOTO",
        "quantity": 1000,
        "rate": 0
      }
    ],
    "cf_tablets": true,
    "notes": "Overs PO for PO-00127 - 1,000 tablets",
    "status": "draft",
    "vendor_id": "...",
    "vendor_name": "...",
    "currency_code": "USD"
  }
  ```
- **Response**: JSON with `purchaseorder` object including `purchaseorder_id`
- **Used By**: `zoho_api.create_purchase_order(po_data)`
- **Called From**: `create_overs_po()`

### Purchase Receives

#### Create Purchase Receive
- **Endpoint**: `POST /purchasereceives`
- **Method**: POST
- **Query Parameters**: 
  - `organization_id` (required)
  - `purchaseorder_id` (required) - passed as URL parameter, not in body
- **Request Body** (JSON):
  ```json
  {
    "date": "2025-01-07",
    "line_items": [
      {
        "line_item_id": "5254962000003613429",
        "quantity": 20008
      }
    ],
    "receive_number": "auto-generated or custom",
    "notes": "Shipment: PO-00156-3\nBox 1, Bag 1\nReceived: 20,000\nPackaged: 20,008"
  }
  ```
- **Response**: JSON with `purchasereceive` object containing `purchasereceive_id` (or `purchase_receive_id`, `id`, `receive_id`)
- **Used By**: `zoho_api.create_purchase_receive(...)`
- **Called From**: `push_bag_to_zoho()`

#### Attach File to Purchase Receive
- **Endpoint**: `POST /purchasereceives/{receive_id}/attachment`
- **Method**: POST
- **Query Parameters**: `organization_id` (required)
- **Request**: Multipart form data
  ```
  attachment: <file_bytes> (image/png)
  ```
- **Response**: 200/201 on success
- **Used By**: `zoho_api.attach_file_to_receive(receive_id, file_bytes, filename)`
- **Called From**: `create_purchase_receive()` (automatically after receive creation if image provided)

### Inventory Items

#### Get Items
- **Endpoint**: `GET /items`
- **Method**: GET
- **Query Parameters**:
  - `organization_id` (required)
  - `per_page` (default: 200)
- **Response**: JSON with `items` array
- **Used By**: `zoho_api.get_items(per_page=200)`
- **Called From**: `test_zoho_connection()`

### Organizations

#### Get Organizations
- **Endpoint**: `GET /organizations`
- **Method**: GET
- **Query Parameters**: None (uses organization_id from config)
- **Response**: JSON with `organizations` array
- **Used By**: `zoho_api.make_request('organizations', method='GET')`
- **Called From**: `find_organization_id()`

---

## Zoho Service Methods (Internal API)

### ZohoInventoryAPI Class (`app/services/zoho_service.py`)

#### Authentication
- `get_access_token()` - Gets/refreshes OAuth access token

#### Purchase Orders
- `get_purchase_orders(status='all', per_page=200)` - Lists POs
- `get_purchase_order_details(po_id)` - Gets PO with line items
- `create_purchase_order(po_data)` - Creates new PO

#### Purchase Receives
- `create_purchase_receive(purchaseorder_id, line_items, date, receive_number=None, notes=None, image_bytes=None, image_filename=None)` - Creates receive
- `attach_file_to_receive(receive_id, file_bytes, filename)` - Attaches image to receive

#### Inventory Items
- `get_items(per_page=200)` - Lists inventory items

#### Sync Operations
- `sync_tablet_pos_to_db(db_conn)` - Syncs tablet POs from Zoho to local DB

#### Generic Request Method
- `make_request(endpoint, method='GET', data=None, extra_params=None)` - Generic authenticated request

---

## Request/Response Patterns

### Authentication Headers
All Zoho API requests include:
```
Authorization: Zoho-oauthtoken <access_token>
Content-Type: application/json
```

### Common Query Parameters
- `organization_id` - Always required (from config: `ZOHO_ORGANIZATION_ID`)

### Error Handling
- Zoho API returns `{"code": <non-zero>, "message": "error message"}` on errors
- Application checks `code != 0` to detect errors
- Access token expires after 1 hour (auto-refreshed)

### Custom Fields Used
- `cf_tablets` or `cf_tablets_unformatted` - Marks PO as tablet PO
- `cf_status` or `cf_status_unformatted` - Custom status field

---

## Environment Variables Required

```bash
ZOHO_CLIENT_ID=<from zoho api console>
ZOHO_CLIENT_SECRET=<from zoho api console>
ZOHO_REFRESH_TOKEN=<from oauth flow>
ZOHO_ORGANIZATION_ID=<your organization id>
```

---

## Integration Points Summary

1. **PO Sync**: `/api/sync_zoho_pos` → `sync_tablet_pos_to_db()` → `GET /purchaseorders` + `GET /purchaseorders/{id}`
2. **Push Receive**: `/api/bag/{id}/push_to_zoho` → `create_purchase_receive()` → `POST /purchasereceives` + `POST /purchasereceives/{id}/attachment`
3. **Create Overs PO**: `/api/create_overs_po/{id}` → `get_purchase_order_details()` + `create_purchase_order()` → `GET /purchaseorders/{id}` + `POST /purchaseorders`
4. **Test Connection**: `/api/test_zoho_connection` → `get_access_token()` + `get_items()` → `POST /oauth/v2/token` + `GET /items`

---

## Notes for Integration Service Migration

1. **OAuth Flow**: Uses refresh token flow (no user interaction needed)
2. **Token Management**: Access tokens are cached and auto-refreshed
3. **Error Handling**: All methods return `None` on error, check response `code` field
4. **PO Filtering**: Only syncs POs with `cf_tablets` or `cf_tablets_unformatted = true`
5. **Line Item Filtering**: Only syncs line items matching configured `tablet_types.inventory_item_id`
6. **Status Mapping**: Maps Zoho statuses (`ISSUED`, `CLOSED`, `CANCELLED`) to internal statuses
7. **File Attachments**: Uses multipart/form-data for image uploads (not JSON)
8. **Receive Creation**: `purchaseorder_id` must be passed as URL parameter, not in body

