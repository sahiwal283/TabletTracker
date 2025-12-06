#!/usr/bin/env python3
"""
Step-by-step import test to find where it hangs
"""
import sys
import os
import signal

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def timeout_handler(signum, frame):
    raise TimeoutError("Operation timed out")

# Set a 10 second timeout
signal.signal(signal.SIGALRM, timeout_handler)

print("=" * 70)
print("Step-by-Step Import Test")
print("=" * 70)
print()

# Step 1: Basic imports
print("Step 1: Testing Flask import...")
try:
    signal.alarm(5)
    from flask import Flask
    signal.alarm(0)
    print("   ✅ Flask imported")
except TimeoutError:
    print("   ❌ TIMEOUT: Flask import hung")
    sys.exit(1)
except Exception as e:
    print(f"   ❌ Flask import failed: {e}")
    sys.exit(1)

# Step 2: Config import
print("\nStep 2: Testing Config import...")
try:
    signal.alarm(5)
    from config import Config
    signal.alarm(0)
    print("   ✅ Config imported")
except TimeoutError:
    print("   ❌ TIMEOUT: Config import hung")
    sys.exit(1)
except Exception as e:
    print(f"   ❌ Config import failed: {e}")
    sys.exit(1)

# Step 3: Import create_app function (don't call it yet)
print("\nStep 3: Testing create_app import (not calling)...")
try:
    signal.alarm(5)
    from app import create_app
    signal.alarm(0)
    print("   ✅ create_app function imported")
except TimeoutError:
    print("   ❌ TIMEOUT: create_app import hung")
    sys.exit(1)
except Exception as e:
    print(f"   ❌ create_app import failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Step 4: Test blueprint imports individually
print("\nStep 4: Testing blueprint imports...")
blueprints = ['auth', 'dashboard', 'submissions', 'purchase_orders', 'admin', 'production', 'shipping', 'api']
for bp_name in blueprints:
    try:
        signal.alarm(5)
        module = __import__(f'app.blueprints.{bp_name}', fromlist=[bp_name])
        bp = getattr(module, 'bp', None)
        signal.alarm(0)
        if bp:
            print(f"   ✅ {bp_name}")
        else:
            print(f"   ⚠️  {bp_name} (no bp attribute)")
    except TimeoutError:
        print(f"   ❌ TIMEOUT: {bp_name} import hung")
        sys.exit(1)
    except Exception as e:
        print(f"   ❌ {bp_name} failed: {e}")
        import traceback
        traceback.print_exc()

# Step 5: Test database initialization separately
print("\nStep 5: Testing database initialization...")
try:
    signal.alarm(10)
    from app.models.database import init_db
    print("   ✅ init_db imported")
    
    print("   🔄 Calling init_db()...")
    signal.alarm(30)  # Give it 30 seconds for database init
    init_db()
    signal.alarm(0)
    print("   ✅ Database initialization completed")
except TimeoutError:
    print("   ❌ TIMEOUT: Database initialization hung (this is likely the problem!)")
    print("   💡 Try: Check if database file is locked or corrupted")
    sys.exit(1)
except Exception as e:
    print(f"   ⚠️  Database initialization error: {e}")
    import traceback
    traceback.print_exc()

# Step 6: Now try creating the app
print("\nStep 6: Testing Flask app creation...")
try:
    signal.alarm(30)
    app = create_app()
    signal.alarm(0)
    print(f"   ✅ Flask app created successfully")
    print(f"   ✅ Blueprints registered: {len(app.blueprints)}")
    if len(app.blueprints) > 0:
        print(f"   ✅ Blueprint names: {', '.join(app.blueprints.keys())}")
except TimeoutError:
    print("   ❌ TIMEOUT: App creation hung")
    print("   💡 This suggests database initialization is the issue")
    sys.exit(1)
except Exception as e:
    print(f"   ❌ App creation failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\n" + "=" * 70)
print("✅ All tests passed!")
print("=" * 70)

