# TabletTracker v2.0 Architecture

## System Overview

TabletTracker is a Flask-based production tracking system for tablet manufacturing with Zoho integration, built using a modular blueprint architecture.

```
┌─────────────────────────────────────────────────────────────┐
│                         User Interface                       │
│                    (Templates + JavaScript)                  │
└───────────────┬─────────────────────────────────────────────┘
                │
┌───────────────▼─────────────────────────────────────────────┐
│                      Flask Application                       │
│                    (Application Factory)                     │
│  ┌─────────────────────────────────────────────────────────┐│
│  │             Blueprint Layer (Routes)                    ││
│  │  auth │ admin │ dashboard │ production │ submissions   ││
│  │  purchase_orders │ receiving │ api                     ││
│  └─────────────────────┬───────────────────────────────────┘│
└────────────────────────┼────────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────────┐
│                    Service Layer                             │
│     zoho_service │ tracking_service │ report_service        │
└────────────────────────┬────────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────────┐
│                    Data Layer                                │
│         SQLite Database + Alembic Migrations                 │
└──────────────────────────────────────────────────────────────┘
```

## Directory Structure

```
TabletTracker/
├── app/                          # Main application package
│   ├── __init__.py              # Application factory (create_app)
│   ├── blueprints/              # Modular route handlers
│   │   ├── auth.py             # Authentication & login
│   │   ├── admin.py            # Admin panel & configuration
│   │   ├── dashboard.py        # Dashboard & analytics
│   │   ├── production.py       # Production forms & submissions
│   │   ├── submissions.py      # Submission management
│   │   ├── purchase_orders.py  # PO management
│   │   ├── receiving.py        # Receiving & shipment tracking
│   │   └── api.py             # API endpoints
│   ├── models/                  # Database models
│   │   └── database.py         # Database initialization
│   ├── services/                # Business logic layer
│   │   ├── zoho_service.py     # Zoho API integration
│   │   ├── tracking_service.py # Shipment tracking
│   │   └── report_service.py   # PDF report generation
│   └── utils/                   # Helper utilities
│       ├── db_utils.py         # Database connection utilities
│       ├── auth_utils.py       # Authentication decorators
│       ├── response_utils.py   # API response helpers
│       ├── validation.py       # Input validation
│       ├── permissions.py      # Permission checking
│       └── route_helpers.py    # Route helper functions
│
├── database/                     # Database files
│   ├── tablet_counter.db        # SQLite database
│   └── migrations/              # Alembic migrations
│       ├── versions/            # Numbered migration files
│       └── legacy/              # Archived ad-hoc scripts
│
├── templates/                    # Jinja2 templates
│   ├── base.html               # Base template with navigation
│   ├── layouts/                # Intermediate base templates
│   ├── components/             # Reusable template fragments
│   └── *.html                  # Feature-specific templates
│
├── static/                       # Static assets
│   └── js/                      # JavaScript files
│       ├── modal-manager.js    # Shared modal components
│       └── api-client.js       # API client utilities
│
├── tests/                        # Test suite
│   ├── test_auth.py            # Authentication tests
│   ├── test_api.py             # API endpoint tests
│   ├── test_database.py        # Database tests
│   ├── test_routes.py          # Route tests
│   ├── test_app_factory.py     # App factory tests
│   └── run_tests.py            # Test runner
│
├── docs/                         # Documentation
│   ├── ARCHITECTURE.md          # This file
│   ├── REFACTORV2_COMPLETE.md  # Refactor summary
│   ├── MIGRATION_V2.md         # Migration guide
│   ├── DEVELOPMENT.md          # Development guide
│   └── TESTING_CHECKLIST.md    # Testing procedures
│
├── app.py                        # Application entry point (23 lines)
├── config.py                     # Configuration management
├── __version__.py                # Version information
├── requirements.txt              # Python dependencies
└── wsgi.py                       # WSGI entry for deployment
```

## Application Architecture

### Application Factory Pattern

The app uses the factory pattern for flexibility and testability:

```python
# app/__init__.py
def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    
    # Initialize extensions (Babel)
    babel.init_app(app, locale_selector=get_locale)
    
    # Register blueprints
    from app.blueprints import auth, admin, dashboard, ...
    app.register_blueprint(auth.bp)
    # ... more blueprints
    
    return app
```

### Blueprint Architecture

Each blueprint handles a specific feature area:

| Blueprint | Prefix | Responsibility |
|-----------|--------|----------------|
| `auth` | `/` | Login, logout, authentication |
| `admin` | `/admin` | Admin panel, config management |
| `dashboard` | `/dashboard` | Analytics, reports, overview |
| `production` | `/production` | Production forms, submissions |
| `submissions` | `/submissions` | Submission management, export |
| `purchase_orders` | `/purchase-orders` | PO management, Zoho sync |
| `receiving` | `/receiving` | Shipment receiving, tracking |
| `api` | `/api` | REST API endpoints |

### Service Layer

Services contain business logic separate from routes:

**`zoho_service.py`** - Zoho API integration
- `zoho_api.authenticate()` - OAuth authentication
- `zoho_api.get_purchase_orders()` - Fetch POs
- `zoho_api.create_item()` - Create Zoho items

**`tracking_service.py`** - Shipment tracking
- `refresh_shipment_row()` - Update tracking status
- Track packages via USPS/FedEx

**`report_service.py`** - PDF generation
- `ProductionReportGenerator` - Generate production reports

### Data Layer

**Database**: SQLite (tablet_counter.db)
**Migrations**: Alembic with numbered versions

Key tables:
- `employees` - User accounts
- `warehouse_submissions` - Production submissions
- `purchase_orders` - PO records from Zoho
- `po_lines` - PO line items
- `receives` - Received shipments
- `tablet_types` - Product configurations

### Authentication & Authorization

**Decorators** (in `app/utils/auth_utils.py`):
- `@admin_required` - Admin only
- `@employee_required` - Authenticated employee
- `@role_required('role')` - Specific role required

**Role Hierarchy**:
- `admin` - Full access
- `manager` - Dashboard, submissions, POs
- `warehouse` - Production submissions
- `shipping` - Receiving, shipments

### Request Flow

```
1. User Request
   ↓
2. Blueprint Route Handler
   ↓
3. Authentication Decorator (@role_required)
   ↓
4. Service Layer (if needed)
   ↓
5. Database Query (via db_utils.get_db())
   ↓
6. Response (Template or JSON)
```

## Key Design Patterns

### 1. Application Factory
- **Purpose**: Create app instances with different configs
- **Location**: `app/__init__.py`
- **Benefits**: Testing, multiple environments

### 2. Blueprint Pattern
- **Purpose**: Modular route organization
- **Location**: `app/blueprints/`
- **Benefits**: Separation of concerns, maintainability

### 3. Service Layer
- **Purpose**: Business logic separation
- **Location**: `app/services/`
- **Benefits**: Reusability, testability

### 4. Decorator Pattern
- **Purpose**: Authentication & authorization
- **Location**: `app/utils/auth_utils.py`
- **Benefits**: DRY, consistent security

### 5. Repository Pattern (lightweight)
- **Purpose**: Data access abstraction
- **Location**: `app/utils/db_utils.py`
- **Benefits**: Consistent DB access

## Technology Stack

- **Framework**: Flask 3.0.3
- **Database**: SQLite 3
- **Migrations**: Alembic 1.13.1
- **Templating**: Jinja2
- **Internationalization**: Flask-Babel
- **Testing**: unittest (built-in)
- **External APIs**: Zoho CRM, USPS/FedEx tracking

## Security Features

- Role-based access control (RBAC)
- Session-based authentication
- Secure session cookies (production)
- CSRF protection (Flask-WTF compatible)
- Input sanitization
- SQL injection protection (parameterized queries)
- XSS protection (template escaping)

## Deployment

- **Production**: PythonAnywhere
- **WSGI**: `wsgi.py` entry point
- **Config**: Environment-based (`Config.ENV`)
- **Database**: File-based SQLite (easy backup/restore)

## Scalability Considerations

- **Horizontal**: Blueprint architecture allows feature separation
- **Database**: Can migrate to PostgreSQL by changing Config.DATABASE_URL
- **Caching**: Can add Flask-Caching for dashboard
- **API**: RESTful design allows frontend decoupling
- **Background Jobs**: Can add Celery for async tasks (Zoho sync, reports)

## Monitoring & Logging

- `current_app.logger` for application logs
- Error handlers for 404/500
- Deprecation warnings for old routes
- Session tracking for authenticated users

## Future Enhancements

- API documentation (OpenAPI/Swagger)
- WebSocket support for real-time updates
- Background task queue (Celery/RQ)
- Redis caching layer
- Database connection pooling
- Frontend framework (React/Vue)
- GraphQL API option
- Multi-tenancy support

