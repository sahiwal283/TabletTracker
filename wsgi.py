#!/usr/bin/env python3
"""
WSGI configuration for PythonAnywhere deployment
"""

import sys
import os

# Add your project directory to the sys.path
# Update the path below with your actual PythonAnywhere username
path = '/home/sahilk1/TabletTracker'  # Update this with your actual username
if path not in sys.path:
    sys.path.insert(0, path)

# Change to the project directory
os.chdir(path)

# Import and create Flask application using factory pattern
try:
    from app import create_app
    application = create_app()
except ImportError:
    # Fallback: if app package doesn't work, try importing from app.py directly
    # This handles the case where the old app.py is still being used
    import app as app_module
    application = app_module.app

if __name__ == "__main__":
    application.run()
