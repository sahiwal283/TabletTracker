#!/usr/bin/env sh
# Optional front nginx on host port 1120 -> tablettracker:8000 (same Docker network).
# On some Proxmox LXC/Docker hosts, nginx workers need --privileged to spawn (socketpair EPERM).
# If you prefer not to use --privileged, use host nginx or your platform reverse proxy to 127.0.0.1:7620 instead.

set -e
cd "$(dirname "$0")"
docker rm -f tablettracker-nginx 2>/dev/null || true
docker run -d --name tablettracker-nginx \
  --network inventory-tracker_inventory-network \
  -p 1120:80 \
  -v "$(pwd)/nginx-platform.conf:/etc/nginx/conf.d/default.conf:ro" \
  --privileged \
  --restart unless-stopped \
  nginx:alpine
