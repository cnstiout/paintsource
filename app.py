#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from flask import Flask, Response, request, jsonify, send_file
import json, os, threading, socket

PORT = 5000
W, H = 80, 24
DATA_FILE = "canvas_state.json"
canvas = [[" "]*W for _ in range(H)]
subscribers = []
lock = threading.Lock()

# Charger état existant
if os.path.exists(DATA_FILE):
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                canvas = data
    except Exception:
        pass

app = Flask(__name__)

# Helpers
def save_canvas():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(canvas, f)

def local_ips():
    ips = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ips.append(s.getsockname()[0])
        s.close()
    except Exception:
        pass
    return ips or ["127.0.0.1"]

def notify_all(msg):
    dead = []
    for q in list(subscribers):
        try:
            q.put(json.dumps(msg))
        except Exception:
            dead.append(q)
    for q in dead:
        if q in subscribers:
            subscribers.remove(q)

# Routes
@app.route("/")
def index():
    return f"""<!doctype html>
<html>
<head><meta charset="utf-8"><title>PaintSource</title>
<style>
body{{background:#111;color:#ddd;font-family:monospace;margin:0;}}
#cv{{display:block;cursor:crosshair;background:#fff;}}
</style>
</head>
<body>
<canvas id="cv"></canvas>
<script>
const W={W}, H={H};
let grid = Array.from({{length:H}},_=>Array(W).fill(" "));
const cv=document.getElementById('cv'), ctx=cv.getContext('2d');
let cell=14, down=false, btn=0, keyChar=null;

function resize(){{cell=Math.floor(Math.min(window.innerWidth/W, window.innerHeight/H));
  cv.width=W*cell; cv.height=H*cell; redraw();}}
function drawCell(x,y,ch){{ctx.fillStyle='#fff';ctx.fillRect(x*cell,y*cell,cell,cell);
  if(ch!==' '){{ctx.fillStyle='#000';ctx.fillText(ch,x*cell+cell/2,y*cell+cell*0.8);}}}}
function redraw(){{ctx.clearRect(0,0,cv.width,cv.height);
  ctx.font=`${{cell-2}}px monospace`;ctx.textAlign='center';
  for(let y=0;y<H;y++)for(let x=0;x<W;x++)drawCell(x,y,grid[y][x]);}}
function xy(ev){{return [Math.floor(ev.offsetX/cell),Math.floor(ev.offsetY/cell)];}}
function chForBtn(){{if(keyChar) return keyChar; return (btn===2)?'#':' ';}}
function paint(ev){{if(!down) return; let [x,y]=xy(ev);
  if(x<0||x>=W||y<0||y>=H) return; let ch=chForBtn();
  fetch('/draw',{{method:'POST',headers:{{'Content-Type':'application/json'}},
  body:JSON.stringify({{x,y,ch}})}});}}

cv.onpointerdown=e=>{{down=true;btn=e.button===2?2:1;paint(e);}};
cv.onpointermove=paint;
cv.onpointerup=()=>{{down=false;}};
cv.oncontextmenu=e=>e.preventDefault();
window.onkeydown=e=>{{if(e.key.length===1)keyChar=e.key;}};
window.onkeyup=e=>{{if(e.key===keyChar)keyChar=null;}};
window.onresize=resize;

fetch('/canvas').then(r=>r.json()).then(g=>{{grid=g;resize();}});
const es=new EventSource('/stream');
es.onmessage=e=>{{let m=JSON.parse(e.data);
 if(m.full){{grid=m.full;resize();}}
 else if(m.reset){{grid=Array.from({{length:H}},_=>Array(W).fill(" "));redraw();}}
 else{{grid[m.y][m.x]=m.ch;drawCell(m.x,m.y,m.ch);}}}};
</script>
</body>
</html>"""

@app.route("/canvas")
def get_canvas():
    with lock:
        return jsonify(canvas)

@app.route("/draw", methods=["POST"])
def draw():
    data = request.json
    x,y,ch = data.get("x"), data.get("y"), data.get("ch")
    if isinstance(x,int) and isinstance(y,int) and 0<=x<W and 0<=y<H and isinstance(ch,str) and len(ch)==1:
        with lock:
            canvas[y][x] = ch
            save_canvas()
        notify_all({"x":x,"y":y,"ch":ch})
        return jsonify(success=True)
    return jsonify(success=False), 400

@app.route("/reset", methods=["POST"])
def reset():
    with lock:
        for y in range(H):
            for x in range(W):
                canvas[y][x] = " "
        save_canvas()
    notify_all({"reset":True})
    return jsonify(success=True)

@app.route("/stream")
def stream():
    from queue import SimpleQueue
    q = SimpleQueue()
    subscribers.append(q)
    def gen():
        q.put(json.dumps({"full": canvas}))
        while True:
            try:
                msg = q.get()
                yield f"data: {msg}\n\n"
            except GeneratorExit:
                break
    return Response(gen(), mimetype="text/event-stream")

if __name__ == "__main__":
    ips = local_ips()
    print("\nPaintSource est prêt ✨  Ouvre depuis ton téléphone :")
    for ip in ips:
        print(f"  → http://{ip}:{PORT}/")
    print(f"  → http://{socket.gethostname()}.local:{PORT}/ (si mDNS activé)\n")
    app.run(host="0.0.0.0", port=PORT, threaded=True)
