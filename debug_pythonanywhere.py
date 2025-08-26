#!/usr/bin/env python3
"""
Emergency diagnostic script for PythonAnywhere deployment
Run this in PythonAnywhere console to identify the issue
"""

import sys
import os
import traceback

def main():
    print("=== PythonAnywhere Diagnostic Tool ===")
    print(f"Python version: {sys.version}")
    print(f"Current directory: {os.getcwd()}")
    print()
    
    # Check if we're in the right directory
    expected_files = ['app.py', '__version__.py', 'requirements.txt']
    print("Checking for required files:")
    for file in expected_files:
        exists = os.path.exists(file)
        print(f"  {file}: {'✅' if exists else '❌'}")
    print()
    
    # Try to import the app
    print("Testing app import...")
    try:
        sys.path.insert(0, os.getcwd())
        from app import app
        print("✅ App imported successfully")
        
        # Check version
        try:
            from __version__ import __version__
            print(f"✅ Version: {__version__}")
        except Exception as e:
            print(f"❌ Version import error: {e}")
        
        # Test basic app functionality
        with app.app_context():
            print("✅ App context working")
            
            # Test database
            try:
                from app import get_db
                conn = get_db()
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
                tables = [row[0] for row in cursor.fetchall()]
                print(f"✅ Database accessible. Tables: {len(tables)}")
                print(f"  Tables: {', '.join(tables[:5])}{'...' if len(tables) > 5 else ''}")
                conn.close()
            except Exception as e:
                print(f"❌ Database error: {e}")
                traceback.print_exc()
        
    except Exception as e:
        print(f"❌ App import failed: {e}")
        traceback.print_exc()
        return False
    
    print("\n=== Recommendations ===")
    print("1. Run: git pull origin main")
    print("2. Check WSGI file points to correct path")
    print("3. Reload web app")
    print("4. Check error logs at:")
    print("   - sahilk1.pythonanywhere.com.error.log")
    print("   - sahilk1.pythonanywhere.com.server.log")
    
    return True

if __name__ == "__main__":
    main()