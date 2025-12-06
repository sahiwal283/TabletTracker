#!/usr/bin/env python3
"""
Test imports without database initialization
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

print("Testing imports WITHOUT database initialization...")
print("=" * 70)

# Test 1: Import create_app
print("\n1. Importing create_app...")
try:
    from app import create_app
    print("   ✅ create_app imported")
except Exception as e:
    print(f"   ❌ Failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Test 2: Import blueprints
print("\n2. Testing blueprint imports...")
try:
    from app.blueprints import auth, dashboard, submissions, purchase_orders, admin, production, shipping, api
    print("   ✅ All blueprints imported")
except Exception as e:
    print(f"   ❌ Failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Test 3: Create app WITHOUT database initialization
print("\n3. Creating Flask app (this will try to init DB)...")
print("   ⚠️  If this hangs, database initialization is the problem")

# Monkey-patch to skip database init
original_init_db = None
try:
    from app.models import database
    original_init_db = database.init_db
    
    def mock_init_db():
        print("   ⏭️  Skipping database initialization (for testing)")
        pass
    
    database.init_db = mock_init_db
    
    app = create_app()
    print(f"   ✅ Flask app created!")
    print(f"   ✅ Blueprints registered: {len(app.blueprints)}")
    if len(app.blueprints) > 0:
        print(f"   ✅ Blueprint names: {', '.join(app.blueprints.keys())}")
    
    # Restore original
    database.init_db = original_init_db
    
except Exception as e:
    print(f"   ❌ Failed: {e}")
    import traceback
    traceback.print_exc()
    if original_init_db:
        database.init_db = original_init_db
    sys.exit(1)

print("\n" + "=" * 70)
print("✅ Test completed! If this worked, database init is the issue.")
print("=" * 70)

