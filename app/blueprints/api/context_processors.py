"""
API routes - all /api/* endpoints
"""

from flask import current_app
from flask_babel import get_locale, gettext, ngettext

from app.utils.version_display import read_version_constants

from . import bp


@bp.app_context_processor
def inject_version():
    """Make version information available to all templates"""
    meta = read_version_constants()
    locale = get_locale()
    # Convert Locale object to string if needed
    current_lang = str(locale) if hasattr(locale, 'language') else locale
    return {
        'version': lambda: meta['__version__'],
        'app_title': meta['__title__'],
        'app_description': meta['__description__'],
        'current_language': current_lang,
        'languages': current_app.config['LANGUAGES'],
        'gettext': gettext,
        'ngettext': ngettext
    }
