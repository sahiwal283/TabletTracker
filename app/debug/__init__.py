"""
Debug and diagnostic routes
"""

from flask import Blueprint

bp = Blueprint('debug', __name__)

from . import routes
