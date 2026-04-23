"""
Receiving and Shipping API routes.

This package handles all receiving, shipping, and bag-related endpoints.
"""

from flask import Blueprint

bp = Blueprint("api_receiving", __name__)

from . import (  # noqa: F401, E402
    routes_bags_zoho,
    routes_receive_shipments,
    routes_receiving_bulk,
    routes_receiving_pages,
)
