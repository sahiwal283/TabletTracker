# Route Migration Plan

## Route Organization

### Auth Blueprint (`auth.py`)
- `/` - index/login
- `/logout` - logout
- `/version` - version info

### Production Blueprint (`production.py`)
- `/production` - production form
- `/warehouse` - warehouse form (redirect)
- `/count` - count form (redirect)
- `/submit_warehouse` - submit warehouse
- `/submit_count` - submit bag count
- `/submit_machine_count` - submit machine count

### Dashboard Blueprint (`dashboard.py`)
- `/dashboard` - admin dashboard

### Submissions Blueprint (`submissions.py`)
- `/submissions` - all submissions page
- `/submissions/export` - CSV export

### Purchase Orders Blueprint (`purchase_orders.py`)
- `/purchase_orders` - all POs page

### Shipping Blueprint (`shipping.py`)
- `/shipping` - shipping management
- `/shipments` - public shipments
- `/receiving` - receiving management
- `/receiving/<id>` - receiving details
- `/receiving/debug` - debug endpoint

### Admin Blueprint (`admin.py`)
- `/admin` - admin panel
- `/admin/products` - product mapping
- `/admin/tablet_types` - tablet types config
- `/admin/shipments` - shipments management
- `/admin/employees` - employee management

### API Blueprint (`api.py`)
All `/api/*` routes (60+ endpoints)

## Migration Strategy

1. Create all blueprint files with proper structure
2. Migrate routes one blueprint at a time
3. Update imports to use services where possible
4. Keep old routes commented in app.py as backup
5. Test each blueprint independently
6. Update app.py to register blueprints
7. Remove commented old routes after verification

