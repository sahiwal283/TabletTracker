#!/usr/bin/env python3
"""
Auto-versioning script for TabletTracker
Automatically increments version numbers and creates safety tags
"""

import re
import os
import subprocess
import sys
from datetime import datetime

def run_command(cmd, check=True):
    """Run shell command and return output"""
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, check=check)
        return result.stdout.strip(), result.stderr.strip()
    except subprocess.CalledProcessError as e:
        if check:
            raise
        return e.stdout.strip(), e.stderr.strip()

def get_current_version():
    """Get current version from __version__.py"""
    try:
        with open('__version__.py', 'r') as f:
            content = f.read()
        
        match = re.search(r'__version__ = ["\']([^"\']+)["\']', content)
        if match:
            return match.group(1)
        else:
            return "1.0.0"
    except FileNotFoundError:
        return "1.0.0"

def increment_version(version, increment_type='patch'):
    """Increment version number (major.minor.patch)"""
    parts = version.split('.')
    if len(parts) != 3:
        return "1.0.0"
    
    major, minor, patch = map(int, parts)
    
    if increment_type == 'major':
        major += 1
        minor = 0
        patch = 0
    elif increment_type == 'minor':
        minor += 1
        patch = 0
    else:  # patch
        patch += 1
    
    return f"{major}.{minor}.{patch}"

def update_version_file(new_version):
    """Update __version__.py with new version"""
    try:
        with open('__version__.py', 'r') as f:
            content = f.read()
        
        # Update version
        content = re.sub(
            r'__version__ = ["\'][^"\']+["\']',
            f'__version__ = "{new_version}"',
            content
        )
        
        with open('__version__.py', 'w') as f:
            f.write(content)
        
        return True
    except Exception as e:
        print(f"❌ Error updating version file: {e}")
        return False

def create_safety_commit(version, message=""):
    """Create commit and safety tag"""
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    
    # Add all changes
    run_command("git add -A")
    
    # Create commit
    if message:
        commit_msg = f"feat: version {version} - {message}"
    else:
        commit_msg = f"feat: version {version} - auto-versioned release"
    
    run_command(f'git commit -m "{commit_msg}"')
    
    # Create safety tag
    safety_tag = f"v{version}-safe-{timestamp}"
    run_command(f'git tag -a {safety_tag} -m "SAFETY: Version {version} deployed at {timestamp}"')
    
    return safety_tag

def main():
    """Main auto-versioning function"""
    print("🔧 TabletTracker Auto-Versioning Tool")
    print("=" * 50)
    
    # Check if we're in git repo
    stdout, stderr = run_command("git status", check=False)
    if "not a git repository" in stderr:
        print("❌ Not in a git repository!")
        sys.exit(1)
    
    # Get current version
    current_version = get_current_version()
    print(f"📋 Current version: {current_version}")
    
    # Get increment type from command line args
    increment_type = 'patch'  # default
    commit_message = ""
    
    if len(sys.argv) > 1:
        if sys.argv[1] in ['major', 'minor', 'patch']:
            increment_type = sys.argv[1]
        else:
            commit_message = ' '.join(sys.argv[1:])
    
    if len(sys.argv) > 2 and sys.argv[1] in ['major', 'minor', 'patch']:
        commit_message = ' '.join(sys.argv[2:])
    
    # Calculate new version
    new_version = increment_version(current_version, increment_type)
    print(f"🚀 New version: {new_version}")
    
    # Update version file
    if not update_version_file(new_version):
        sys.exit(1)
    
    print(f"✅ Updated __version__.py to {new_version}")
    
    # Create safety commit and tag
    try:
        safety_tag = create_safety_commit(new_version, commit_message)
        print(f"✅ Created commit and safety tag: {safety_tag}")
        
        # Push to remote
        run_command("git push origin main")
        run_command(f"git push origin {safety_tag}")
        print("✅ Pushed to remote repository")
        
        print("\n🎉 SUCCESS!")
        print(f"📦 Version {new_version} deployed with safety tag {safety_tag}")
        print("\nTo rollback if needed:")
        print(f"  git checkout {safety_tag}")
        print(f"  git checkout -b rollback-{new_version}")
        print(f"  git push origin rollback-{new_version}")
        
        return True
        
    except Exception as e:
        print(f"❌ Error during commit/push: {e}")
        return False

if __name__ == "__main__":
    print("Usage:")
    print("  python3 auto_version.py                    # Patch increment")
    print("  python3 auto_version.py minor              # Minor increment") 
    print("  python3 auto_version.py major              # Major increment")
    print("  python3 auto_version.py 'custom message'   # Patch with message")
    print("  python3 auto_version.py minor 'message'    # Minor with message")
    print()
    
    if main():
        print("\n✅ Auto-versioning completed successfully!")
    else:
        print("\n❌ Auto-versioning failed!")
        sys.exit(1)