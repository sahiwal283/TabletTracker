#!/usr/bin/env python3
"""
WSGI entry for production (PythonAnywhere, gunicorn, Docker).

Set TABLETTRACKER_ROOT to the project directory if wsgi.py is not at the repo root.
"""

import os
import sys

PROJECT_ROOT = os.environ.get("TABLETTRACKER_ROOT", os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

try:
    from app import create_app

    application = create_app()
    print(
        f"✅ Flask app created successfully with {len(application.blueprints)} blueprints registered"
    )
    if len(application.blueprints) == 0:
        print("⚠️  WARNING: No blueprints registered! Check blueprint imports.")
except Exception as e:
    import traceback

    error_msg = f"❌ CRITICAL: Failed to create Flask app: {str(e)}\n{traceback.format_exc()}"
    print(error_msg)
    raise

if __name__ == "__main__":
    application.run()
