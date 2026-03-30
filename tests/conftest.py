"""Pytest: relax Zoho integration URL requirement (Docker sets TABLETTRACKER_SELF_HOSTED)."""
import os

os.environ.setdefault("SKIP_ZOHO_SERVICE_CHECK", "1")
