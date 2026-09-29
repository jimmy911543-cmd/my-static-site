#!/bin/bash
# 在 Ubuntu 雲端虛擬機上安裝網站、HTTPS，並啟用憑證自動續期。
# 用法：sudo bash deploy/setup.sh example.com you@example.com
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "請用 sudo 執行。"
  exit 1
fi

DOMAIN="${1:-}"
EMAIL="${2:-}"
if [ -z "$DOMAIN" ] || [ -z "$EMAIL" ]; then
  echo "用法：sudo bash deploy/setup.sh 你的網域 你的信箱"
  exit 1
fi

SRC="$(cd "$(dirname "$0")/.." && pwd)"
APP="/opt/wuyang"

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y nginx certbot python3-certbot-nginx python3 rsync

id wuyang >/dev/null 2>&1 || useradd --system --home "$APP" --shell /usr/sbin/nologin wuyang
mkdir -p "$APP" /var/www/certbot
rsync -a --delete --exclude data --exclude wuyang.env "$SRC/" "$APP/"
mkdir -p "$APP/data"
if [ ! -f "$APP/wuyang.env" ]; then
  cat > "$APP/wuyang.env" <<'EOF'
HOST=127.0.0.1
PORT=8765
WUYANG_ADMIN_PASSWORD=wuyang
EOF
  chmod 600 "$APP/wuyang.env"
fi
chown -R wuyang:wuyang "$APP"

install -m 644 "$APP/deploy/wuyang.service" /etc/systemd/system/wuyang.service
systemctl daemon-reload
systemctl enable --now wuyang.service

sed "s/__DOMAIN__/${DOMAIN}/g" "$APP/deploy/nginx.conf.template" > /etc/nginx/sites-available/wuyang.conf
ln -sfn /etc/nginx/sites-available/wuyang.conf /etc/nginx/sites-enabled/wuyang.conf
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx

certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos --email "$EMAIL" --redirect
install -m 755 "$APP/deploy/reload-nginx.sh" /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh
systemctl enable --now certbot.timer

if command -v ufw >/dev/null 2>&1 && ufw status | grep -q "Status: active"; then
  ufw allow 80/tcp
  ufw allow 443/tcp
fi

echo "完成。網站：https://${DOMAIN}"
echo "憑證由 certbot.timer 自動續期，續期後會重新載入 Nginx。"
