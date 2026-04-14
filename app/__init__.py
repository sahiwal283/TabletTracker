"""TabletTracker application factory."""

import os
from datetime import timedelta
import time
import traceback

from flask import Flask, flash, g, jsonify, redirect, render_template, request, session, url_for
from werkzeug.middleware.proxy_fix import ProxyFix
from flask_babel import Babel
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_wtf.csrf import CSRFError, CSRFProtect

from app.utils.perf_utils import add_server_timing_header, log_request_duration
from config import Config


LANGUAGES = {"en": "English", "es": "Español"}
CSP_POLICY = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.tailwindcss.com https://unpkg.com https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com; "
    "img-src 'self' data: https:; "
    "font-src 'self' data:; "
    "connect-src 'self'; "
    "frame-ancestors 'none';"
)


def _configure_app(app, config_class):
    """Load application config and static defaults."""
    app.config.from_object(config_class)
    app.secret_key = config_class.SECRET_KEY
    app.config["LANGUAGES"] = LANGUAGES
    app.config["BABEL_DEFAULT_LOCALE"] = "en"
    app.config["BABEL_DEFAULT_TIMEZONE"] = "UTC"
    root = getattr(config_class, "APPLICATION_ROOT", None) or "/"
    app.config["APPLICATION_ROOT"] = root if root.startswith("/") else f"/{root}"


def _build_locale_selector(app):
    """Create Babel locale selector with DB/user/session fallback."""

    def get_locale():
        from app.utils.db_utils import get_db

        selected_lang = request.args.get("lang")
        if selected_lang:
            session["language"] = selected_lang
            session["manual_language_override"] = True

        if (
            session.get("manual_language_override")
            and "language" in session
            and session["language"] in app.config["LANGUAGES"]
        ):
            return session["language"]

        if (
            session.get("employee_authenticated")
            and session.get("employee_id")
            and not session.get("manual_language_override")
        ):
            conn = None
            try:
                conn = get_db()
                employee = conn.execute(
                    """
                    SELECT preferred_language FROM employees WHERE id = ?
                    """,
                    (session.get("employee_id"),),
                ).fetchone()
                preferred = employee["preferred_language"] if employee else None
                if preferred and preferred in app.config["LANGUAGES"]:
                    session["language"] = preferred
                    return preferred
            except Exception as exc:
                app.logger.warning("Locale lookup failed: %s", exc)
            finally:
                if conn:
                    try:
                        conn.close()
                    except Exception as exc:
                        app.logger.debug("Failed to close locale DB connection: %s", exc)

        if "language" in session and session["language"] in app.config["LANGUAGES"]:
            return session["language"]

        fallback_lang = request.accept_languages.best_match(app.config["LANGUAGES"].keys())
        fallback_lang = fallback_lang or app.config["BABEL_DEFAULT_LOCALE"]
        session["language"] = fallback_lang
        return fallback_lang

    return get_locale


def _initialize_extensions(app):
    """Initialize Flask extensions used by this app."""
    babel = Babel()
    babel.init_app(app, locale_selector=_build_locale_selector(app))

    csrf = CSRFProtect()
    csrf.init_app(app)

    Limiter(
        app=app,
        key_func=get_remote_address,
        default_limits=["1000 per day", "200 per hour"],
        storage_uri="memory://",
        enabled=False,  # Disabled to prevent false positives on first login
    )


def _configure_session_security(app, config_class):
    """Configure secure cookie/session behavior."""
    if config_class.ENV == "production":
        app.config["SESSION_COOKIE_SECURE"] = True
        app.config["SESSION_COOKIE_HTTPONLY"] = True
        app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

    app.permanent_session_lifetime = timedelta(seconds=config_class.PERMANENT_SESSION_LIFETIME)


def _register_error_handlers(app, config_class):
    """Register CSRF and generic HTTP error handlers."""

    @app.errorhandler(CSRFError)
    def handle_csrf_error(error):
        if request.path.startswith("/api/"):
            return jsonify({"success": False, "error": f"CSRF validation failed: {error.description}"}), 400

        session.clear()
        flash("Your session has expired. Please log in again.", "error")
        return redirect(url_for("auth.index"))

    @app.errorhandler(404)
    def not_found_error(error):
        if request.path.startswith("/api/"):
            return jsonify({"success": False, "error": "Resource not found"}), 404
        if config_class.ENV == "production":
            return render_template("base.html"), 404
        return str(error), 404

    @app.errorhandler(500)
    def internal_error(error):
        if request.path.startswith("/api/"):
            error_msg = str(error)
            if config_class.ENV != "production":
                error_msg = f"{error_msg}\n{traceback.format_exc()}"
            return jsonify({"success": False, "error": f"Internal server error: {error_msg}"}), 500
        if config_class.ENV == "production":
            return render_template("base.html"), 500
        return str(error), 500


def _register_request_hooks(app, config_class):
    """Register shared request lifecycle hooks."""

    @app.before_request
    def _perf_start():
        g.perf_start = time.perf_counter()

    @app.after_request
    def _after_request(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        response.headers["Content-Security-Policy"] = CSP_POLICY

        if config_class.ENV == "production":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"

        if hasattr(g, "perf_start"):
            duration_ms = (time.perf_counter() - g.perf_start) * 1000
            log_request_duration(request.path, duration_ms, app)
            add_server_timing_header(response, request.path, duration_ms, app)

        return response


def _register_blueprints(app):
    """Import and register all blueprints."""
    from app.blueprints import (
        admin,
        api as api_bp,
        api_admin,
        api_machines,
        api_purchase_orders,
        api_receiving,
        api_reports,
        api_submissions,
        api_tablet_types,
        auth,
        dashboard,
        production,
        purchase_orders,
        receiving,
        reports,
        submissions,
    )

    app.register_blueprint(auth.bp)
    app.register_blueprint(admin.bp)
    app.register_blueprint(dashboard.bp)
    app.register_blueprint(reports.bp)
    app.register_blueprint(production.bp)
    app.register_blueprint(submissions.bp)
    app.register_blueprint(purchase_orders.bp)
    app.register_blueprint(receiving.bp)
    app.register_blueprint(api_bp.bp)
    app.register_blueprint(api_purchase_orders.bp)
    app.register_blueprint(api_receiving.bp)
    app.register_blueprint(api_admin.bp)
    app.register_blueprint(api_tablet_types.bp)
    app.register_blueprint(api_machines.bp)
    app.register_blueprint(api_reports.bp)
    app.register_blueprint(api_submissions.bp)


def _initialize_database(app):
    """Ensure DB schema initialization/migrations run at startup."""
    with app.app_context():
        from app.models.database import init_db

        init_db()


def create_app(config_class=Config):
    """Application factory function."""
    app = Flask(__name__, template_folder="../templates", static_folder="../static")

    _configure_app(app, config_class)
    if getattr(config_class, "BEHIND_PROXY", False) or os.environ.get("BEHIND_PROXY", "").lower() in (
        "1",
        "true",
        "yes",
    ):
        n = int(os.environ.get("TRUSTED_PROXY_COUNT", str(getattr(config_class, "TRUSTED_PROXY_COUNT", 1))))
        app.wsgi_app = ProxyFix(
            app.wsgi_app,
            x_for=n,
            x_proto=1,
            x_host=1,
            x_port=1,
            x_prefix=1,
        )
    _initialize_extensions(app)
    _configure_session_security(app, config_class)
    _register_error_handlers(app, config_class)
    _register_request_hooks(app, config_class)
    _register_blueprints(app)
    _initialize_database(app)

    return app
