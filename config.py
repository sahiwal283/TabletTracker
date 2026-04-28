import json
import os

from dotenv import load_dotenv

load_dotenv()


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes")


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _parse_zoho_service_extra_headers():
    raw = os.environ.get("ZOHO_SERVICE_EXTRA_HEADERS", "").strip()
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def _parse_int_list_env(name: str):
    raw = os.environ.get(name, "").strip()
    if not raw:
        return []
    out = []
    for part in raw.split(","):
        value = part.strip()
        if not value:
            continue
        try:
            out.append(int(value))
        except ValueError:
            continue
    return out


class Config:
    # Flask settings
    SECRET_KEY = os.environ.get('SECRET_KEY')
    if not SECRET_KEY:
        ENV = os.environ.get('FLASK_ENV', 'development')
        if ENV == 'production':
            raise ValueError("SECRET_KEY environment variable must be set in production")
        SECRET_KEY = 'dev-secret-change-in-production'  # Only allow in development

    # Admin authentication
    ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD')
    if not ADMIN_PASSWORD:
        ENV = os.environ.get('FLASK_ENV', 'development')
        if ENV == 'production':
            raise ValueError("ADMIN_PASSWORD environment variable must be set in production")
        ADMIN_PASSWORD = 'admin'  # Only allow in development

    # Zoho API settings
    ZOHO_CLIENT_ID = os.environ.get('ZOHO_CLIENT_ID')
    ZOHO_CLIENT_SECRET = os.environ.get('ZOHO_CLIENT_SECRET')
    ZOHO_REFRESH_TOKEN = os.environ.get('ZOHO_REFRESH_TOKEN')
    ZOHO_ORGANIZATION_ID = os.environ.get('ZOHO_ORGANIZATION_ID', '856048585')  # Your org ID

    # Self-hosted: route all Zoho traffic through integration service (e.g. http://zoho-integration:9503).
    # When set, defaults inventory API to {ZOHO_SERVICE_BASE_URL}/inventory/v1 and token to
    # {ZOHO_SERVICE_BASE_URL}/oauth/v2/token (standard Zoho layout behind a transparent proxy).
    # Override with ZOHO_INVENTORY_API_BASE / ZOHO_TOKEN_URL if your service uses different paths.
    ZOHO_SERVICE_BASE_URL = os.environ.get("ZOHO_SERVICE_BASE_URL", "").strip().rstrip("/")
    _zoho_inv_override = os.environ.get("ZOHO_INVENTORY_API_BASE", "").strip().rstrip("/")
    _zoho_tok_override = os.environ.get("ZOHO_TOKEN_URL", "").strip()
    ZOHO_INVENTORY_API_BASE = _zoho_inv_override or (
        f"{ZOHO_SERVICE_BASE_URL}/inventory/v1"
        if ZOHO_SERVICE_BASE_URL
        else "https://www.zohoapis.com/inventory/v1"
    )
    ZOHO_TOKEN_URL = _zoho_tok_override or (
        f"{ZOHO_SERVICE_BASE_URL}/oauth/v2/token"
        if ZOHO_SERVICE_BASE_URL
        else "https://accounts.zoho.com/oauth/v2/token"
    )
    ZOHO_SERVICE_EXTRA_HEADERS = _parse_zoho_service_extra_headers()

    # Reverse proxy (nginx): trust X-Forwarded-*; optional subpath via X-Forwarded-Prefix
    BEHIND_PROXY = _env_flag("BEHIND_PROXY")
    TRUSTED_PROXY_COUNT = _env_int("TRUSTED_PROXY_COUNT", 1)
    # If the app is mounted under a path (and not only X-Forwarded-Prefix), set e.g. APPLICATION_ROOT=/tablet
    APPLICATION_ROOT = os.environ.get("APPLICATION_ROOT", "").strip() or "/"

    # UPS Tracking API (free; client credentials)
    UPS_CLIENT_ID = os.environ.get('UPS_CLIENT_ID')
    UPS_CLIENT_SECRET = os.environ.get('UPS_CLIENT_SECRET')
    # Base URL: 'https://apis.ups.com' (prod) or 'https://wwwcie.ups.com' (test)
    UPS_API_BASE = os.environ.get('UPS_API_BASE', 'https://apis.ups.com')
    UPS_TRANSACTION_SRC = os.environ.get('UPS_TRANSACTION_SRC', 'TabletTracker')

    # FedEx Tracking API (free with dev account)
    FEDEX_API_KEY = os.environ.get('FEDEX_API_KEY')
    FEDEX_API_SECRET = os.environ.get('FEDEX_API_SECRET')
    FEDEX_ACCOUNT_NUMBER = os.environ.get('FEDEX_ACCOUNT_NUMBER')
    FEDEX_BASE = os.environ.get('FEDEX_BASE', 'https://apis.fedex.com')

    # Telegram bot settings
    TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    TELEGRAM_ALLOWED_CHAT_IDS = _parse_int_list_env("TELEGRAM_ALLOWED_CHAT_IDS")
    TELEGRAM_ALLOWED_USER_IDS = _parse_int_list_env("TELEGRAM_ALLOWED_USER_IDS")
    TELEGRAM_DAILY_REPORT_TIME = os.environ.get("TELEGRAM_DAILY_REPORT_TIME", "18:30").strip() or "18:30"
    # Webhook auth: prefer TELEGRAM_WEBHOOK_SECRET + setWebhook(secret_token=...) so the bot token is not in the URL.
    # Optional TELEGRAM_WEBHOOK_PATH_SECRET: random path segment instead of putting TELEGRAM_BOT_TOKEN in the URL.
    TELEGRAM_WEBHOOK_SECRET = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "").strip()
    TELEGRAM_WEBHOOK_PATH_SECRET = os.environ.get("TELEGRAM_WEBHOOK_PATH_SECRET", "").strip()

    # Database (set DATABASE_PATH in Docker to a mounted volume, e.g. /data/tablet_counter.db)
    _config_dir = os.path.dirname(os.path.abspath(__file__))
    DATABASE_PATH = os.environ.get("DATABASE_PATH") or os.path.join(_config_dir, "database", "tablet_counter.db")
    DATABASE_URL = os.environ.get("DATABASE_URL") or f"sqlite:///{DATABASE_PATH}"

    # Security settings
    SESSION_COOKIE_SECURE = os.environ.get('FLASK_ENV') == 'production'
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    PERMANENT_SESSION_LIFETIME = 28800  # 8 hours in seconds

    # CSRF settings - match session lifetime to prevent token expiration during long work sessions
    WTF_CSRF_TIME_LIMIT = 28800  # 8 hours in seconds (same as session)

    # App settings
    ITEMS_PER_PAGE = 50
    DEBUG = os.environ.get('FLASK_ENV') == 'development'

    # Production settings
    ENV = os.environ.get('FLASK_ENV', 'development')
    TESTING = False

    # Performance baseline logging (request/query timing). Default: same as DEBUG.
    PERF_LOGGING = _env_flag('PERF_LOGGING') or os.environ.get('FLASK_ENV') == 'development'


def _validate_self_hosted_zoho():
    """Docker image sets TABLETTRACKER_SELF_HOSTED=1; all Zoho traffic must use the integration service."""
    if not _env_flag("TABLETTRACKER_SELF_HOSTED"):
        return
    if _env_flag("SKIP_ZOHO_SERVICE_CHECK"):
        return
    if not os.environ.get("ZOHO_SERVICE_BASE_URL", "").strip():
        raise ValueError(
            "TABLETTRACKER_SELF_HOSTED is set but ZOHO_SERVICE_BASE_URL is empty. "
            "Set it to your Zoho integration service base URL, e.g. http://zoho-integration:9503"
        )


_validate_self_hosted_zoho()
