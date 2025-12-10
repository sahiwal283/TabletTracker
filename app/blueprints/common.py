"""
Common imports and utilities for all blueprints
This ensures consistent imports across all blueprint files
"""
from flask import render_template, request, jsonify, redirect, url_for, flash, session, make_response
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import sqlite3
import json
import os
import requests
import hashlib
import re
import traceback
import csv
import io
from functools import wraps
from config import Config
from app.services.zoho_service import zoho_api
from __version__ import __version__, __title__, __description__
from app.services.tracking_service import refresh_shipment_row
from app.services.report_service import ProductionReportGenerator
from app.utils.db_utils import get_db
from app.utils.auth_utils import admin_required, role_required, employee_required, verify_password, hash_password, get_employee_role, has_permission, ROLE_PERMISSIONS
from app.models.database import init_db
from app.models.schema import SchemaManager
from app.models.migrations import MigrationRunner

# Helper functions from app.py that routes depend on
def get_setting(setting_key, default_value=None):
    """Get a setting value from app_settings table"""
    from app.utils.db_utils import db_query
    result = db_query(
        'SELECT setting_value FROM app_settings WHERE setting_key = ?',
        (setting_key,),
        fetch_one=True
    )
    if result:
        return result['setting_value']
    return default_value

def ensure_app_settings_table():
    """Ensure app_settings table exists"""
    from app.models.database import init_db
    init_db()  # This will ensure all tables exist

def ensure_submission_type_column():
    """Ensure submission_type column exists"""
    from app.models.database import init_db
    init_db()  # Migrations handle this

def ensure_machine_counts_table():
    """Ensure machine_counts table exists"""
    from app.models.database import init_db
    init_db()  # Migrations handle this

def ensure_machine_count_columns():
    """Ensure machine count columns exist"""
    from app.models.database import init_db
    init_db()  # Migrations handle this

