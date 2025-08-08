# PaintSource PRO — pipou.chris-pek.fr
Préconfiguré pour : domaine `pipou.chris-pek.fr`, bind `127.0.0.1:7100`, grille `80×24`, scale `10`.

## Install (root)
```bash
scp -P 2267 paintsource_pro_pack_pipou_fresh.zip root@pipou.chris-pek.fr:/root/
ssh -p 2267 root@pipou.chris-pek.fr
apt update && apt install -y python3-venv nginx certbot python3-certbot-nginx unzip
mkdir -p /opt/paintsource_pro && cd /opt/paintsource_pro
unzip /root/paintsource_pro_pack_pipou_fresh.zip
python3 -m venv .venv && source .venv/bin/activate
pip install -U pip -r requirements.txt
cp deploy/paintsource.service /etc/systemd/system/paintsource.service
systemctl daemon-reload && systemctl enable --now paintsource
cp deploy/nginx.pipou.conf /etc/nginx/sites-available/paintsource
ln -s /etc/nginx/sites-available/paintsource /etc/nginx/sites-enabled/paintsource || true
nginx -t && systemctl reload nginx
certbot --nginx -d pipou.chris-pek.fr
```

## Run locally
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip -r requirements.txt
python3 app.py  # defaults are already good
# http://127.0.0.1:7100/
```
