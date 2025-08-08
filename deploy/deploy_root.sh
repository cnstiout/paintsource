#!/usr/bin/env bash
set -euo pipefail

# Defaults
SERVER=""
DOMAIN=""
REMOTE_PATH="/opt/paintsource_v1"
COLS=160
ROWS=48
SCALE=6
PORT=8765

usage(){ cat <<EOF
Usage: $0 --server user@host --domain paint.yoursite.tld [--path /opt/paintsource_v1] [--cols 160] [--rows 48] [--scale 6] [--port 8765]

Requires root on server for systemd+nginx.
EOF
exit 1; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --server) SERVER="$2"; shift 2;;
    --domain) DOMAIN="$2"; shift 2;;
    --path)   REMOTE_PATH="$2"; shift 2;;
    --cols)   COLS="$2"; shift 2;;
    --rows)   ROWS="$2"; shift 2;;
    --scale)  SCALE="$2"; shift 2;;
    --port)   PORT="$2"; shift 2;;
    *) usage;;
  esac
done

[[ -z "$SERVER" || -z "$DOMAIN" ]] && usage

echo "[*] Rsync project to $SERVER:$REMOTE_PATH"
ssh "$SERVER" "sudo mkdir -p '$REMOTE_PATH' && sudo chown -R \$USER '\$PWD' '$REMOTE_PATH' || true"
rsync -avz --delete --exclude '__pycache__' --exclude '.venv' ./ "$SERVER":"$REMOTE_PATH"/

echo "[*] Setup venv + deps"
ssh "$SERVER" "cd '$REMOTE_PATH' && python3 -m venv .venv && source .venv/bin/activate && pip install -U pip -r requirements.txt"

echo "[*] Install systemd service"
SERVICE_PATH="/etc/systemd/system/paintsource_v1.service"
ssh "$SERVER" "sudo tee '$SERVICE_PATH' >/dev/null" <<EOF
[Unit]
Description=PaintSource v1 (FastAPI)
After=network.target

[Service]
User=\$USER
WorkingDirectory=$REMOTE_PATH
ExecStart=$REMOTE_PATH/.venv/bin/python app.py --host 127.0.0.1 --port $PORT --cols $COLS --rows $ROWS --scale $SCALE
Restart=always
RestartSec=2
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

ssh "$SERVER" "sudo systemctl daemon-reload && sudo systemctl enable --now paintsource_v1 && sudo systemctl status paintsource_v1 --no-pager"

echo "[*] Install nginx vhost for $DOMAIN"
NGX="/etc/nginx/sites-available/paintsource_v1"
ssh "$SERVER" "sudo tee '$NGX' >/dev/null" <<EOF
server {
    listen 80;
    server_name $DOMAIN;

    location / {
        proxy_pass http://127.0.0.1:$PORT/;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
    }

    location /ws {
        proxy_pass http://127.0.0.1:$PORT/ws;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 86400;
        proxy_set_header Host \$host;
    }
}
EOF
ssh "$SERVER" "sudo ln -sf '$NGX' /etc/nginx/sites-enabled/paintsource_v1 && sudo nginx -t && sudo systemctl reload nginx"

echo "[*] (Optional) Enable HTTPS with certbot:"
echo "ssh $SERVER 'sudo certbot --nginx -d $DOMAIN'"
echo "[✓] Done. Visit: http://$DOMAIN/"
