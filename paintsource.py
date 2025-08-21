#!/usr/bin/env python3
import argparse, socketserver, threading, json
from flask import Flask, Response, request

# =========================
#  CONFIG PAR DÉFAUT
# =========================
W, H = 80, 24
PORT_WEB = 8080
PORT_TTY = 2323
GRID = [[" " for _ in range(W)] for _ in range(H)]
clients = []   # SSE (web)
terms   = []   # NC/telnet

# =========================
#  SERVEUR WEB (Flask)
# =========================
app = Flask(__name__)

@app.route("/")
def index():
    return HTML_PAGE, 200, {"Content-Type": "text/html"}

@app.route("/canvas")
def canvas_state():
    return {"grid": GRID}

@app.route("/canvas", methods=["POST"])
def canvas_update():
    d = request.json
    x, y, ch = d["x"], d["y"], d["ch"]
    if 0 <= x < W and 0 <= y < H:
        GRID[y][x] = ch
        broadcast({"x": x, "y": y, "ch": ch})
    return {"ok": 1}

@app.route("/stream")
def stream():
    def gen():
        q = queue_subscribe()
        try:
            for ev in q:
                yield f"data: {json.dumps(ev)}\n\n"
        finally:
            queue_unsubscribe(q)
    return Response(gen(), mimetype="text/event-stream")

# ============== HTML/JS PAGE ==================
HTML_PAGE = f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><title>PaintSource</title>
<style>
  :root{{--bg:#111;--fg:#ddd}}
  html,body{{height:100%;margin:0;background:var(--bg);color:var(--fg);font-family:monospace}}
  header{{padding:6px}}
  #wrap{{height:calc(100% - 30px);}}
  canvas{{display:block;width:100%;height:100%;image-rendering:pixelated;background:#fff;cursor:crosshair}}
  small{{opacity:.7}}
</style></head><body>
<header><strong>PaintSource</strong> – cliquer pour dessiner (gauche=blanc, droit=noir, touche=caractère)</header>
<div id="wrap"><canvas id="cv"></canvas></div>
<script>
const W={W}, H={H}, BASE="";
let grid=null;
const cv=document.getElementById('cv'), ctx=cv.getContext('2d');
let down=false, buttons=0, keyChar=null;

function resize(){{
  cv.width=cv.clientWidth; cv.height=cv.clientHeight;
  redraw();
}}
function drawCell(x,y,ch){{
  const cellW = cv.width/W, cellH=cv.height/H;
  ctx.fillStyle='#fff'; ctx.fillRect(x*cellW,y*cellH,cellW,cellH);
  if(ch===' ') return;
  if(ch==='#'){{ ctx.fillStyle='#000'; ctx.fillRect(x*cellW,y*cellH,cellW,cellH); return; }}
  ctx.fillStyle='#000'; ctx.font=`${{Math.floor(Math.min(cellW,cellH)*0.9)}}px monospace`;
  ctx.textBaseline='middle'; ctx.textAlign='center';
  ctx.fillText(ch, x*cellW+cellW/2, y*cellH+cellH/2);
}}
function redraw(){{
  if(!grid) return;
  for(let y=0;y<H;y++) for(let x=0;x<W;x++) drawCell(x,y,grid[y][x]);
}}
function pos(ev){{
  const r=cv.getBoundingClientRect();
  const x=Math.floor((ev.clientX-r.left)/r.width*W);
  const y=Math.floor((ev.clientY-r.top )/r.height*H);
  return [Math.max(0,Math.min(W-1,x)), Math.max(0,Math.min(H-1,y))];
}}
function chForInput(){{
  if(keyChar && keyChar.length===1) return keyChar;
  return (buttons & 2) ? '#' : ' ';
}}
async function put(x,y,ch){{
  await fetch(`${{BASE}}/canvas`, {{
    method:'POST', headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{x,y,ch}})
  }});
}}
function paint(ev){{
  if(!down) return;
  const [x,y]=pos(ev); const ch=chForInput();
  put(x,y,ch);
}}
cv.addEventListener('pointerdown', e=>{{ down=true; buttons=e.buttons||(e.button===2?2:1); paint(e); cv.setPointerCapture(e.pointerId); }});
cv.addEventListener('pointermove', e=>{{ buttons=e.buttons; paint(e); }});
cv.addEventListener('pointerup',   e=>{{ buttons=e.buttons; if(e.buttons===0){{ down=false; cv.releasePointerCapture(e.pointerId); }} }});
cv.addEventListener('contextmenu', e=>e.preventDefault());
window.addEventListener('keydown', e=>{{ if(e.key.length===1) keyChar=e.key; }});
window.addEventListener('keyup',   e=>{{ if(e.key===keyChar) keyChar=null; }});
window.addEventListener('resize', resize);

fetch(`${{BASE}}/canvas`).then(r=>r.json()).then(g=>{{ grid=g.grid; resize(); }});
const es=new EventSource(`${{BASE}}/stream`);
es.onmessage = e => {{
  const m=JSON.parse(e.data);
  if(m.full){{ grid=m.full; resize(); }}
  else{{ if(grid){{ grid[m.y][m.x]=m.ch; drawCell(m.x,m.y,m.ch); }} }}
}};
</script></body></html>
"""

# =========================
#  BROADCAST / SSE QUEUES
# =========================
def broadcast(msg):
    for q in list(clients):
        q.append(msg)
    for t in list(terms):
        try:
            x,y,ch = msg["x"], msg["y"], msg["ch"]
            terms[t].send_update(x,y,ch)
        except: pass

def queue_subscribe():
    q=[]
    clients.append(q)
    return q
def queue_unsubscribe(q):
    if q in clients: clients.remove(q)

# =========================
#  TELNET/NC SERVER
# =========================
class TermHandler(socketserver.BaseRequestHandler):
    def setup(self):
        self.request.sendall(b"Welcome to PaintSource!\\n")
        self.request.sendall(b"+" + b"-"*W + b"+\\n")
        for row in GRID:
            self.request.sendall(b"|" + "".join(row).encode() + b"|\\n")
        self.request.sendall(b"+" + b"-"*W + b"+\\n")
        terms.append(self)

    def handle(self):
        while True:
            data=self.request.recv(1)
            if not data: break
            ch=data.decode(errors="ignore")
            if ch.strip():
                # juste écrit en (0,0) pour démo, tu peux rajouter un vrai curseur partagé
                GRID[0][0]=ch[0]
                broadcast({"x":0,"y":0,"ch":ch[0]})

    def finish(self):
        if self in terms: terms.remove(self)

    def send_update(self,x,y,ch):
        # simplifié: renvoie toute la grille
        pass

# =========================
#  MAIN
# =========================
if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--ip",default="0.0.0.0")
    parser.add_argument("--port",type=int,default=PORT_WEB)
    parser.add_argument("--w",type=int,default=W)
    parser.add_argument("--h",type=int,default=H)
    args=parser.parse_args()

    W,H=args.w,args.h

    # Telnet server thread
    tty_srv=socketserver.ThreadingTCPServer((args.ip,PORT_TTY), TermHandler)
    threading.Thread(target=tty_srv.serve_forever,daemon=True).start()
    print(f"[PaintSource] telnet/nc on {args.ip}:{PORT_TTY}")

    # Flask (web) server
    app.run(host=args.ip, port=args.port, threaded=True)
