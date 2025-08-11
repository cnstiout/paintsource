#!/usr/bin/env python3
import os, json, socket
from flask import Flask, Response, request, jsonify, send_from_directory
from flask_cors import CORS
from threading import Lock

# -------------------
# CONFIG
# -------------------
CANVAS_W, CANVAS_H = 80, 24
SAVE_FILE = "canvas_state.json"
BASE_PATH = os.environ.get("PAINTSOURCE_BASE", "/paintsource")  # sous-chemin proxy
lock = Lock()

# -------------------
# ETAT GLOBAL
# -------------------
if os.path.exists(SAVE_FILE):
    with open(SAVE_FILE, "r") as f:
        canvas = json.load(f)
else:
    canvas = [[" " for _ in range(CANVAS_W)] for _ in range(CANVAS_H)]

subscribers = set()

# -------------------
# FONCTIONS
# -------------------
def save_canvas():
    with open(SAVE_FILE, "w") as f:
        json.dump(canvas, f)

def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip

# -------------------
# FLASK
# -------------------
app = Flask(__name__)
CORS(app)

@app.route(f"{BASE_PATH}/")
def index():
    return send_from_directory(".", "index.html")

@app.route(f"{BASE_PATH}/canvas", methods=["GET"])
def get_canvas():
    with lock:
        return jsonify(canvas)

@app.route(f"{BASE_PATH}/canvas", methods=["POST"])
def update_canvas():
    data = request.get_json(force=True)
    x, y, ch = data.get("x"), data.get("y"), data.get("ch", " ")
    with lock:
        if 0 <= x < CANVAS_W and 0 <= y < CANVAS_H:
            canvas[y][x] = ch
            save_canvas()
            for q in list(subscribers):
                q.put(json.dumps({"x": x, "y": y, "ch": ch}))
    return jsonify({"status": "ok"})

@app.route(f"{BASE_PATH}/reset", methods=["POST"])
def reset_canvas():
    with lock:
        for y in range(CANVAS_H):
            for x in range(CANVAS_W):
                canvas[y][x] = " "
        save_canvas()
    return jsonify({"status": "reset"})

@app.route(f"{BASE_PATH}/stream")
def stream():
    def event_stream(q):
        try:
            while True:
                data = q.get()
                yield f"data: {data}\n\n"
        except GeneratorExit:
            pass

    from queue import Queue
    q = Queue()
    subscribers.add(q)
    return Response(event_stream(q), mimetype="text/event-stream")

# -------------------
# PAGE HTML
# -------------------
@app.route(f"{BASE_PATH}/index.html")
def serve_index():
    return f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>PaintSource</title>
<style>
  body {{ background:#111; color:white; font-family:monospace; }}
  canvas {{ background:#222; display:block; margin:auto; image-rendering:pixelated; }}
</style>
</head>
<body>
<canvas id="c" width="{CANVAS_W*10}" height="{CANVAS_H*10}"></canvas>
<script>
const W = {CANVAS_W}, H = {CANVAS_H};
const CELL = 10;
const BASE = "{BASE_PATH}";
let charDraw = "█";
let canvas = document.getElementById("c");
let ctx = canvas.getContext("2d");

function drawGrid() {{
  ctx.fillStyle = "#fff";
  ctx.fillRect(0,0,W*CELL,H*CELL);
  ctx.fillStyle = "#000";
  for (let y=0;y<H;y++) for (let x=0;x<W;x++) {{
    if (grid[y][x] !== " ") {{
      ctx.fillRect(x*CELL,y*CELL,CELL,CELL);
    }}
  }}
}}

let grid = [];
fetch(BASE+"/canvas").then(r=>r.json()).then(data=>{{grid=data; drawGrid();}});

canvas.addEventListener("mousedown", e => {{
  e.preventDefault();
  drawAtEvent(e);
  canvas.addEventListener("mousemove", drawAtEvent);
}});
canvas.addEventListener("mouseup", e => {{
  canvas.removeEventListener("mousemove", drawAtEvent);
}});
canvas.addEventListener("contextmenu", e => e.preventDefault());

function drawAtEvent(e) {{
  const rect = canvas.getBoundingClientRect();
  const x = Math.floor((e.clientX - rect.left) / CELL);
  const y = Math.floor((e.clientY - rect.top) / CELL);
  const ch = e.button === 2 ? " " : charDraw;
  grid[y][x] = ch;
  drawGrid();
  fetch(BASE+"/canvas", {{method:"POST", headers:{{"Content-Type":"application/json"}}, body:JSON.stringify({{x:x,y:y,ch:ch}})}})
}}

document.addEventListener("keydown", e => {{
  if (e.key.length === 1) charDraw = e.key;
}});

// SSE updates
const evt = new EventSource(BASE+"/stream");
evt.onmessage = (e) => {{
  const data = JSON.parse(e.data);
  grid[data.y][data.x] = data.ch;
  drawGrid();
}};
</script>
</body>
</html>
"""

# -------------------
# MAIN
# -------------------
if __name__ == "__main__":
    ip = get_local_ip()
    print(f"\nPaintSource est prêt ✨  Ouvre depuis ton téléphone :")
    print(f"  → http://{ip}:5000{BASE_PATH}/")
    print(f"  → http://{socket.gethostname()}.local:5000{BASE_PATH}/ (si mDNS)")
    app.run(host="0.0.0.0", port=5000)
