# Development Guide

## Getting Started

### Prerequisites

- Python 3.9+
- Git
- pip
- Virtual environment (recommended)

### Initial Setup

```bash
# Clone repository
git clone https://github.com/sahiwal283/TabletTracker.git
cd TabletTracker

# Create virtual environment
python -m venv venv

# Activate virtual environment
# On macOS/Linux:
source venv/bin/activate
# On Windows:
venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run application
python app.py
```

Visit http://localhost:5001

**Default Login**: admin / admin

## Project Structure

See `docs/ARCHITECTURE.md` for detailed architecture documentation.

```
TabletTracker/
├── app/                     # Main application package
│   ├── __init__.py         # Application factory
│   ├── blueprints/         # Route handlers
│   ├── services/           # Business logic
│   ├── models/             # Database models
│   └── utils/              # Utilities
├── database/               # Database & migrations
├── templates/              # Jinja2 templates
├── static/                 # Static assets
├── tests/                  # Test suite
└── docs/                   # Documentation
```

## Naming Conventions

Follow these conventions throughout the codebase:

| Context | Convention | Example |
|---------|-----------|---------|
| **URL Routes** | kebab-case | `/purchase-orders`, `/api/sync-zoho-pos` |
| **Python Functions** | snake_case | `receiving_list()`, `get_purchase_orders()` |
| **Python Variables** | snake_case | `purchase_order`, `tablet_type_id` |
| **Python Classes** | PascalCase | `ProductionReportGenerator` |
| **Database Tables** | snake_case | `purchase_orders`, `tablet_types` |
| **Database Columns** | snake_case | `po_number`, `tablet_type_name` |
| **Python Files** | snake_case | `receiving.py`, `zoho_service.py` |
| **JavaScript Functions** | camelCase | `viewPODetailsModal()`, `showSuccess()` |
| **JavaScript Variables** | camelCase | `purchaseOrder`, `tabletTypeId` |
| **JS/CSS Files** | kebab-case | `modal-manager.js`, `api-client.js` |
| **Constants** | UPPER_SNAKE_CASE | `MAX_ITEMS`, `API_TIMEOUT` |

## Adding New Features

### Creating a New Blueprint

1. **Create blueprint file** (`app/blueprints/my_feature.py`):

```python
"""
My Feature routes
"""
from flask import Blueprint, render_template, request, jsonify
from app.utils.db_utils import get_db
from app.utils.auth_utils import role_required

bp = Blueprint('my_feature', __name__)


@bp.route('/my-feature')
@role_required('manager')
def my_feature_list():
    """List view for my feature"""
    conn = get_db()
    # Your logic here
    return render_template('my_feature.html')
```

2. **Register blueprint** (`app/__init__.py`):

```python
from app.blueprints import ..., my_feature

app.register_blueprint(my_feature.bp)
```

3. **Create template** (`templates/my_feature.html`):

```html
{% extends "base.html" %}
{% block content %}
  <!-- Your content -->
{% endblock %}
```

4. **Add navigation** (`templates/base.html`):

```html
<a href="{{ url_for('my_feature.my_feature_list') }}">My Feature</a>
```

### Creating a Database Migration

```bash
# Create migration
alembic revision -m "add_my_column"

# Edit generated file in database/migrations/versions/
# Add upgrade() and downgrade() logic

# Apply migration
alembic upgrade head

# Rollback if needed
alembic downgrade -1
```

Example migration:

```python
def upgrade():
    op.add_column('my_table', 
        sa.Column('my_column', sa.String(255), nullable=True))

def downgrade():
    op.drop_column('my_table', 'my_column')
```

### Adding API Endpoints

Add to `app/blueprints/api.py`:

```python
@bp.route('/api/my-endpoint', methods=['GET'])
@role_required('manager')
def my_endpoint():
    """API endpoint description"""
    try:
        conn = get_db()
        # Your logic
        return jsonify({'success': True, 'data': data})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
```

### Creating Services

Add to `app/services/my_service.py`:

```python
"""
My Service - Business logic for my feature
"""

class MyService:
    def __init__(self):
        pass
    
    def do_something(self, param):
        """Do something useful"""
        # Your business logic
        return result
```

### Adding Utilities

**Validation** (`app/utils/validation.py`):
```python
def validate_my_input(value):
    """Validate my input"""
    if not value:
        return "Value is required"
    return None
```

**Permissions** (`app/utils/permissions.py`):
```python
def can_do_something():
    """Check if user can do something"""
    return is_manager()
```

## Testing

### Running Tests

```bash
# Run all tests
python tests/run_tests.py

# Run specific test file
python -m unittest tests.test_my_feature

# Run specific test
python -m unittest tests.test_my_feature.TestMyFeature.test_something
```

### Writing Tests

Create `tests/test_my_feature.py`:

```python
"""
Test my feature
"""
import unittest
from app import create_app


class TestMyFeature(unittest.TestCase):
    """Test my feature functionality"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.app = create_app()
        self.client = self.app.test_client()
    
    def test_my_feature(self):
        """Test my feature works"""
        response = self.client.get('/my-feature')
        self.assertEqual(response.status_code, 200)


if __name__ == '__main__':
    unittest.main()
```

### Test Coverage

Aim for tests covering:
- ✅ Authentication & authorization
- ✅ Route availability
- ✅ API endpoints
- ✅ Database operations
- ✅ Business logic in services
- ✅ Edge cases & error handling

## Database

### Connection

```python
from app.utils.db_utils import get_db

conn = get_db()  # Returns sqlite3.Connection with Row factory
cursor = conn.execute('SELECT * FROM table')
rows = cursor.fetchall()
```

### Queries

Always use parameterized queries:

```python
# ✅ GOOD
conn.execute('SELECT * FROM users WHERE id = ?', (user_id,))

# ❌ BAD (SQL injection risk)
conn.execute(f'SELECT * FROM users WHERE id = {user_id}')
```

### Transactions

```python
conn = get_db()
try:
    conn.execute('INSERT INTO ...')
    conn.execute('UPDATE ...')
    conn.commit()
except Exception as e:
    conn.rollback()
    raise
```

## Frontend Development

### Templates

Use Jinja2 template inheritance:

```html
{% extends "base.html" %}

{% block content %}
  <h1>{{ title }}</h1>
  <!-- Your content -->
{% endblock %}
```

### JavaScript

Use shared utilities:

```html
<!-- In your template -->
<script>
  // Use shared modal manager
  function showDetails(id) {
    viewPODetailsModal(id, 'PO-123');
  }
  
  // Use shared API client
  async function loadData() {
    const data = await apiCall('/api/my-endpoint');
    showSuccess('Data loaded!');
  }
</script>
```

### Styling

Use Tailwind CSS classes (already included in base.html):

```html
<button class="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700">
  Click Me
</button>
```

## Authentication & Authorization

### Decorators

```python
from app.utils.auth_utils import admin_required, employee_required, role_required

@bp.route('/admin-only')
@admin_required
def admin_only():
    pass

@bp.route('/employee-only')
@employee_required
def employee_only():
    pass

@bp.route('/manager-only')
@role_required('manager')
def manager_only():
    pass
```

### Permission Checking

```python
from app.utils.permissions import is_admin, is_manager, has_role

if is_manager():
    # Manager-specific logic
    pass

if has_role('warehouse'):
    # Warehouse-specific logic
    pass
```

## Debugging

### Flask Debug Mode

```python
# In app.py or set FLASK_DEBUG=1
if __name__ == '__main__':
    app = create_app()
    app.run(host='0.0.0.0', port=5001, debug=True)
```

### Logging

```python
from flask import current_app

current_app.logger.info('Info message')
current_app.logger.warning('Warning message')
current_app.logger.error('Error message')
```

### Debug Endpoints

Add temporary debug routes:

```python
@bp.route('/debug')
@admin_required
def debug():
    """Debug endpoint (remove before production)"""
    from flask import session
    return jsonify({
        'session': dict(session),
        'config': dict(current_app.config)
    })
```

## Git Workflow

### Branching

```bash
# Create feature branch
git checkout -b feature/my-feature

# Make changes
git add .
git commit -m "Add my feature"

# Push to remote
git push origin feature/my-feature

# Create pull request on GitHub
```

### Commit Messages

Follow conventional commits:

```bash
git commit -m "feat: add new feature"
git commit -m "fix: resolve bug"
git commit -m "docs: update documentation"
git commit -m "refactor: reorganize code"
git commit -m "test: add tests"
```

## Code Style

### Python (PEP 8)

```python
# ✅ GOOD
def my_function(param_one, param_two):
    """Function docstring."""
    my_variable = calculate_something()
    return my_variable

# ❌ BAD
def MyFunction(ParamOne,ParamTwo):
    MyVariable=CalculateSomething()
    return MyVariable
```

### Docstrings

```python
def my_function(param: str) -> dict:
    """
    Brief description.
    
    Longer description if needed.
    
    Args:
        param: Description of param
    
    Returns:
        Description of return value
    
    Raises:
        ValueError: When param is invalid
    """
    pass
```

## Deployment

### PythonAnywhere

See `docs/MIGRATION_V2.md` for detailed deployment instructions.

### Environment Variables

Set in PythonAnywhere or local `.env`:

```bash
FLASK_ENV=production
DATABASE_URL=sqlite:///database/tablet_counter.db
SECRET_KEY=your-secret-key
ADMIN_PASSWORD=your-admin-password
```

## Common Tasks

### Add New Route

1. Choose appropriate blueprint
2. Add route with decorator
3. Update template
4. Add navigation link
5. Write tests
6. Commit changes

### Modify Database

1. Create Alembic migration
2. Test migration (upgrade/downgrade)
3. Update model documentation
4. Update related queries
5. Write tests
6. Commit changes

### Fix Bug

1. Write test that reproduces bug
2. Fix the bug
3. Verify test passes
4. Run all tests
5. Commit with descriptive message

## Resources

- **Flask Documentation**: https://flask.palletsprojects.com/
- **Jinja2 Documentation**: https://jinja.palletsprojects.com/
- **Alembic Documentation**: https://alembic.sqlalchemy.org/
- **SQLite Documentation**: https://www.sqlite.org/docs.html
- **Tailwind CSS**: https://tailwindcss.com/docs

## Getting Help

1. Check `docs/ARCHITECTURE.md` for system overview
2. Review `docs/REFACTORV2_COMPLETE.md` for refactor details
3. Look at existing code for examples
4. Run tests to understand behavior
5. Check git history for context: `git log --oneline`

## Contributing

1. Follow naming conventions
2. Write tests for new features
3. Update documentation
4. Keep commits atomic and descriptive
5. Test locally before pushing
6. Create pull request with description

