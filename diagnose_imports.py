#!/usr/bin/env python3
"""
Diagnostic script to test imports and identify issues
Run this on PythonAnywhere to see what's failing
"""
import sys
import os

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

print("=" * 70)
print("Import Diagnostic Script")
print("=" * 70)
print()

# Test 1: Basic imports
print("1. Testing basic imports...")
try:
    from flask import Flask
    print("   ✅ Flask imported")
except Exception as e:
    print(f"   ❌ Flask import failed: {e}")
    sys.exit(1)

try:
    from config import Config
    print("   ✅ Config imported")
except Exception as e:
    print(f"   ❌ Config import failed: {e}")
    sys.exit(1)

# Test 2: App package import
print("\n2. Testing app package import...")
try:
    from app import create_app
    print("   ✅ create_app imported successfully")
except Exception as e:
    print(f"   ❌ Failed to import create_app: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Test 3: Blueprint imports
print("\n3. Testing blueprint imports...")
blueprints_to_test = ['auth', 'dashboard', 'submissions', 'purchase_orders', 'admin', 'production', 'shipping', 'api']
for bp_name in blueprints_to_test:
    try:
        module = __import__(f'app.blueprints.{bp_name}', fromlist=[bp_name])
        bp = getattr(module, 'bp', None)
        if bp:
            print(f"   ✅ {bp_name} blueprint imported (name: {bp.name})")
        else:
            print(f"   ⚠️  {bp_name} module imported but no 'bp' attribute found")
    except Exception as e:
        print(f"   ❌ Failed to import {bp_name} blueprint: {e}")
        import traceback
        traceback.print_exc()

# Test 4: Create Flask app
print("\n4. Testing Flask app creation...")
try:
    app = create_app()
    print(f"   ✅ Flask app created successfully")
    print(f"   ✅ App name: {app.name}")
    print(f"   ✅ Registered blueprints: {len(app.blueprints)}")
    if len(app.blueprints) > 0:
        print(f"   ✅ Blueprint names: {', '.join(app.blueprints.keys())}")
    else:
        print("   ⚠️  WARNING: No blueprints registered!")
except Exception as e:
    print(f"   ❌ Failed to create Flask app: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Test 5: Database initialization
print("\n5. Testing database initialization...")
try:
    from app.models.database import init_db
    init_db()
    print("   ✅ Database initialization completed")
except Exception as e:
    print(f"   ⚠️  Database initialization warning: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 70)
print("✅ All diagnostic tests completed!")
print("=" * 70)

