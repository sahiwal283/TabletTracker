"""
TabletTracker Application Factory
Modular Flask application with blueprint-based architecture
"""

from flask import Flask
from flask_babel import Babel
from datetime import timedelta
import os

from .config import Config
from .models import init_db
from .utils.decorators import setup_error_handlers
from .utils.i18n import get_locale

def create_app(config_class=Config):
    """Application factory pattern for Flask app creation"""
    
    # Create Flask app
    app = Flask(__name__)
    app.config.from_object(config_class)
    app.secret_key = config_class.SECRET_KEY
    
    # Configure internationalization
    app.config['LANGUAGES'] = {
        'en': 'English',
        'es': 'Español'
    }
    app.config['BABEL_DEFAULT_LOCALE'] = 'en'
    app.config['BABEL_DEFAULT_TIMEZONE'] = 'UTC'
    
    # Initialize extensions
    babel = Babel()
    babel.init_app(app, locale_selector=get_locale)
    
    # Configure session settings for production
    if config_class.ENV == 'production':
        app.config['SESSION_COOKIE_SECURE'] = True
        app.config['SESSION_COOKIE_HTTPONLY'] = True
        app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    
    # Set permanent session lifetime
    app.permanent_session_lifetime = timedelta(seconds=config_class.PERMANENT_SESSION_LIFETIME)
    
    # Initialize database
    with app.app_context():
        init_db()
    
    # Register blueprints
    from .auth import bp as auth_bp
    app.register_blueprint(auth_bp)
    
    from .admin import bp as admin_bp
    app.register_blueprint(admin_bp, url_prefix='/admin')
    
    from .warehouse import bp as warehouse_bp
    app.register_blueprint(warehouse_bp, url_prefix='/warehouse')
    
    from .api import bp as api_bp
    app.register_blueprint(api_bp, url_prefix='/api')
    
    from .dashboard import bp as dashboard_bp
    app.register_blueprint(dashboard_bp, url_prefix='/dashboard')
    
    from .shipping import bp as shipping_bp
    app.register_blueprint(shipping_bp, url_prefix='/shipping')
    
    # Register error handlers
    setup_error_handlers(app)
    
    # Template context processors
    @app.context_processor
    def inject_version():
        """Make version and language info available to all templates"""
        from .__version__ import __version__, __title__, __description__
        from .utils.i18n import get_locale
        from flask_babel import gettext, ngettext
        
        return {
            'version': lambda: __version__,
            'app_title': __title__,
            'app_description': __description__,
            'current_language': get_locale(),
            'languages': app.config['LANGUAGES'],
            'gettext': gettext,
            'ngettext': ngettext
        }
    
    return app
