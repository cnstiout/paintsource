#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PaintSource — app.py (stdlib only)
- Serveur HTTP + SSE (sans Flask)
- Persistance (canvas_state.json) + logs (canvas_updates.log)
- Reset automatique quotidien
- Affiche les URLs locales pour accès depuis le téléphone (même Wi-Fi)
"""

import http.server
import socketserver
import socket
import threading
import time
import json
import os
import sys
from datetime import datetime
from string import Template

# ───────────────────────────────── Config ─────────────────────────────────

PORT = int(os.getenv('PAINTSOURCE_PORT', '5000'))
CANVAS_W, CANVAS_H = 80, 24
RESET_INTERVAL = 24 * 3600  # secondes
DATA_FILE = 'canvas_state.json'
LOG_FILE  = 'canvas_updates.log'

# ──────────────────────────────── État & I/O ─────────────────────────────

def load_canvas():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return [[' ']*CANVAS_W for _ in range(CANVAS_H)]

canvas = load_canvas()
lock = threading.Lock()
subscribers = []  # Handlers SSE actifs
last_reset = time.time()

def save_canvas():
    with lock:
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(canvas, f)

def log_update(x, y, ch):
    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(f"{datetime.now().isoformat()} UPDATE x={x} y={y} ch={ch}\n")

def log_reset():
    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(f"{datetime.now().isoformat()} RESET all\n")

# ───────────────────────────── Helpers réseau ─────────────────────────────

def local_ipv4s():
    ips = set()
    # 1) socket UDP sortante (détecte l’IP active)
    for target in (('8.8.8.8', 80), ('1.1.1.1', 80)):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(target)
            ips.add(s.getsockname()[0])
            s.close()
        except Exception:
            pass
    # 2) getaddrinfo(hostname)
    try:
        hn = socket.gethostname()
        for fam, *_ in socket.getaddrinfo(hn, None):
            if fam == socket.AF_INET:
                # Certaines implémentations ne renvoient pas l’IP directement ici
                pass
    except Exception:
        pass
    # Filtrer loopback et garder privées si présentes
    def is_private(ip):
        try:
            a, b, c, d = map(int, ip.split('.'))
            if a == 10: return True
            if a == 192 and b == 168: return True
            if a == 172 and 16 <= b <= 31: return True
            return False
        except Exception:
            return False
    privs = [ip for ip in ips if is_private(ip)]
    return privs or [ip for ip in ips if not ip.startswith('127.')] or ['127.0.0.1']

# ──────────────────────────────── SSE helpers ─────────────────────────────

def notify_all(message: dict):
    dead = []
    for h in list(subscribers):
        try:
            h.send_sse(message)
        except Exception:
            dead.append(h)
    for h in dead:
        try:
            subscribers.remove(h)
        except ValueError:
            pass

# ─────────────────────────────── Reset quotidien ─────────────────────────

def periodic_reset():
    global last_reset
    while True:
        time.sleep(1)
        if time.time() - last_reset >= RESET_INTERVAL:
            with lock:
                for y in range(CANVAS_H):
                    for x in range(CANVAS_W):
                        canvas[y][x] = ' '
            last_reset = time.time()
            log_reset()
            save_canvas()
            notify_all({'reset': True})

# ──────────────────────────────── Page HTML (Template) ───────────────────

HTML = Template("""<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><title>PaintSource</title>
<style>
  body{background:#111;color:#ddd;font-family:monospace;margin:16px}
  #canvas{white-space:pre;line-height:1;font-size:12px}
</style>
</head><body>
<h3>PaintSource</h3>
<pre id="canvas">$initial</pre>
<script>
let grid;
const sse = new EventSource('/canvas/stream');
sse.onmessage = e => {
  const m = JSON.parse(e.data);
  if (m.full) { grid = m.full; }
  else if (m.reset) { grid = Array($h).fill().map(_=>Array($w).fill(' ')); }
  else { grid[m.y][m.x] = m.ch; }
  render();
};
fetch('/canvas').then(r=>r.json()).then(g=>{ grid = g; render(); });

function render(){
  document.getElementById('canvas').textContent =
    grid.map(r=>r.map(c=>c===' ' ? '·' : c).join('')).join('\\n');
}
</script>
</body></html>""")

# ─────────────────────────────── HTTP Handler ─────────────────────────────

class Handler(http.server.BaseHTTPRequestHandler):
    def send_json(self, data):
        body = json.dumps(data).encode()
        self.send_response(200)
        self.send_header('Content-Type','application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_sse(self, data):
        self.wfile.write(f"data: {json.dumps(data)}\n\n".encode())
        self.wfile.flush()

    def do_GET(self):
        if self.path == '/':
            with lock:
                initial = '\n'.join(''.join(c if c!=' ' else '·' for c in row) for row in canvas)
            b = HTML.substitute(initial=initial, w=CANVAS_W, h=CANVAS_H).encode()
            self.send_response(200)
            self.send_header('Content-Type','text/html')
            self.send_header('Content-Length', str(len(b)))
            self.end_headers()
            self.wfile.write(b)
        elif self.path == '/canvas':
            with lock:
                self.send_json(canvas)
        elif self.path == '/canvas/stream':
            self.send_response(200)
            self.send_header('Content-Type','text/event-stream')
            self.send_header('Cache-Control','no-cache')
            self.end_headers()
            subscribers.append(self)
            try:
                # état initial
                with lock:
                    self.send_sse({'full': canvas})
                # keepalive ping toutes 15s
                while True:
                    time.sleep(15)
                    try:
                        self.wfile.write(b":\n\n")
                        self.wfile.flush()
                    except Exception:
                        break
            finally:
                if self in subscribers:
                    try:
                        subscribers.remove(self)
                    except ValueError:
                        pass
        else:
            self.send_response(404); self.end_headers()

    def do_POST(self):
        if self.path not in ('/canvas','/canvas/reset'):
            self.send_response(404); self.end_headers(); return

        length = int(self.headers.get('Content-Length', 0))
        raw = self.rfile.read(length) if length else b'{}'
        try:
            data = json.loads(raw) if raw else {}
        except Exception:
            self.send_response(400); self.end_headers(); return

        if self.path == '/canvas':
            x, y, ch = data.get('x'), data.get('y'), data.get('ch')
            if (isinstance(x,int) and isinstance(y,int) and
                0 <= x < CANVAS_W and 0 <= y < CANVAS_H and
                isinstance(ch,str) and len(ch)==1):
                with lock:
                    canvas[y][x] = ch
                log_update(x,y,ch)
                save_canvas()
                notify_all({'x':x,'y':y,'ch':ch})
                self.send_json({'success': True})
            else:
                self.send_response(400); self.end_headers()
        else:  # /canvas/reset
            with lock:
                for yy in range(CANVAS_H):
                    for xx in range(CANVAS_W):
                        canvas[yy][xx] = ' '
            log_reset()
            save_canvas()
            notify_all({'reset': True})
            self.send_json({'success': True})

# ─────────────────────────────── Lancement ────────────────────────────────

def print_local_urls(port: int):
    ips = local_ipv4s()
    print("\nPaintSource est prêt ✨  Ouvre depuis ton téléphone (même Wi-Fi) :")
    for ip in ips:
        print(f"  → http://{ip}:{port}/")
    try:
        print(f"  → http://{socket.gethostname()}.local:{port}/ (si mDNS)")
    except Exception:
        pass
    print("")

if __name__ == '__main__':
    threading.Thread(target=periodic_reset, daemon=True).start()
    try:
        with socketserver.ThreadingTCPServer(('0.0.0.0', PORT), Handler) as srv:
            print_local_urls(PORT)
            print(f"Serving PaintSource on 0.0.0.0:{PORT} …  (Ctrl+C pour arrêter)")
            srv.serve_forever()
    except OSError as e:
        if getattr(e, 'errno', None) == 98:
            print(f"[ERREUR] Le port {PORT} est déjà utilisé. Éteins l'ancien serveur :")
            print("  pkill -f app.py   # ou server.py")
            print(f"  lsof -iTCP:{PORT} -sTCP:LISTEN")
        else:
            print("[ERREUR]", e)
        sys.exit(1)
