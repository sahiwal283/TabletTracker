"""
TabletTracker Application Package
Main application factory and initialization

Note: This is the new modular structure. The old app.py still works for backward compatibility.
"""
from flask import Flask, request, session
from datetime import timedelta
from config import Config
from flask_babel import Babel

babel = Babel()


def get_locale():
    """Locale selector for Babel - matches the one in app.py"""
    # 1. Check if user explicitly chose a language
    if request.args.get('lang'):
        session['language'] = request.args.get('lang')
        session['manual_language_override'] = True
    
    # 2. Use session language if manually set
    if (session.get('manual_language_override') and 
        'language' in session and session['language'] in {'en', 'es'}):
        return session['language']
    
    # 3. Check employee's preferred language from database (if authenticated)
    if (session.get('employee_authenticated') and session.get('employee_id') and 
        not session.get('manual_language_override')):
        try:
            from app.utils.db_utils import db_query
            employee = db_query(
                'SELECT preferred_language FROM employees WHERE id = ?',
                (session.get('employee_id'),),
                fetch_one=True
            )
            if employee and employee.get('preferred_language') and employee['preferred_language'] in {'en', 'es'}:
                session['language'] = employee['preferred_language']
                return employee['preferred_language']
        except:
            pass
    
    # 4. Use session language if available
    if 'language' in session and session['language'] in {'en', 'es'}:
        return session['language']
    
    # 5. Use browser's preferred language if available
    fallback_lang = request.accept_languages.best_match(['en', 'es']) or 'en'
    session['language'] = fallback_lang
    return fallback_lang


def create_app(config_class=Config):
    """Application factory pattern"""
    app = Flask(__name__)
    app.config.from_object(config_class)
    app.secret_key = config_class.SECRET_KEY
    
    # Configure Babel for internationalization
    app.config['LANGUAGES'] = {
        'en': 'English',
        'es': 'Español'
    }
    app.config['BABEL_DEFAULT_LOCALE'] = 'en'
    app.config['BABEL_DEFAULT_TIMEZONE'] = 'UTC'
    
    # Initialize Babel with locale selector
    babel.init_app(app, locale_selector=get_locale)
    
    # Configure session settings for production security
    if config_class.ENV == 'production':
        app.config['SESSION_COOKIE_SECURE'] = True
        app.config['SESSION_COOKIE_HTTPONLY'] = True
        app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    
    # Set permanent session lifetime
    app.permanent_session_lifetime = timedelta(seconds=config_class.PERMANENT_SESSION_LIFETIME)
    
    # Register blueprints (commented out until routes are migrated)
    # from app.blueprints import auth, dashboard, submissions, purchase_orders, admin, production, shipping, api
    # app.register_blueprint(auth.bp)
    # app.register_blueprint(dashboard.bp)
    # app.register_blueprint(submissions.bp)
    # app.register_blueprint(purchase_orders.bp)
    # app.register_blueprint(admin.bp)
    # app.register_blueprint(production.bp)
    # app.register_blueprint(shipping.bp)
    # app.register_blueprint(api.bp)
    
    # Register error handlers
    @app.errorhandler(404)
    def not_found_error(error):
        if config_class.ENV == 'production':
            from flask import render_template
            return render_template('base.html'), 404
        return str(error), 404
    
    @app.errorhandler(500)
    def internal_error(error):
        if config_class.ENV == 'production':
            from flask import render_template
            return render_template('base.html'), 500
        return str(error), 500
    
    # Security headers for production
    @app.after_request
    def after_request(response):
        if config_class.ENV == 'production':
            response.headers['X-Content-Type-Options'] = 'nosniff'
            response.headers['X-Frame-Options'] = 'DENY'
            response.headers['X-XSS-Protection'] = '1; mode=block'
            response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        return response
    
    return app

