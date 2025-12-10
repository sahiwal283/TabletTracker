#!/usr/bin/env python3
"""
Route migration script - extracts routes from app.py and creates blueprint files
"""
import re
import os

# Route to blueprint mapping
ROUTE_MAPPING = {
    'purchase_orders': {
        'blueprint': 'purchase_orders',
        'routes': ['/purchase_orders']
    },
    'admin': {
        'blueprint': 'admin',
        'routes': ['/admin', '/admin/login', '/admin/logout', '/admin/products', '/admin/tablet_types', '/admin/shipments', '/admin/employees']
    },
    'shipping': {
        'blueprint': 'shipping',
        'routes': ['/shipping', '/shipments', '/receiving', '/receiving/debug']
    },
    'api': {
        'blueprint': 'api',
        'routes': ['/api/']  # All /api/* routes
    }
}

def extract_route_function(app_py_content, route_path):
    """Extract a route function from app.py content"""
    # Find the route decorator
    pattern = rf"@app\.route\(['\"]{re.escape(route_path)}['\"][^)]*\)\s*\n\s*@?\w+.*?\n\s*def\s+(\w+)\([^)]*\):"
    match = re.search(pattern, app_py_content, re.MULTILINE | re.DOTALL)
    
    if not match:
        return None
    
    func_name = match.group(1)
    func_start = match.start()
    
    # Find the function end (next @app.route or end of file)
    next_route = re.search(r'@app\.route\(', app_py_content[func_start + 100:])
    if next_route:
        func_end = func_start + 100 + next_route.start()
    else:
        func_end = len(app_py_content)
    
    # Extract function code
    func_code = app_py_content[func_start:func_end]
    
    # Convert to blueprint format
    func_code = func_code.replace('@app.route', '@bp.route')
    
    return func_code

def main():
    print("Route migration script")
    print("This script helps extract routes from app.py")
    print("Routes should be manually migrated to ensure correctness")
    
if __name__ == '__main__':
    main()

