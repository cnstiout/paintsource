from flask import Flask, request, jsonify, Response
import threading
import time
import queue
import json
import os
import atexit
from datetime import datetime

app = Flask(__name__)

# —————————————————————————————————————————————————
# Configuration et persistance
# —————————————————————————————————————————————————
DATA_FILE       = os.getenv('CANVAS_DATA_FILE', 'canvas_state.json')
LOG_FILE        = os.getenv('CANVAS_LOG_FILE',  'canvas_updates.log')
CANVAS_W, CANVAS_H = 80, 24
RESET_INTERVAL  = 24 * 3600  # 24h

# Chargement du canevas depuis le fichier, ou initialisation vierge
if os.path.exists(DATA_FILE):
    try:
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            canvas = json.load(f)
    except Exception:
        canvas = [[' ' for _ in range(CANVAS_W)] for _ in range(CANVAS_H)]
else:
    canvas = [[' ' for _ in range(CANVAS_W)] for _ in range(CANVAS_H)]

lock = threading.Lock()
subscribers = []
last_reset = time.time()

# —————————————————————————————————————————————————
# Fonctions de sauvegarde et de log
# —————————————————————————————————————————————————

def save_canvas():
    """Sauvegarde l'état complet du canvas dans DATA_FILE."""
    with lock:
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(canvas, f)


def log_update(x, y, ch):
    """Ajoute une ligne de log pour chaque mise à jour."""
    entry = f"{datetime.now().isoformat()} UPDATE x={x} y={y} ch={ch}\n"
    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(entry)


def log_reset():
    """Ajoute une ligne de log pour chaque reset."""
    entry = f"{datetime.now().isoformat()} RESET all\n"
    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(entry)

# Sauvegarde à l'arrêt
atexit.register(save_canvas)

# —————————————————————————————————————————————————
# Thread de reset périodique
# —————————————————————————————————————————————————

def periodic_reset():
    global canvas, last_reset
    while True:
        now = time.time()
        if now - last_reset >= RESET_INTERVAL:
            with lock:
                canvas[:] = [[' ' for _ in range(CANVAS_W)] for _ in range(CANVAS_H)]
            last_reset = now
            log_reset()
            notify_subscribers({'reset': True})
            save_canvas()
        time.sleep(1)

t = threading.Thread(target=periodic_reset, daemon=True)
t.start()

# —————————————————————————————————————————————————
# SSE et notifications
# —————————————————————————————————————————————————

def notify_subscribers(message: dict):
    for q in list(subscribers):
        q.put(message)

@app.route('/canvas/stream')
def stream():
    def event_stream(q: queue.Queue):
        with lock:
            yield f"data: {json.dumps({'full': canvas})}\n\n"
        while True:
            msg = q.get()
            yield f"data: {json.dumps(msg)}\n\n"

    q = queue.Queue()
    subscribers.append(q)
    return Response(event_stream(q), mimetype='text/event-stream')

# —————————————————————————————————————————————————
# Endpoints REST
# —————————————————————————————————————————————————

@app.route('/canvas', methods=['GET'])
def get_canvas():
    with lock:
        return jsonify(canvas)

@app.route('/canvas', methods=['POST'])
def post_canvas():
    data = request.get_json(force=True)
    x = data.get('x'); y = data.get('y'); ch = data.get('ch')
    if not (isinstance(x, int) and isinstance(y, int) and isinstance(ch, str) and len(ch) == 1):
        return jsonify({'error': 'Bad payload'}), 400
    with lock:
        canvas[y][x] = ch
    notify_subscribers({'x': x, 'y': y, 'ch': ch})
    log_update(x, y, ch)
    save_canvas()
    return jsonify({'success': True})

@app.route('/canvas/reset', methods=['POST'])
def reset_canvas():
    global last_reset
    with lock:
        for yy in range(CANVAS_H):
            for xx in range(CANVAS_W):
                canvas[yy][xx] = ' '
    last_reset = time.time()
    notify_subscribers({'reset': True})
    log_reset()
    save_canvas()
    return jsonify({'success': True})

# —————————————————————————————————————————————————
# Endpoint INDEX (interface Web + documentation + rendu du canvas)
# —————————————————————————————————————————————————

@app.route('/')
def index():
    # Préparer le rendu initial du canvas
    with lock:
        initial = '\n'.join(''.join(ch if ch!=' ' else '·' for ch in row) for row in canvas)
    html = f'''<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <title>PaintSource Web & API</title>
  <style>
    body {{ background: #111; color: #ddd; font-family: monospace; padding: 10px; }}
    #canvas {{ line-height: 1; white-space: pre; font-size: 12px; margin-top: 20px; }}
    pre {{ background: #222; padding: 10px; overflow-x: auto; }}
  </style>
</head>
<body>
  <h1>PaintSource Web & API</h1>
  <h2>Interface Web</h2>
  <p>Dashboard collaboratif :</p>
  <div id="canvas">{initial}</div>

  <h2>API Endpoints</h2>
  <pre>
GET  /canvas          -> Renvoie le canvas complet (JSON 2D array)
GET  /canvas/stream   -> SSE (Server-Sent Events) pour mises à jour en temps réel
POST /canvas          -> JSON {{ x:int, y:int, ch:str }} pour dessiner un caractère
POST /canvas/reset    -> Réinitialise le canvas
  </pre>

  <h2>Exemples</h2>
  <pre>
# Récupérer l'état complet :
curl http://localhost:5000/canvas

# Souscrire au stream SSE :
curl -N http://localhost:5000/canvas/stream

# Dessiner un caractère 'A' en (10,5) :
  curl -X POST -H "Content-Type: application/json" \
       -d '{{"x":10,"y":5,"ch":"A"}}' \
       http://localhost:5000/canvas

# Reset :
curl -X POST http://localhost:5000/canvas/reset
  </pre>

  <script>
    const W = {CANVAS_W}, H = {CANVAS_H};
    const API = window.location.origin;
    const stream = new EventSource(API + '/canvas/stream');
    let grid = Array.from({{ length: H }}, () => Array(W).fill(' '));
    const container = document.getElementById('canvas');

    function render() {{
      container.textContent = grid.map(row => row.map(ch => ch===' ' ? '·' : ch).join('')).join('\n');
    }}

    stream.onmessage = e => {{
      const msg = JSON.parse(e.data);
      if (msg.full) {{ grid = msg.full; }}
      else if (msg.reset) {{ grid = Array.from({{ length: H }}, () => Array(W).fill(' ')); }}
      else if (msg.x !== undefined) {{ grid[msg.y][msg.x] = msg.ch; }}
      render();
    }};

    container.addEventListener('click', ev => {{
      const rect = container.getBoundingClientRect();
      const x = Math.floor((ev.clientX - rect.left) / 8);
      const y = Math.floor((ev.clientY - rect.top ) / 16);
      const ch = prompt('Caractère à dessiner :','*');
      if (!ch) return;
      fetch(API+'/canvas', {{
        method:'POST', headers:{{'Content-Type':'application/json'}},
        body: JSON.stringify({{x,y,ch:ch[0]}})
      }});
    }});

    // Affiche immédiatement l'état initial
    render();
  </script>
</body>
</html>'''
    return Response(html, mimetype='text/html')

# —————————————————————————————————————————————————
# Lancement du serveur
# —————————————————————————————————————————————————

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, threaded=True)
