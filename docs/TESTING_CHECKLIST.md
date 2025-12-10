# TabletTracker v2.0 Testing Checklist

## Automated Tests

Run test suite:
```bash
python tests/run_tests.py
```

Expected: All tests pass ✓

## Manual Testing Checklist

### 🔐 Authentication Tests

- [ ] **Admin Login**
  - Navigate to `/`
  - Login with username: `admin`, password: `admin`
  - Should redirect to Admin Panel
  
- [ ] **Employee Login (Manager)**
  - Navigate to `/`
  - Login with manager credentials
  - Should redirect to Dashboard

- [ ] **Employee Login (Warehouse Staff)**
  - Navigate to `/`
  - Login with warehouse staff credentials
  - Should redirect to Production page

- [ ] **Logout**
  - Click logout button
  - Should redirect to login page
  - Accessing protected pages should redirect to login

### 📦 Production Workflow

- [ ] **Packaged Submission**
  - Navigate to Production page
  - Select a product
  - Enter box/bag numbers
  - Enter displays, packs, loose tablets
  - Submit form
  - Should show success message

- [ ] **Bag Count Submission**
  - Navigate to Production page
  - Select "Bag Count" tab
  - Select tablet type
  - Enter box/bag numbers and count
  - Submit
  - Should show success message

- [ ] **Machine Count Submission**
  - Navigate to Production page
  - Select "Machine Count" tab
  - Enter machine count details
  - Submit
  - Should show success message

### 📊 Dashboard Tests

- [ ] **Dashboard Loads**
  - Navigate to `/dashboard` as manager/admin
  - Should display:
    - Purchase Orders summary
    - Recent submissions
    - Statistics

- [ ] **PO Sync from Zoho**
  - Click "Sync POs" button
  - Should fetch POs from Zoho
  - Should update PO list

- [ ] **View PO Details**
  - Click on any PO number
  - Modal should open showing:
    - PO lines
    - Quantities
    - Submissions linked to PO

### 📥 Receiving Workflow

- [ ] **Shipping/Receiving Page Loads**
  - Navigate to `/shipping`
  - Should display receiving records
  - Should show tablet types dropdown

- [ ] **Create Receiving Record**
  - Enter shipment details
  - Upload photos (optional)
  - Add boxes and bags
  - Save receiving record
  - Should appear in list

- [ ] **Assign Receiving to PO**
  - View receiving details
  - Assign to a PO
  - Bags should link to PO
  - PO counts should update

### 📋 Submissions Management

- [ ] **View All Submissions**
  - Navigate to `/submissions`
  - Should list all submissions
  - Filter by status, date, PO
  
- [ ] **Approve Submission**
  - Click approve on a submission
  - Should mark as approved
  - PO counts should update

- [ ] **Reassign Submission**
  - Click reassign on a submission
  - Select new PO
  - Should move to new PO
  - Counts should update

- [ ] **Export Submissions**
  - Click "Export CSV"
  - Should download CSV file
  - File should contain all submissions

### 🛒 Purchase Orders

- [ ] **View All Purchase Orders**
  - Navigate to `/purchase_orders`
  - Should list all POs
  - Filter by open/closed/draft

- [ ] **Create Overs PO**
  - View PO with overs
  - Click "Create Overs PO"
  - Should create new PO in Zoho
  - Should appear as sub-PO

- [ ] **Close PO**
  - View PO details
  - Click "Close PO"
  - Should mark as closed
  - Should update status

### ⚙️ Admin Functions

- [ ] **Product Mapping**
  - Navigate to `/admin/products`
  - Add new product
  - Configure packaging details
  - Save
  - Should appear in dropdowns

- [ ] **Tablet Types Management**
  - Navigate to `/admin/tablet_types`
  - Add new tablet type
  - Link to Zoho inventory item
  - Save
  - Should appear in system

- [ ] **Employee Management**
  - Navigate to admin panel
  - Click "Employees"
  - Add new employee
  - Set role (warehouse_staff/manager/admin)
  - Save
  - Should be able to login

### 🌍 Language/Internationalization

- [ ] **Switch Language**
  - Click language selector in nav
  - Select Español
  - UI should switch to Spanish
  - Switch back to English
  - Should persist across pages

### 📱 Mobile Responsiveness

- [ ] **Resize Browser**
  - Test at mobile width (375px)
  - Navigation should collapse to menu
  - Forms should be usable
  - Tables should scroll horizontally

### 🔍 Edge Cases

- [ ] **Duplicate Bag Detection**
  - Submit bag count for box/bag already received
  - System should flag for review
  - Should not auto-assign to PO

- [ ] **Negative Inventory**
  - Submit counts exceeding PO ordered quantity
  - Should allow and show as overs
  - Overs should be tracked

- [ ] **Missing Data**
  - Try submitting forms with missing fields
  - Should show validation errors
  - Should not submit

## Performance Tests

- [ ] **Page Load Times**
  - Dashboard should load < 2 seconds
  - Submissions page should load < 3 seconds
  - Large PO lists should be paginated

- [ ] **Database Queries**
  - No obvious N+1 query issues
  - Joins properly optimized
  - Indexes on frequently queried columns

## Browser Compatibility

Test in:
- [ ] Chrome (latest)
- [ ] Firefox (latest)
- [ ] Safari (latest)
- [ ] Mobile Safari (iOS)
- [ ] Mobile Chrome (Android)

## Security Tests

- [ ] **Authentication Required**
  - Try accessing `/dashboard` without login
  - Should redirect to login

- [ ] **Role-Based Access**
  - Warehouse staff cannot access `/admin`
  - Warehouse staff cannot access `/dashboard`
  - Only managers/admin can see shipping page

- [ ] **Session Timeout**
  - Leave app idle for 8+ hours
  - Next action should require re-login

## Database Tests

- [ ] **Alembic Migrations**
  - Run `alembic upgrade head`
  - Should apply migrations successfully
  - Run `alembic downgrade -1`
  - Should rollback successfully

- [ ] **Database Backup**
  - Check `backups/` directory has recent backups
  - Backup files should be compressed
  - Health checks should pass

## API Tests

- [ ] **Version Endpoint**
  - GET `/version`
  - Should return JSON with version info

- [ ] **API Endpoints (Authenticated)**
  - Try API calls without authentication
  - Should return 401/403 errors

## Post-Deployment Checklist (PythonAnywhere)

- [ ] Update `wsgi.py` to use `create_app()`
- [ ] Set environment variables in PythonAnywhere
- [ ] Update static files mapping
- [ ] Reload web app
- [ ] Test critical flows on production
- [ ] Monitor error logs for issues

## Success Criteria

All checklist items should pass before deploying to production.

If any tests fail, investigate and fix before proceeding.

