#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════════════
# Hand Of Midas — Deployment Script
# ═══════════════════════════════════════════════════════════════════════════════
#
# Target: Ubuntu 22.04+ on AWS EC2 (same box as VibeTrader — subashtrades.in)
# Domain: midas.subashtrades.in
#
# Usage:
#   ./deploy.sh              (full setup from scratch)
#   ./deploy.sh update       (git pull + restart services)
#   ./deploy.sh status       (check all services)
#   ./deploy.sh logs         (tail all service logs)
#   ./deploy.sh restart      (restart all services)
#   ./deploy.sh stop         (stop all services)
#
# ═══════════════════════════════════════════════════════════════════════════════

set -e

# ─── Config ───────────────────────────────────────────────────────────────────
APP_DIR="/opt/handofmidas"
REPO_URL="git@github-midas:SubashMourougayane/hand-of-midas.git"
BRANCH="main"
DB_NAME="golddigger"
DB_USER="midas"
DB_PASS="midas_trade_2026"
DOMAIN="midas.subashtrades.in"
NODE_VERSION="20"

# Ports
PORT_GOLD=5053
PORT_OIL=5054
PORT_UI=3001

# ─── Colors ───────────────────────────────────────────────────────────────────
G='\033[0;32m'; Y='\033[0;33m'; B='\033[0;34m'; R='\033[0;31m'; C='\033[0;36m'; NC='\033[0m'
log() { echo -e "${G}[MIDAS]${NC} $1"; }
warn() { echo -e "${Y}[WARN]${NC} $1"; }
err() { echo -e "${R}[ERROR]${NC} $1"; exit 1; }

# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 1: System Packages (skip if already installed by VibeTrader)
# ═══════════════════════════════════════════════════════════════════════════════
install_system() {
  log "Checking system dependencies..."

  # These should already exist from VibeTrader deploy
  for cmd in python3 node psql nginx; do
    if ! command -v $cmd &>/dev/null; then
      err "$cmd not found. Run VibeTrader deploy.sh first or install manually."
    fi
  done

  # Ensure python3-venv is installed
  PYTHON_VER=$(python3 --version | grep -oP '\d+\.\d+')
  if ! dpkg -l python3-venv &>/dev/null && ! dpkg -l python${PYTHON_VER}-venv &>/dev/null; then
    log "Installing python3-venv..."
    sudo apt-get update -qq
    sudo apt-get install -y -qq python3-venv python3-dev libpq-dev
  fi

  log "System: Python $(python3 --version | cut -d' ' -f2), Node $(node --version), PostgreSQL $(psql --version | grep -oP '\d+\.\d+')"
}

# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 2: Database Setup
# ═══════════════════════════════════════════════════════════════════════════════
setup_database() {
  log "Setting up database..."

  # Create user
  sudo -u postgres psql -tc "SELECT 1 FROM pg_roles WHERE rolname='${DB_USER}'" | grep -q 1 || \
    sudo -u postgres psql -c "CREATE ROLE ${DB_USER} WITH LOGIN PASSWORD '${DB_PASS}';"

  # Create database
  sudo -u postgres psql -tc "SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'" | grep -q 1 || \
    sudo -u postgres createdb -O ${DB_USER} ${DB_NAME}

  # Grant permissions
  sudo -u postgres psql -d ${DB_NAME} -c "GRANT ALL PRIVILEGES ON DATABASE ${DB_NAME} TO ${DB_USER};"
  sudo -u postgres psql -d ${DB_NAME} -c "GRANT ALL ON SCHEMA public TO ${DB_USER};"
  sudo -u postgres psql -d ${DB_NAME} -c "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO ${DB_USER};"

  # Apply schema
  PGPASSWORD=${DB_PASS} psql -U ${DB_USER} -d ${DB_NAME} -f ${APP_DIR}/database/schema.sql 2>/dev/null || true

  # Seed admin user
  cd ${APP_DIR}
  source .venv/bin/activate
  python -c "
from backend.auth import hash_password
from backend.db import execute
pw = hash_password('9994605758')
execute('''INSERT INTO users (email, password_hash, name, phone) VALUES (%s, %s, %s, %s) ON CONFLICT (email) DO NOTHING''', ('subashtrades.in@gmail.com', pw, 'Subash', '9994605758'))
print('Admin user seeded')
" 2>/dev/null || true

  log "Database '${DB_NAME}' ready (user: ${DB_USER})"
}

# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 3: Clone & Install App
# ═══════════════════════════════════════════════════════════════════════════════
setup_app() {
  log "Setting up application..."

  # Clone or pull
  if [ -d "$APP_DIR" ]; then
    cd "$APP_DIR"
    git fetch origin && git reset --hard origin/${BRANCH}
  else
    sudo mkdir -p "$APP_DIR"
    sudo chown $USER:$USER "$APP_DIR"
    git clone -b ${BRANCH} ${REPO_URL} "$APP_DIR"
    cd "$APP_DIR"
  fi

  # Python venv + deps
  log "Installing Python dependencies..."
  python3 -m venv .venv
  source .venv/bin/activate
  pip install --upgrade pip -q
  pip install -r requirements.txt -q

  # Ensure swap exists (needed for npm build on small instances)
  if [ ! -f /swapfile ]; then
    log "Creating 2GB swap file..."
    sudo fallocate -l 2G /swapfile
    sudo chmod 600 /swapfile
    sudo mkswap /swapfile
    sudo swapon /swapfile
    echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
  fi

  # Frontend build
  log "Building frontend..."
  cd frontend
  npm install --legacy-peer-deps 2>/dev/null
  NODE_OPTIONS="--max-old-space-size=1024" npm run build
  cd "$APP_DIR"

  # Create .env if not exists
  if [ ! -f .env ]; then
    log "Creating .env..."
    cat > .env << ENVEOF
OANDA_TOKEN=
OANDA_ACCOUNT=
OANDA_URL=https://api-fxpractice.oanda.com/v3
DATABASE_URL=postgresql://${DB_USER}:${DB_PASS}@localhost:5432/${DB_NAME}
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
ENVEOF
    warn ".env created — EDIT IT with your OANDA + Telegram credentials!"
  fi

  # Create logs dir
  mkdir -p ${APP_DIR}/logs

  log "Application installed at ${APP_DIR}"
}

# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 4: Systemd Services
# ═══════════════════════════════════════════════════════════════════════════════
setup_services() {
  log "Creating systemd services..."

  # Gold Backend
  sudo tee /etc/systemd/system/midas-gold.service > /dev/null << EOF
[Unit]
Description=Hand Of Midas — Gold Backend (XAU/USD)
After=network.target postgresql.service

[Service]
Type=simple
User=$USER
WorkingDirectory=${APP_DIR}/backend
EnvironmentFile=${APP_DIR}/.env
ExecStart=${APP_DIR}/.venv/bin/uvicorn main:app --host 0.0.0.0 --port ${PORT_GOLD}
Restart=always
RestartSec=5
StandardOutput=append:${APP_DIR}/logs/gold.log
StandardError=append:${APP_DIR}/logs/gold.log

[Install]
WantedBy=multi-user.target
EOF

  # Oil Backend
  sudo tee /etc/systemd/system/midas-oil.service > /dev/null << EOF
[Unit]
Description=Hand Of Midas — Oil Backend (BCO/USD)
After=network.target postgresql.service

[Service]
Type=simple
User=$USER
WorkingDirectory=${APP_DIR}/backend-oil
EnvironmentFile=${APP_DIR}/.env
ExecStart=${APP_DIR}/.venv/bin/uvicorn main:app --host 0.0.0.0 --port ${PORT_OIL}
Restart=always
RestartSec=5
StandardOutput=append:${APP_DIR}/logs/oil.log
StandardError=append:${APP_DIR}/logs/oil.log

[Install]
WantedBy=multi-user.target
EOF

  # Frontend (Next.js production)
  sudo tee /etc/systemd/system/midas-ui.service > /dev/null << EOF
[Unit]
Description=Hand Of Midas — Dashboard
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=${APP_DIR}/frontend
ExecStart=$(which npx) next start -p ${PORT_UI}
Restart=always
RestartSec=5
Environment=NODE_ENV=production

[Install]
WantedBy=multi-user.target
EOF

  sudo systemctl daemon-reload
  sudo systemctl enable midas-gold midas-oil midas-ui

  log "Services created: midas-gold, midas-oil, midas-ui"
}

# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 5: Nginx (subdomain: midas.subashtrades.in)
# ═══════════════════════════════════════════════════════════════════════════════
setup_nginx() {
  log "Configuring Nginx for ${DOMAIN}..."

  sudo tee /etc/nginx/sites-available/midas > /dev/null << NGINX
server {
    listen 80;
    server_name ${DOMAIN};

    # Frontend (Next.js)
    location / {
        proxy_pass http://127.0.0.1:${PORT_UI};
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_cache_bypass \$http_upgrade;
    }

    # Gold API
    location /api/gold/ {
        proxy_pass http://127.0.0.1:${PORT_GOLD}/api/gold/;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_read_timeout 300;
    }

    # Auth API (served by Gold backend)
    location /api/auth/ {
        proxy_pass http://127.0.0.1:${PORT_GOLD}/api/auth/;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
    }

    # Health check (Gold)
    location /api/health {
        proxy_pass http://127.0.0.1:${PORT_GOLD}/api/health;
    }

    # Oil API
    location /api/oil/ {
        proxy_pass http://127.0.0.1:${PORT_OIL}/api/oil/;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_read_timeout 300;
    }
}
NGINX

  sudo ln -sf /etc/nginx/sites-available/midas /etc/nginx/sites-enabled/
  sudo nginx -t && sudo systemctl reload nginx

  log "Nginx configured — http://${DOMAIN}"
}

# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 6: SSL (Let's Encrypt)
# ═══════════════════════════════════════════════════════════════════════════════
setup_ssl() {
  log "Setting up SSL certificate..."

  if command -v certbot &>/dev/null; then
    sudo certbot --nginx -d ${DOMAIN} --non-interactive --agree-tos --email subashtrades.in@gmail.com || \
      warn "SSL setup failed — site will work on HTTP only"
  else
    warn "certbot not installed — skipping SSL"
  fi
}

# ═══════════════════════════════════════════════════════════════════════════════
# COMMANDS
# ═══════════════════════════════════════════════════════════════════════════════
start_services() {
  log "Starting all services..."
  sudo systemctl start midas-gold midas-oil midas-ui
  sleep 3
  show_status
}

stop_services() {
  log "Stopping all services..."
  sudo systemctl stop midas-gold midas-oil midas-ui
}

restart_services() {
  log "Restarting all services..."
  sudo systemctl restart midas-gold midas-oil midas-ui
  sleep 3
  show_status
}

show_status() {
  echo ""
  echo -e "  ${Y}╔══════════════════════════════════════════════╗${NC}"
  echo -e "  ${Y}║${NC}  🤚 ${Y}HAND OF MIDAS${NC} — Service Status          ${Y}║${NC}"
  echo -e "  ${Y}╠══════════════════════════════════════════════╣${NC}"

  for svc in midas-gold midas-oil midas-ui; do
    status=$(systemctl is-active $svc 2>/dev/null || echo "inactive")
    if [ "$status" = "active" ]; then
      icon="${G}●${NC}"
    else
      icon="${R}○${NC}"
    fi
    printf "  ${Y}║${NC}  ${icon}  %-20s  %-10s       ${Y}║${NC}\n" "$svc" "$status"
  done

  echo -e "  ${Y}╠══════════════════════════════════════════════╣${NC}"

  for port in ${PORT_GOLD} ${PORT_OIL} ${PORT_UI} 80 443; do
    listening=$(ss -tlnp 2>/dev/null | grep ":${port} " | head -1)
    if [ -n "$listening" ]; then
      printf "  ${Y}║${NC}  ${G}●${NC}  Port %-5s  listening                ${Y}║${NC}\n" "$port"
    else
      printf "  ${Y}║${NC}  ${R}○${NC}  Port %-5s  not listening             ${Y}║${NC}\n" "$port"
    fi
  done

  echo -e "  ${Y}╚══════════════════════════════════════════════╝${NC}"
  echo ""
  echo -e "  ${C}Dashboard:${NC}  https://${DOMAIN}"
  echo -e "  ${C}Gold API:${NC}   https://${DOMAIN}/api/gold/state"
  echo -e "  ${C}Oil API:${NC}    https://${DOMAIN}/api/oil/state"
  echo ""
}

show_logs() {
  echo -e "${Y}[GOLD]${NC} ${C}[OIL]${NC} ${G}[UI]${NC} — Ctrl+C to exit"
  sudo journalctl -f -u midas-gold -u midas-oil -u midas-ui --no-hostname -o short-iso | \
    sed -e "s/midas-gold/$(printf "${Y}GOLD${NC}")/" \
        -e "s/midas-oil/$(printf "${C}OIL${NC}")/" \
        -e "s/midas-ui/$(printf "${G}UI${NC}")/"
}

update_app() {
  log "Pulling latest code..."
  cd "$APP_DIR"
  git fetch origin && git reset --hard origin/${BRANCH}

  source .venv/bin/activate
  pip install -r requirements.txt -q

  cd frontend
  npm install --legacy-peer-deps 2>/dev/null
  npm run build
  cd "$APP_DIR"

  restart_services
  log "Update complete!"
}

# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════
case "${1:-install}" in
  install)
    echo ""
    echo -e "  ${Y}╔══════════════════════════════════════════════╗${NC}"
    echo -e "  ${Y}║${NC}  🤚 ${Y}HAND OF MIDAS${NC} — Full Deployment         ${Y}║${NC}"
    echo -e "  ${Y}║${NC}     Ubuntu 22.04+ / AWS EC2                 ${Y}║${NC}"
    echo -e "  ${Y}║${NC}     Domain: ${C}${DOMAIN}${NC}             ${Y}║${NC}"
    echo -e "  ${Y}╚══════════════════════════════════════════════╝${NC}"
    echo ""

    install_system
    setup_app
    setup_database
    setup_services
    setup_nginx
    setup_ssl
    start_services

    echo ""
    echo -e "  ${Y}════════════════════════════════════════════════${NC}"
    echo -e "  ${G}  DEPLOYMENT COMPLETE!${NC}"
    echo -e "  ${Y}════════════════════════════════════════════════${NC}"
    echo ""
    echo -e "  ${C}Dashboard:${NC}  https://${DOMAIN}"
    echo -e "  ${C}Gold API:${NC}   http://localhost:${PORT_GOLD}"
    echo -e "  ${C}Oil API:${NC}    http://localhost:${PORT_OIL}"
    echo ""
    echo -e "  ${Y}IMPORTANT:${NC} Edit ${APP_DIR}/.env with OANDA + Telegram tokens!"
    echo ""
    echo -e "  Commands:"
    echo -e "    ./deploy.sh status    — check service health"
    echo -e "    ./deploy.sh logs      — tail all logs (colored)"
    echo -e "    ./deploy.sh restart   — restart all services"
    echo -e "    ./deploy.sh update    — git pull + rebuild + restart"
    echo -e "    ./deploy.sh stop      — stop everything"
    echo ""
    ;;
  update)   update_app ;;
  status)   show_status ;;
  logs)     show_logs ;;
  restart)  restart_services ;;
  stop)     stop_services ;;
  start)    start_services ;;
  *)
    echo "Usage: ./deploy.sh [install|update|status|logs|restart|stop|start]"
    ;;
esac
