"""
TabletTracker application factory
"""
from flask import Flask, render_template, request, session, jsonify
from datetime import timedelta
from flask_babel import Babel
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from config import Config


def create_app(config_class=Config):
    """Application factory function"""
    app = Flask(__name__, 
                template_folder='../templates',
                static_folder='../static')
    
    # Load configuration
    app.config.from_object(config_class)
    app.secret_key = config_class.SECRET_KEY
    
    # Configure Babel for internationalization
    app.config['LANGUAGES'] = {
        'en': 'English',
        'es': 'Español'
    }
    app.config['BABEL_DEFAULT_LOCALE'] = 'en'
    app.config['BABEL_DEFAULT_TIMEZONE'] = 'UTC'
    
    # Babel locale selector
    def get_locale():
        from app.utils.db_utils import get_db
        
        # 1. Check if user explicitly chose a language
        if request.args.get('lang'):
            session['language'] = request.args.get('lang')
            session['manual_language_override'] = True
        
        # 2. Use session language if manually set
        if (session.get('manual_language_override') and 
            'language' in session and session['language'] in app.config['LANGUAGES']):
            return session['language']
        
        # 3. Check employee's preferred language from database (if authenticated)
        if (session.get('employee_authenticated') and session.get('employee_id') and 
            not session.get('manual_language_override')):
            conn = None
            try:
                conn = get_db()
                employee = conn.execute('''
                    SELECT preferred_language FROM employees WHERE id = ?
                ''', (session.get('employee_id'),)).fetchone()
                if employee and employee['preferred_language'] and employee['preferred_language'] in app.config['LANGUAGES']:
                    session['language'] = employee['preferred_language']
                    return employee['preferred_language']
            except Exception as e:
                pass
            finally:
                if conn:
                    try:
                        conn.close()
                    except:
                        pass
        
        # 4. Use session language if available
        if 'language' in session and session['language'] in app.config['LANGUAGES']:
            return session['language']
        
        # 5. Use browser's preferred language if available
        fallback_lang = request.accept_languages.best_match(app.config['LANGUAGES'].keys()) or app.config['BABEL_DEFAULT_LOCALE']
        session['language'] = fallback_lang
        return fallback_lang
    
    # Initialize Babel
    babel = Babel()
    babel.init_app(app, locale_selector=get_locale)
    
    # Initialize CSRF Protection
    csrf = CSRFProtect()
    csrf.init_app(app)
    
    # Initialize Rate Limiting (disabled for login routes - using failed attempt tracking instead)
    limiter = Limiter(
        app=app,
        key_func=get_remote_address,
        default_limits=["1000 per day", "200 per hour"],
        storage_uri="memory://",
        enabled=False  # Disabled to prevent false positives on first login
    )
    
    # Configure session settings for production security
    if config_class.ENV == 'production':
        app.config['SESSION_COOKIE_SECURE'] = True
        app.config['SESSION_COOKIE_HTTPONLY'] = True
        app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    
    # Set permanent session lifetime
    app.permanent_session_lifetime = timedelta(seconds=config_class.PERMANENT_SESSION_LIFETIME)
    
    # Production error handling
    @app.errorhandler(404)
    def not_found_error(error):
        # Return JSON for API routes
        if request.path.startswith('/api/'):
            return jsonify({'success': False, 'error': 'Resource not found'}), 404
        if config_class.ENV == 'production':
            return render_template('base.html'), 404
        return str(error), 404
    
    @app.errorhandler(500)
    def internal_error(error):
        # Return JSON for API routes
        if request.path.startswith('/api/'):
            import traceback
            error_msg = str(error)
            if config_class.ENV != 'production':
                # Include traceback in development
                error_msg = f"{error_msg}\n{traceback.format_exc()}"
            return jsonify({'success': False, 'error': f'Internal server error: {error_msg}'}), 500
        if config_class.ENV == 'production':
            return render_template('base.html'), 500
        return str(error), 500
    
    # Security headers (apply to all environments)
    @app.after_request
    def after_request(response):
        # Always apply these security headers
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['X-XSS-Protection'] = '1; mode=block'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response.headers['Permissions-Policy'] = 'geolocation=(), microphone=(), camera=()'
        
        # Content Security Policy
        csp = "default-src 'self'; " \
              "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.tailwindcss.com https://unpkg.com; " \
              "style-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com; " \
              "img-src 'self' data: https:; " \
              "font-src 'self' data:; " \
              "connect-src 'self'; " \
              "frame-ancestors 'none';"
        response.headers['Content-Security-Policy'] = csp
        
        # Additional production-only headers
        if config_class.ENV == 'production':
            response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains; preload'
        
        return response
    
    # Register Blueprints
    from app.blueprints import auth, admin, dashboard, production, submissions, purchase_orders, receiving, api as api_bp
    
    app.register_blueprint(auth.bp)
    app.register_blueprint(admin.bp)
    app.register_blueprint(dashboard.bp)
    app.register_blueprint(production.bp)
    app.register_blueprint(submissions.bp)
    app.register_blueprint(purchase_orders.bp)
    app.register_blueprint(receiving.bp)
    app.register_blueprint(api_bp.bp)
    
    return app
