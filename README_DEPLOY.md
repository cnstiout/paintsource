# PaintSource v1 — Deploy over SSH

Minimal version (toggle-only), ready to deploy.

## Local dev
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip -r requirements.txt

python3 app.py --cols 160 --rows 48 --scale 6
# http://127.0.0.1:8765/

# Another terminal
python3 term_client.py
```

---

## Deploy (root) — systemd + nginx + https

Edit variables and run:
```bash
bash deploy/deploy_root.sh \
  --server user@your.server \
  --domain paint.yoursite.tld \
  --path /opt/paintsource_v1 \
  --cols 160 --rows 48 --scale 6 --port 8765
```

This will:
- rsync files to the server
- create venv + install deps
- install systemd service
- install nginx vhost (HTTP)
- reload nginx
- prompt you to enable HTTPS with certbot

Then visit: https://paint.yoursite.tld/

---

## Deploy (no root) — user space

Run:
```bash
bash deploy/deploy_user.sh \
  --server user@your.server \
  --path ~/paintsource_v1 \
  --cols 160 --rows 48 --scale 6 --port 9000
```

It will rsync the project and start:
```bash
python3 app.py --host 127.0.0.1 --port 9000 --cols ... --rows ... --scale ...
```
You can ask your friend to reverse-proxy to `127.0.0.1:9000` on the server,
or create an SSH tunnel from your machine:
```bash
ssh -N -L 8765:127.0.0.1:9000 user@your.server
# then open http://127.0.0.1:8765/
```

---

## Files
- app.py — server (web + ws)
- term_client.py — terminal client
- requirements.txt — deps
- deploy/deploy_root.sh — automated root deploy
- deploy/deploy_user.sh — user-space deploy
- deploy/paintsource.service — systemd unit template
- deploy/nginx.paintsource.conf — nginx vhost template
