"""
Flask blueprints for route organization
"""
# Export all blueprints so they can be imported from app.blueprints
from app.blueprints import auth
from app.blueprints import dashboard
from app.blueprints import submissions
from app.blueprints import purchase_orders
from app.blueprints import admin
from app.blueprints import production
from app.blueprints import shipping
from app.blueprints import api

__all__ = ['auth', 'dashboard', 'submissions', 'purchase_orders', 'admin', 'production', 'shipping', 'api']

