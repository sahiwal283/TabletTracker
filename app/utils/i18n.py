"""
Internationalization utilities
"""

from flask import session, request, current_app
from ..models.database import get_db

def get_locale():
    """Determine the best language for the current user"""
    # 1. Check if user explicitly chose a language (manual override - highest priority)
    if request.args.get('lang'):
        new_lang = request.args.get('lang')
        if new_lang in current_app.config['LANGUAGES']:
            session['language'] = new_lang
            session['manual_language_override'] = True  # Mark as manual choice
            session.permanent = True
            return new_lang
    
    # 2. Use session language if available (manual or employee-set)
    if 'language' in session and session['language'] in current_app.config['LANGUAGES']:
        return session['language']
    
    # 3. Use employee's preferred language if logged in and no manual override
    if (session.get('employee_authenticated') and session.get('employee_id') and 
        not session.get('manual_language_override')):
        try:
            conn = get_db()
            employee = conn.execute('''
                SELECT preferred_language FROM employees WHERE id = ?
            ''', (session.get('employee_id'),)).fetchone()
            if employee and employee['preferred_language'] and employee['preferred_language'] in current_app.config['LANGUAGES']:
                session['language'] = employee['preferred_language']
                conn.close()
                return employee['preferred_language']
            conn.close()
        except:
            pass  # Continue to fallback if database query fails
    
    # 4. Use browser's preferred language if available
    fallback_lang = request.accept_languages.best_match(current_app.config['LANGUAGES'].keys()) or current_app.config['BABEL_DEFAULT_LOCALE']
    session['language'] = fallback_lang
    return fallback_lang
