"""
Warehouse operations blueprint
"""

from flask import Blueprint

bp = Blueprint('warehouse', __name__)

from . import routes
