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
    print(f"✅ Flask app created with {len(application.blueprints)} blueprints registered")
except Exception as e:
    # Log the error and raise it - don't fall back to old app.py
    import traceback
    error_msg = f"❌ CRITICAL: Failed to create Flask app: {str(e)}\n{traceback.format_exc()}"
    print(error_msg)
    raise

if __name__ == "__main__":
    application.run()
