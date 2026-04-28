# PythonAnywhere: deploy TabletTracker v4.6+ / v4.7 (UI refresh)

> For **v4.7.0**, use the same steps; version is informational only unless migrations are noted in [CHANGELOG.md](../../CHANGELOG.md).

Replace `YOUR_USER` with your PythonAnywhere username and adjust the virtualenv path if yours differs (`venv`, `.venv`, or a named virtualenv).

## Commands (Bash console on PythonAnywhere)

```bash
cd /home/YOUR_USER/TabletTracker

git fetch origin
git checkout main
git pull origin main
# Or merge/tag your release branch after it lands on GitHub.

source /home/YOUR_USER/TabletTracker/venv/bin/activate
pip install -r requirements.txt --upgrade

# Only if this release ships new migrations (v4.6.0 does not require a schema bump by default):
# alembic upgrade head
```

Then open the **Web** tab and click **Reload** for your site so WSGI picks up new templates and static files.

## After reload

1. Smoke-test login and one primary workflow page (for example Shipments Received or Production).
2. Open **Ops TV**: `/command-center/ops-tv` (admin session) — confirm LIVE strip, KPIs, charts, and “Snapshot · …” time update every poll.
3. If fonts fail to load, check browser devtools console for CSP violations; `app/__init__.py` in v4.6.0 allows `https://fonts.googleapis.com` and `https://fonts.gstatic.com`.

## Static files

Ensure **Static files** mapping still points `/static/` to `/home/YOUR_USER/TabletTracker/static/` (Web tab → Static files).
