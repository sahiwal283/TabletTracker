# Migrating from PythonAnywhere to self-hosted (complete)

This checklist moves **code + SQLite data** to your server, routes **all Zoho calls** through your **integration service** (e.g. port **9503**), and exposes the app via **nginx** (e.g. container **104**) on your internal app platform.

## 1. Export data from PythonAnywhere

1. Open a **Bash console** on PythonAnywhere (or use **Files**).
2. Locate your database file, typically:
   - `~/TabletTracker/database/tablet_counter.db`
3. Download it to your workstation (Files tab → select file → Download), or use `scp` / `rsync` if you have SSH access.
4. Optionally download **backups** under `backups/` if you rely on them.
5. **Secrets**: Copy your production `.env` values (never commit them). Rotate keys if `.env` was ever exposed.

## 2. Prepare the server (192.168.1.190 or your host)

1. Install **Docker** and **Docker Compose** (plugin or `docker compose`).
2. Clone or upload this repository to the server.
3. Create a directory for the database and copy the file:

   ```bash
   mkdir -p /opt/tablettracker/data
   cp /path/to/tablet_counter.db /opt/tablettracker/data/tablet_counter.db
   chmod 644 /opt/tablettracker/data/tablet_counter.db
   ```

   Or use the repo’s `./data` directory if you use the provided `docker-compose.yml` as-is.

## 3. Docker network with Zoho integration service

TabletTracker must resolve the Zoho service by **container name** (not `localhost`).

1. List your existing network (often shared with other apps):

   ```bash
   docker network ls
   ```

2. Edit `docker-compose.yml` and set `networks.app_platform.name` to that network name, or create one:

   ```bash
   docker network create app_platform
   ```

3. Ensure the **Zoho integration service** container is attached to the **same network** and listening on **9503** (or whatever port you use).

## 4. Configure environment

1. Copy `.env.example` to `.env` on the server.
2. Set at minimum:
   - `SECRET_KEY`, `ADMIN_PASSWORD`
   - `ZOHO_CLIENT_ID`, `ZOHO_CLIENT_SECRET`, `ZOHO_REFRESH_TOKEN`, `ZOHO_ORGANIZATION_ID`
   - **`ZOHO_SERVICE_BASE_URL`** = `http://<zoho-service-container-name>:9503` (must match Docker DNS name on the shared network)
3. The Docker image sets **`TABLETTRACKER_SELF_HOSTED=1`**, which **requires** `ZOHO_SERVICE_BASE_URL` at startup (no direct `zohoapis.com` from the container).
4. Set **`BEHIND_PROXY=1`** when serving behind nginx (included in the Dockerfile).

## 5. Run the stack

```bash
cd /path/to/TabletTracker
docker compose build
docker compose up -d
```

Host port **7620** maps to gunicorn **8000** inside the container.

## 6. nginx (container 104) and internal platform

1. Add an `upstream` / `location` that proxies to TabletTracker:
   - From the **host**: `proxy_pass http://127.0.0.1:7620;`
   - From **another container** on the same network: `proxy_pass http://tablettracker:8000;`
2. Pass headers: `Host`, `X-Real-IP`, `X-Forwarded-For`, `X-Forwarded-Proto`, and if needed `X-Forwarded-Prefix` for a subpath.
3. See `deploy/nginx-tablettracker.example.conf` for a template.
4. Platform frontend (**1120**) / DB (**1220**) are separate; TabletTracker keeps its own SQLite in the mounted volume unless you change architecture later.

## 7. Verification

- `curl -s http://127.0.0.1:7620/health` → `{"status":"ok"}`
- If you use the optional **nginx sidecar** on port **1120** (see `deploy/tablettracker-nginx-docker.sh` and `deploy/nginx-platform.conf`): `curl -s http://127.0.0.1:1120/health`. On some Proxmox/Docker setups the nginx container may need **`--privileged`** so worker processes can start; otherwise point your platform proxy at **`http://<host>:7620`** directly.
- Open the app through your platform URL, log in, run **Sync Zoho POs** and **Test Zoho connection** (see `docs/ZOHO_INTEGRATION_ROUTES.md`).
- Confirm in your Zoho integration service logs that requests come from TabletTracker, not direct public Zoho from this app.

## 8. Decommission PythonAnywhere

After a successful parallel run, point DNS/bookmarks to the new URL, then cancel or downgrade the PythonAnywhere web app.
