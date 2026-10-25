#!/bin/sh
# Vultr startup script for the Equa backend (paste into Vultr > Startup Scripts, type "Boot").
#
# Runs once on first boot as root. It:
#   1. installs Docker and opens only ports 22/80/443
#   2. pulls the backend image from Docker Hub
#   3. runs Postgres right away
#   4. starts the API, discovery worker and Caddy (HTTPS for api.equalityfin.tech)
#      as soon as /opt/equa/.env exists
#
# Secrets are NOT in this script or the image. After the server boots, copy them up:
#   scp fastapi_backend/.env root@<VULTR_IP>:/opt/equa/.env
#   scp rsa_key.p8 root@<VULTR_IP>:/opt/equa/secrets/rsa_key.p8      # only if Snowflake is on
# Progress log: /var/log/equa-setup.log

set -eu
exec >>/var/log/equa-setup.log 2>&1

IMAGE="savern/equa-backend:latest"
API_DOMAIN="api.equalityfin.tech"
FRONTEND="https://equalityfin.tech"
APP_DIR="/opt/equa"

# --- 1. Docker + firewall --------------------------------------------------------
# Retry: on first boot apt can still be locked by Ubuntu's own updates.
for _ in 1 2 3 4 5; do
  command -v docker >/dev/null 2>&1 && break
  curl -fsSL https://get.docker.com | sh || sleep 30
done
command -v docker >/dev/null 2>&1
if command -v ufw >/dev/null 2>&1; then
  ufw allow 22/tcp
  ufw allow 80/tcp
  ufw allow 443/tcp
  ufw --force enable
fi

# --- 2. App files ----------------------------------------------------------------
mkdir -p "$APP_DIR/secrets"
chmod 700 "$APP_DIR/secrets"
cd "$APP_DIR"

# Postgres only listens inside Docker; its password is generated here and never leaves the box.
if [ ! -f db.env ]; then
  echo "POSTGRES_PASSWORD=$(openssl rand -hex 24)" >db.env
  chmod 600 db.env
fi
DB_PASSWORD=$(sed -n 's/^POSTGRES_PASSWORD=//p' db.env)

cat >Caddyfile <<EOF
$API_DOMAIN {
  encode gzip
  reverse_proxy backend:8000
}
EOF

# Values under "environment" override .env, so the server always uses the
# Docker database and trusts only the Vercel frontend.
cat >docker-compose.yml <<EOF
services:
  db:
    image: postgres:17
    env_file: db.env
    environment:
      POSTGRES_USER: postgres
      POSTGRES_DB: mydatabase
    volumes:
      - pgdata:/var/lib/postgresql/data
    restart: unless-stopped

  backend:
    image: $IMAGE
    env_file: .env
    environment: &app_env
      DATABASE_URL: postgresql+asyncpg://postgres:$DB_PASSWORD@db:5432/mydatabase
      FRONTEND_URL: $FRONTEND
      CORS_ORIGINS: '["$FRONTEND","https://www.equalityfin.tech"]'
      SNOWFLAKE_PRIVATE_KEY_PATH: /app/secrets/rsa_key.p8
    volumes:
      - ./secrets:/app/secrets:ro
    command: sh -c "alembic upgrade head && fastapi run app/main.py --host 0.0.0.0 --port 8000"
    depends_on: [db]
    restart: unless-stopped

  worker:
    image: $IMAGE
    env_file: .env
    environment: *app_env
    volumes:
      - ./secrets:/app/secrets:ro
    command: python -m commands.worker
    depends_on: [db, backend]
    restart: unless-stopped

  caddy:
    image: caddy:2
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy_data:/data
    depends_on: [backend]
    restart: unless-stopped

volumes:
  pgdata: {}
  caddy_data: {}
EOF

# --- 3. Start ------------------------------------------------------------------
docker compose up -d db

# Finish the boot now and do the rest in the background: wait for the image to
# be on Docker Hub and for the real .env (API keys), then bring everything up.
# Re-run "docker compose pull && docker compose up -d" after changes later.
nohup sh -c "
  cd $APP_DIR
  # An image sent straight over SSH (docker save | docker load) counts too.
  until docker image inspect $IMAGE >/dev/null 2>&1 || docker pull $IMAGE; do
    echo 'Waiting for $IMAGE (Docker Hub, or docker load)...'; sleep 30
  done
  until [ -s .env ]; do sleep 10; done
  docker compose up -d
  echo 'Equa backend is up: https://$API_DOMAIN/docs'
" >>/var/log/equa-setup.log 2>&1 &

echo "Setup done. Waiting for $APP_DIR/.env (scp it up)."
