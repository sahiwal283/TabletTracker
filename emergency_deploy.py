#!/usr/bin/env python3
"""
Emergency deployment script for PythonAnywhere
Forces update to latest working version
"""

import subprocess
import os
import sys

def run_cmd(cmd, description=""):
    """Run command and print output"""
    print(f"🔧 {description}")
    print(f"Running: {cmd}")
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, check=True)
        if result.stdout.strip():
            print(f"✅ {result.stdout.strip()}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ Error: {e}")
        if e.stdout:
            print(f"stdout: {e.stdout}")
        if e.stderr:
            print(f"stderr: {e.stderr}")
        return False

def main():
    print("🚨 EMERGENCY DEPLOYMENT TO PYTHONANYWHERE")
    print("=" * 50)
    
    # Check current directory
    print(f"📁 Current directory: {os.getcwd()}")
    
    # 1. Force reset to latest
    print("\n1️⃣ FORCE RESET TO LATEST VERSION")
    if not run_cmd("git fetch origin", "Fetching latest from GitHub"):
        return False
    
    if not run_cmd("git reset --hard origin/main", "Hard reset to origin/main"):
        return False
    
    if not run_cmd("git clean -fd", "Cleaning working directory"):
        return False
    
    # 2. Check version
    print("\n2️⃣ CHECKING VERSION")
    run_cmd("python3 -c \"from __version__ import __version__; print(f'Version: {__version__}')\"", "Reading version")
    
    # 3. Install/upgrade dependencies
    print("\n3️⃣ UPDATING DEPENDENCIES")
    run_cmd("pip install -r requirements.txt --upgrade", "Installing/upgrading packages")
    
    # 4. Check database
    print("\n4️⃣ CHECKING DATABASE")
    run_cmd("python3 -c \"import sqlite3; print('DB tables:', [r[0] for r in sqlite3.connect('tablettracker.db').execute('SELECT name FROM sqlite_master WHERE type=\\'table\\'').fetchall()])\"", "Checking database tables")
    
    # 5. Run diagnostic
    print("\n5️⃣ RUNNING DIAGNOSTIC")
    if os.path.exists('debug_pythonanywhere.py'):
        run_cmd("python3 debug_pythonanywhere.py", "Running diagnostic script")
    
    # 6. Create sample data if needed
    print("\n6️⃣ CREATING SAMPLE DATA")
    if os.path.exists('create_sample_shipments.py'):
        run_cmd("python3 create_sample_shipments.py", "Creating sample shipments")
    
    print("\n🎉 EMERGENCY DEPLOYMENT COMPLETE!")
    print("\nNEXT STEPS:")
    print("1. Go to PythonAnywhere Web tab")
    print("2. Click 'Reload sahilk1.pythonanywhere.com'")
    print("3. Check error logs if still broken:")
    print("   - sahilk1.pythonanywhere.com.error.log")
    print("   - sahilk1.pythonanywhere.com.server.log")
    
    return True

if __name__ == "__main__":
    if main():
        print("\n✅ Script completed successfully")
    else:
        print("\n❌ Script failed")
        sys.exit(1)