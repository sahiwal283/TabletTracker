# Template Layouts

This directory contains intermediate base templates for specific sections of the application.

## Available Layouts

### `admin_base.html` (Future)
Extended base template for admin-specific pages with:
- Admin navigation
- Admin-specific styling
- Admin utilities

### `dashboard_base.html` (Future)
Extended base template for dashboard pages with:
- Dashboard widgets
- Common dashboard components
- Dashboard-specific scripts

## Usage

Templates in specific feature folders should extend these layouts:

```jinja2
{% extends "layouts/admin_base.html" %}
{% block page_content %}
  <!-- Admin page content -->
{% endblock %}
```

## Note

Currently, all templates extend `base.html` directly. These intermediate layouts can be created as needed for specific sections of the application to reduce duplication.

