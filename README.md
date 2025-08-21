# Tablet Production Counter

A Python web application to track tablet production against Zoho Inventory Purchase Orders. 

**Replaces:** Google Forms + Google Sheets workflow  
**Integrates:** Zoho Inventory API for PO sync  
**Optimized:** Mobile forms for warehouse staff, desktop dashboard for managers  

## Features

✅ **Mobile-Responsive Warehouse Form**
- Optimized for phones/tablets
- Auto-calculates tablet counts
- Validates against bag label count
- Shows discrepancy warnings

✅ **Admin Dashboard** 
- Desktop-optimized interface
- Real-time PO status tracking
- Recent submissions view
- Export capabilities

✅ **Zoho Integration**
- Syncs Purchase Orders automatically
- Matches by Inventory Item ID (not fragile name matching)
- Updates counts in real-time

✅ **Smart Business Logic**
- Allocates production to oldest open POs first
- Handles multiple line items per PO
- Tracks good vs damaged counts separately
- Auto-calculates remaining quantities

## Quick Start (Local Development)

1. **Setup Virtual Environment**
```bash
cd ~/Projects/Haute/TabletTracker
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

2. **Setup Environment Variables**
```bash
cp env_template.txt .env
# Edit .env with your Zoho API credentials
```

3. **Initialize Database**
```bash
python setup_db.py
```

4. **Run Application**
```bash
python app.py
```

4. **Open in Browser**
- Main app: http://localhost:5000
- Warehouse form: http://localhost:5000/warehouse
- Admin dashboard: http://localhost:5000/dashboard

## PythonAnywhere Deployment

### 1. Upload Files
Upload your TabletTracker folder to PythonAnywhere

### 2. Install Dependencies
In PythonAnywhere console:
```bash
cd /home/yourusername/TabletTracker
pip3.10 install --user -r requirements.txt
```

### 3. Setup Environment Variables
In PythonAnywhere Dashboard > Files, create `.env`:
```
SECRET_KEY=your-production-secret-key
ZOHO_CLIENT_ID=your_zoho_client_id
ZOHO_CLIENT_SECRET=your_zoho_client_secret
ZOHO_REFRESH_TOKEN=your_zoho_refresh_token
ZOHO_ORGANIZATION_ID=856048585
```

### 4. Initialize Database
In console:
```bash
python3.10 setup_db.py
```

### 5. Configure Web App
In PythonAnywhere Web tab:
- Source code: `/home/yourusername/TabletTracker`
- WSGI file: Edit to point to your app.py
- Static files: `/static/` → `/home/yourusername/TabletTracker/static/`

### 6. Reload and Test
Hit "Reload" and visit your PythonAnywhere URL

## Zoho API Setup

### Get API Credentials
1. Go to https://api-console.zoho.com/
2. Create a new "Server-based Applications" client
3. Set redirect URL to: `http://localhost:8080` (for token generation)
4. Note your Client ID and Client Secret

### Get Refresh Token
1. Visit authorization URL (replace YOUR_CLIENT_ID):
```
https://accounts.zoho.com/oauth/v2/auth?scope=ZohoInventory.FullAccess.all&client_id=YOUR_CLIENT_ID&response_type=code&redirect_uri=http://localhost:8080&access_type=offline
```
2. Authorize and copy the code from the redirect URL
3. Exchange for refresh token using curl or Postman
4. Save the `refresh_token` from response

## Database Schema

### Core Tables
- **purchase_orders**: PO headers with totals
- **po_lines**: Individual line items per PO
- **tablet_types**: Master list with Inventory Item IDs
- **product_details**: Product configs with multipliers
- **warehouse_submissions**: All production submissions

### Key Relationships
- Product → Tablet Type → Inventory Item ID
- PO → Multiple Lines (by Inventory Item ID)
- Submissions → Auto-allocated to matching PO lines

## Workflow

### 1. PO Sync (Automated)
1. Zoho Inventory creates tablet PO
2. Admin clicks "Sync Zoho POs" in dashboard
3. System pulls PO + line items via API
4. Stores locally with Inventory Item IDs

### 2. Production Submission (Warehouse Staff)
1. Staff opens mobile form
2. Selects product, enters counts
3. System auto-calculates tablets using multipliers
4. Finds oldest open PO with matching Inventory Item ID
5. Allocates good/damaged counts to available capacity
6. Updates PO header totals

### 3. Monitoring (Managers)
1. Dashboard shows real-time PO status
2. Recent submissions log
3. Export capabilities for reporting

## Advantages Over Zoho Creator/Deluge

✅ **Real debugging** - actual error messages, logging, testing  
✅ **Full control** - custom UI, business logic, data flow  
✅ **Better mobile UX** - responsive design, touch-friendly  
✅ **Easier maintenance** - Python instead of Deluge syntax hell  
✅ **Future-proof** - can extend with any features you need  

## Next Steps

1. **Test locally** with sample data
2. **Deploy to PythonAnywhere** 
3. **Setup Zoho API credentials**
4. **Test PO sync** with real data
5. **Train warehouse staff** on new mobile form
6. **Migrate from Google Forms**

## Support

For issues or questions about this implementation, check:
1. PythonAnywhere logs for runtime errors
2. Browser console for frontend issues  
3. `/dashboard` for business logic validation
