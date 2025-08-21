#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os, json, socket
from queue import SimpleQueue
from threading import Lock
from flask import Flask, Response, request, jsonify

# ─── Config ────────────────────────────────────────────────────────────────
W, H = 80, 24                          # grille 80x24
DATA_FILE = "canvas_state.json"
BASE = os.environ.get("PAINTSOURCE_BASE", "/").rstrip("/")
if BASE == "": BASE = "/"              # "" -> racine
# Exemple: BASE="/" (dev local) ou BASE="/paintsource" (derrière Apache)

# ─── État ──────────────────────────────────────────────────────────────────
lock = Lock()
if os.path.exists(DATA_FILE):
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            canvas = json.load(f)
        # garde-fou sur dimensions
        if not (isinstance(canvas, list) and len(canvas)==H and all(len(r)==W for r in canvas)):
            raise ValueError
    except Exception:
        canvas = [[" "]*W for _ in range(H)]
else:
    canvas = [[" "]*W for _ in range(H)]

subscribers = set()  # SimpleQueue par client SSE

def save_canvas():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(canvas, f)

def local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

# ─── App Flask ─────────────────────────────────────────────────────────────
app = Flask(__name__)

# HTML minimal (ASCII-friendly, <canvas> + SSE)
HTML = f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><title>PaintSource</title>
<style>
  :root{{--bg:#111;--fg:#ddd}}
  html,body{{height:100%;margin:0;background:var(--bg);color:var(--fg);font-family:monospace}}
  header{{padding:10px 14px}}
  #wrap{{height:calc(100% - 44px);}}
  canvas{{display:block;width:100%;height:100%;image-rendering:pixelated;background:#fff;cursor:crosshair}}
  small{{opacity:.7}}
</style></head><body>
<header><strong>PaintSource</strong>
<small> · clic gauche = blanc · clic droit = noir (#) · maintenir une touche = peindre ce caractère</small>
</header>
<div id="wrap"><canvas id="cv"></canvas></div>
<script>
const W={W}, H={H}, BASE="{BASE}";
let grid=null, cell=12, dpi=window.devicePixelRatio||1;
const cv=document.getElementById('cv'), ctx=cv.getContext('2d');
let down=false, buttons=0, keyChar=null;

function resize(){{
  const r=cv.getBoundingClientRect();
  cell=Math.max(6, Math.floor(Math.min(r.width/W, r.height/H)));
  cv.width=W*cell*dpi; cv.height=H*cell*dpi;
  ctx.setTransform(dpi,0,0,dpi,0,0);
  ctx.imageSmoothingEnabled=false;
  redraw();
}}
function drawCell(x,y,ch){{
  ctx.fillStyle='#fff'; ctx.fillRect(x*cell,y*cell,cell,cell);
  if(ch===' ') return;
  if(ch==='#'){{ ctx.fillStyle='#000'; ctx.fillRect(x*cell,y*cell,cell,cell); return; }}
  ctx.fillStyle='#000'; ctx.font=`${{Math.floor(cell*0.9)}}px monospace`;
  ctx.textBaseline='middle'; ctx.textAlign='center';
  ctx.fillText(ch, x*cell+cell/2, y*cell+cell/2);
}}
function redraw(){{
  if(!grid) return;
  for(let y=0;y<H;y++) for(let x=0;x<W;x++) drawCell(x,y,grid[y][x]);
}}
function pos(ev){{
  const r=cv.getBoundingClientRect();
  const x=Math.floor((ev.clientX-r.left)/cell);
  const y=Math.floor((ev.clientY-r.top )/cell);
  return [Math.max(0,Math.min(W-1,x)), Math.max(0,Math.min(H-1,y))];
}}
function chForInput(){{
  if(keyChar && keyChar.length===1) return keyChar;    // override clavier
  return (buttons & 2) ? '#' : ' ';                    // droit noir, gauche blanc
}}
async function put(x,y,ch){{
  try {{
    await fetch(`${{BASE}}/canvas`, {{
      method:'POST', headers:{{'Content-Type':'application/json'}},
      body:JSON.stringify({{x,y,ch}})
    }});
  }} catch(_){{
  }}
}}
function paint(ev){{
  if(!down) return;
  const [x,y]=pos(ev); const ch=chForInput();
  put(x,y,ch);
}}
cv.addEventListener('pointerdown', e=>{{ down=true; buttons=e.buttons||(e.button===2?2:1); paint(e); cv.setPointerCapture(e.pointerId); }});
cv.addEventListener('pointermove', e=>{{ buttons=e.buttons; paint(e); }});
cv.addEventListener('pointerup',   e=>{{ buttons=e.buttons; if(e.buttons===0){{ down=false; cv.releasePointerCapture(e.pointerId); }} }});
cv.addEventListener('pointercancel', ()=>{{ down=false; }});
cv.addEventListener('contextmenu', e=>e.preventDefault());
window.addEventListener('keydown', e=>{{ if(e.key && e.key.length===1) keyChar=e.key; }});
window.addEventListener('keyup',   e=>{{ if(e.key===keyChar) keyChar=null; }});
window.addEventListener('resize', resize);

// Init + SSE
fetch(`${{BASE}}/canvas`).then(r=>r.json()).then(g=>{{ grid=g; resize(); }});
const es=new EventSource(`${{BASE}}/stream`);
es.onmessage = e => {{
  const m=JSON.parse(e.data);
  if(m.full){{ grid=m.full; resize(); }}
  else if(m.reset){{ grid=Array(H).fill().map(_=>Array(W).fill(' ')); redraw(); }}
  else{{ if(grid){{ grid[m.y][m.x]=m.ch; drawCell(m.x,m.y,m.ch); }} }}
}};
</script>
</body></html>
"""

# ─── Routes ───────────────────────────────────────────────────────────────
@app.get(f"{BASE}/")
def index():
    return Response(HTML, mimetype="text/html; charset=utf-8")

@app.get(f"{BASE}/canvas")
def get_canvas():
    with lock:
        return jsonify(canvas)

@app.post(f"{BASE}/canvas")
def post_canvas():
    data = request.get_json(silent=True) or {}
    x, y, ch = data.get("x"), data.get("y"), data.get("ch", " ")
    if not (isinstance(x,int) and isinstance(y,int) and 0<=x<W and 0<=y<H and isinstance(ch,str) and len(ch)==1):
        return jsonify(error="bad params"), 400
    with lock:
        canvas[y][x] = ch
        save_canvas()
        # push aux abonnés
        for q in list(subscribers):
            try: q.put(json.dumps({"x":x,"y":y,"ch":ch}))
            except Exception: subscribers.discard(q)
    return jsonify(ok=True)

@app.post(f"{BASE}/reset")
def reset():
    with lock:
        for yy in range(H):
            for xx in range(W):
                canvas[yy][xx] = " "
        save_canvas()
        for q in list(subscribers):
            try: q.put(json.dumps({"reset": True}))
            except Exception: subscribers.discard(q)
    return jsonify(ok=True)

@app.get(f"{BASE}/stream")
def stream():
    q = SimpleQueue()
    subscribers.add(q)
    # état initial
    with lock:
        q.put(json.dumps({"full": canvas}))
    def gen():
        try:
            while True:
                data = q.get()
                yield f"data: {data}\n\n"
        except GeneratorExit:
            pass
        finally:
            subscribers.discard(q)
    return Response(gen(), mimetype="text/event-stream")

# ─── Lancement direct (dev) ───────────────────────────────────────────────
if __name__ == "__main__":
    ip = local_ip()
    url = f"http://{ip}:5000{'' if BASE=='/' else BASE + '/'}"
    print("\nPaintSource est prêt ✨  Ouvre depuis ton téléphone :")
    print(f"  → {url}\n")
    app.run(host="0.0.0.0", port=5000, threaded=True)
