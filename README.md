# TabletTracker v2.0

Production tablet counting and tracking system for Haute Nutrition.

## ⚡ Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Initialize database (if needed)
alembic upgrade head

# Run development server
python app.py
```

Access at: `http://localhost:5000`

**Default login:** admin / admin

## 🏗️ Architecture

Built with Flask using application factory pattern:

- **Blueprints**: Modular route organization (8 blueprints, 95 routes)
- **Services**: Business logic layer
- **Alembic**: Database migrations
- **Babel**: Internationalization (English/Spanish)
- **SQLite**: Database (production-ready)

## 📁 Project Structure

```
TabletTracker/
├── app/
│   ├── __init__.py          # Application factory
│   ├── blueprints/          # Route blueprints
│   ├── services/            # Business logic
│   ├── utils/               # Helper functions
│   └── models/              # Database models
├── database/
│   ├── tablet_counter.db    # SQLite database
│   └── migrations/          # Alembic migrations
├── templates/               # Jinja2 templates
├── static/                  # CSS, JS, images
├── tests/                   # Test suite
├── docs/                    # Documentation
└── scripts/                 # Utility scripts
```

## 🧪 Testing

```bash
# Run test suite
python tests/run_tests.py

# Or with unittest
python -m unittest discover tests
```

## 📚 Documentation

- [Refactor Summary](docs/REFACTORV2_SUMMARY.md) - v2.0 changes
- [Testing Checklist](docs/TESTING_CHECKLIST.md) - Manual testing guide
- [Deployment Guide](docs/DEPLOYMENT.md) - PythonAnywhere setup

## 🚀 Deployment (PythonAnywhere)

Update `wsgi.py`:
```python
from app import create_app
application = create_app()
```

Static files mapping:
- URL: `/static/`
- Directory: `/home/yourusername/TabletTracker/static/`

## 🔧 Development

### Database Migrations

```bash
# Create new migration
alembic revision -m "description"

# Apply migrations
alembic upgrade head

# Rollback one migration
alembic downgrade -1
```

### Adding New Routes

1. Create route in appropriate blueprint (`app/blueprints/`)
2. Use `@bp.route()` decorator
3. Blueprint auto-registered in `app/__init__.py`

## 🎯 Features

- **Production Tracking**: Packaged, bag count, machine count submissions
- **Purchase Orders**: Sync from Zoho, track inventory
- **Receiving**: Shipment tracking, box/bag management
- **Dashboard**: Real-time analytics and reporting
- **Multi-language**: English and Spanish support
- **Role-Based Access**: Admin, Manager, Warehouse Staff roles

## 📊 Version

Current: v2.8.0 (Security Enhanced)
- **NEW**: CSRF protection & rate limiting
- **NEW**: Comprehensive security utilities
- **NEW**: Enhanced input validation & error handling
- 99.7% reduction in main app file
- Modular blueprint architecture
- Comprehensive test coverage
- Production-ready

## 🔐 Security

- Session-based authentication with session fixation protection
- Role-based access control
- CSRF protection (Flask-WTF)
- Rate limiting on authentication endpoints
- Comprehensive security headers (CSP, X-Frame-Options, etc.)
- XSS protection utilities
- Secure error handling (no information leakage)
- Input validation and sanitization
- 8-hour session timeout

## 📝 License

Proprietary - Haute Nutrition Internal Tool

## 🤝 Contributing

Internal tool - contact development team for changes.

---

Built with ❤️ for Haute Nutrition

