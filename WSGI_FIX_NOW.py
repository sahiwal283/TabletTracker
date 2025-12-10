#!/usr/bin/env python3
"""
WSGI configuration for PythonAnywhere deployment
COPY THIS ENTIRE FILE TO YOUR PYTHONANYWHERE WSGI FILE
"""

import sys
import os

# Add your project directory to the sys.path
path = '/home/sahilk1/TabletTracker'
if path not in sys.path:
    sys.path.insert(0, path)

# Change to the project directory
os.chdir(path)

# Import and create Flask application using factory pattern
try:
    from app import create_app
    application = create_app()
    print(f"✅ Flask app created successfully")
except Exception as e:
    # Log the error and raise it
    import traceback
    error_msg = f"❌ CRITICAL: Failed to create Flask app: {str(e)}\n{traceback.format_exc()}"
    print(error_msg)
    raise

