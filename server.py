#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Standalone PaintSource server using only Python standard library.
"""

import http.server
import socketserver
import threading
import time
import json
import os
from datetime import datetime

PORT = 5000
CANVAS_W, CANVAS_H = 80, 24
RESET_INTERVAL = 24 * 3600  # seconds
DATA_FILE = 'canvas_state.json'
LOG_FILE = 'canvas_updates.log'

# Load or initialize canvas
if os.path.exists(DATA_FILE):
    try:
        with open(DATA_FILE, 'r') as f:
            canvas = json.load(f)
    except:
        canvas = [[' ']*CANVAS_W for _ in range(CANVAS_H)]
else:
    canvas = [[' ']*CANVAS_W for _ in range(CANVAS_H)]

lock = threading.Lock()
subscribers = []  # list of handler objects
last_reset = time.time()

def save_canvas():
    with lock:
        with open(DATA_FILE, 'w') as f:
            json.dump(canvas, f)

def log_update(x, y, ch):
    entry = f"{datetime.now().isoformat()} UPDATE x={x} y={y} ch={ch}\n"
    with open(LOG_FILE, 'a') as f:
        f.write(entry)

def log_reset():
    entry = f"{datetime.now().isoformat()} RESET all\n"
    with open(LOG_FILE, 'a') as f:
        f.write(entry)

def periodic_reset():
    global canvas, last_reset
    while True:
        time.sleep(1)
        now = time.time()
        if now - last_reset >= RESET_INTERVAL:
            with lock:
                canvas = [[' ']*CANVAS_W for _ in range(CANVAS_H)]
            last_reset = now
            log_reset()
            save_canvas()
            for handler in subscribers:
                handler.send_sse({'reset': True})

threading.Thread(target=periodic_reset, daemon=True).start()

class Handler(http.server.BaseHTTPRequestHandler):
    def send_json(self, data):
        body = json.dumps(data).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == '/':
            with lock:
                initial = '\n'.join(''.join(c if c!=' ' else '·' for c in row)
                                     for row in canvas)
            html = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>PaintSource</title></head><body>
<pre id="canvas">{initial}</pre>
<script>
let grid;
const evt = new EventSource('/canvas/stream');
evt.onmessage = e => {{
  const msg = JSON.parse(e.data);
  if (msg.full) grid = msg.full;
  else if (msg.reset) grid = Array({CANVAS_H}).fill().map(_=>Array({CANVAS_W}).fill(' '));
  else if (msg.x!==undefined) grid[msg.y][msg.x] = msg.ch;
  document.getElementById('canvas').textContent =
    grid.map(r=>r.map(c=>c===' ' ? '·':c).join('')).join('\\n');
}};
fetch('/canvas').then(r=>r.json()).then(g=>{{grid=g;}});
</script>
</body></html>"""
            b = html.encode()
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
                with lock:
                    self.send_sse({'full': canvas})
                while True:
                    time.sleep(0.1)
            except ConnectionError:
                subscribers.remove(self)

        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path in ('/canvas', '/canvas/reset'):
            length = int(self.headers.get('Content-Length',0))
            body = self.rfile.read(length)
            data = json.loads(body) if body else {}
            if self.path == '/canvas':
                x, y, ch = data.get('x'), data.get('y'), data.get('ch')
                if isinstance(x,int) and isinstance(y,int) and isinstance(ch,str) and len(ch)==1:
                    with lock:
                        canvas[y][x] = ch
                    log_update(x,y,ch); save_canvas()
                    for h in subscribers: h.send_sse({'x':x,'y':y,'ch':ch})
                    self.send_json({'success':True})
                    return
                else:
                    self.send_response(400); self.end_headers(); return
            else:  # reset
                with lock:
                    for yy in range(CANVAS_H):
                        for xx in range(CANVAS_W):
                            canvas[yy][xx] = ' '
                log_reset(); save_canvas()
                for h in subscribers: h.send_sse({'reset':True})
                self.send_json({'success':True})
                return

        self.send_response(404)
        self.end_headers()

    def send_sse(self, data):
        msg = f"data: {json.dumps(data)}\n\n".encode()
        self.wfile.write(msg)
        self.wfile.flush()

with socketserver.ThreadingTCPServer(('', PORT), Handler) as srv:
    print(f"Serving on port {PORT}…")
    srv.serve_forever()
