#!/usr/bin/env bash
# =============================================================================
# deploy/setup.sh — VPS setup script for fb-monitor
# Tested on Ubuntu 22.04 LTS
# Run as root or with sudo: sudo bash setup.sh
# =============================================================================
set -euo pipefail

APP_DIR="/opt/fb-monitor"
SERVICE_NAME="fb-monitor"
PYTHON="python3.11"

echo "============================================================"
echo " FB Monitor — VPS Setup"
echo "============================================================"

# ---------------------------------------------------------------------------
# 1. System packages
# ---------------------------------------------------------------------------
echo "[1/8] Installing system dependencies..."
apt-get update -qq
apt-get install -y --no-install-recommends \
    software-properties-common \
    curl \
    git \
    nginx \
    unzip \
    ca-certificates \
    lsb-release

# Python 3.11 (deadsnakes PPA for Ubuntu < 23.04)
if ! command -v python3.11 &>/dev/null; then
    echo "    -> Adding deadsnakes PPA for Python 3.11..."
    add-apt-repository -y ppa:deadsnakes/ppa
    apt-get update -qq
    apt-get install -y python3.11 python3.11-venv python3.11-dev
fi

echo "    -> Python version: $(python3.11 --version)"

# ---------------------------------------------------------------------------
# 2. Create application directory
# ---------------------------------------------------------------------------
echo "[2/8] Creating application directory at $APP_DIR..."
mkdir -p "$APP_DIR"

# ---------------------------------------------------------------------------
# 3. Copy project files
# ---------------------------------------------------------------------------
echo "[3/8] Copying project files..."
# Run from the directory containing setup.sh
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

rsync -a --exclude='.git' \
         --exclude='__pycache__' \
         --exclude='*.pyc' \
         --exclude='.env' \
         --exclude='session/' \
         --exclude='*.db' \
         "$PROJECT_ROOT/" "$APP_DIR/"

chown -R ubuntu:ubuntu "$APP_DIR"

# ---------------------------------------------------------------------------
# 4. Python virtual environment
# ---------------------------------------------------------------------------
echo "[4/8] Creating Python virtual environment..."
sudo -u ubuntu "$PYTHON" -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install --upgrade pip wheel

# ---------------------------------------------------------------------------
# 5. Install Python requirements
# ---------------------------------------------------------------------------
echo "[5/8] Installing Python requirements..."
"$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt"

# ---------------------------------------------------------------------------
# 6. Playwright + Chromium
# ---------------------------------------------------------------------------
echo "[6/8] Installing Playwright Chromium browser..."
"$APP_DIR/venv/bin/python" -m playwright install chromium --with-deps
# Make sure the ubuntu user can run it too
chown -R ubuntu:ubuntu /root/.cache/ms-playwright 2>/dev/null || true

# ---------------------------------------------------------------------------
# 7. Environment configuration
# ---------------------------------------------------------------------------
echo "[7/8] Setting up environment file..."
if [ ! -f "$APP_DIR/.env" ]; then
    cp "$APP_DIR/.env.example" "$APP_DIR/.env"
    echo ""
    echo "  ⚠️  IMPORTANT: Edit $APP_DIR/.env before starting the service!"
    echo "       Set TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, and APP_SECRET_KEY"
    echo ""
fi

# ---------------------------------------------------------------------------
# 8. systemd service
# ---------------------------------------------------------------------------
echo "[8/8] Installing systemd service..."
cp "$APP_DIR/deploy/fb-monitor.service" /etc/systemd/system/"$SERVICE_NAME".service
systemctl daemon-reload
systemctl enable "$SERVICE_NAME"

# Don't start yet — user must configure .env first
# systemctl start "$SERVICE_NAME"

echo ""
echo "============================================================"
echo " Nginx configuration"
echo "============================================================"
cp "$APP_DIR/deploy/nginx.conf" /etc/nginx/sites-available/"$SERVICE_NAME"
ln -sf /etc/nginx/sites-available/"$SERVICE_NAME" \
       /etc/nginx/sites-enabled/"$SERVICE_NAME"
# Remove default site if present
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx

# ---------------------------------------------------------------------------
# Optional: Certbot / Let's Encrypt
# ---------------------------------------------------------------------------
echo ""
echo "============================================================"
echo " Optional: SSL with Let's Encrypt"
echo "============================================================"
read -r -p "Install certbot for SSL? (y/N): " INSTALL_CERTBOT
if [[ "${INSTALL_CERTBOT,,}" == "y" ]]; then
    apt-get install -y certbot python3-certbot-nginx
    echo ""
    echo "  Run the following after pointing your domain DNS to this server:"
    echo "    sudo certbot --nginx -d your-domain.com"
    echo "  Then uncomment the HTTPS server block in /etc/nginx/sites-available/fb-monitor"
fi

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
echo ""
echo "============================================================"
echo " Setup complete!"
echo ""
echo " Next steps:"
echo "   1. Edit $APP_DIR/.env  (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, etc.)"
echo "   2. Login to Facebook:  sudo -u ubuntu $APP_DIR/venv/bin/python -m scraper.login"
echo "   3. Start the service:  sudo systemctl start $SERVICE_NAME"
echo "   4. Check logs:         sudo journalctl -u $SERVICE_NAME -f"
echo "============================================================"
