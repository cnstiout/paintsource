# app.py — PaintSource v1 (minimal): toggle-only, fixed logical grid, web+tty
# - Web UI: click toggles a cell (█ <-> empty). Has a "Clear" button.
# - TTY client: click toggles cells.
# - WebSocket broadcast keeps everyone in sync.
# - CLI sizing: --cols/--rows/--scale, bind: --host/--port
import asyncio, json, argparse
from typing import Dict, Tuple
from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.websockets import WebSocketDisconnect
import uvicorn

def make_app(cols:int, rows:int, scale:int):
    app = FastAPI()
    GRID_W = int(cols)
    GRID_H = int(rows)
    SCALE = max(1, int(scale))

    framebuffer: Dict[Tuple[int,int], bool] = {}
    clients = set()

    HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
  <meta charset='utf-8'>
  <title>PaintSource v1 — __GRID_W__×__GRID_H__</title>
  <style>
    html,body{margin:0;height:100%;background:#111;color:#eee;font-family:sans-serif}
    #wrap{padding:16px}
    #c{border:1px solid #444;background:#000;image-rendering:pixelated;cursor:crosshair}
    .row{display:flex;gap:12px;align-items:center;margin-top:8px}
    button{background:#222;color:#eee;border:1px solid #444;padding:6px 10px;border-radius:6px}
    .status{opacity:.85}
  </style>
</head>
<body>
<div id="wrap">
  <h3>PaintSource v1 — __GRID_W__×__GRID_H__</h3>
  <canvas id="c" width="__GRID_W__" height="__GRID_H__"></canvas>
  <div class="row">
    <span class="status" id="status">WS: connecting…</span>
    <button id="clear">Clear</button>
  </div>
  <p class="status">Click toggles cells (white/black). Logical pixels are 1×1 and scaled ×__SCALE__ in CSS.</p>
</div>
<script>
const W=__GRID_W__, H=__GRID_H__, SCALE=__SCALE__;
const c=document.getElementById('c');
const ctx=c.getContext('2d', {alpha:false});
ctx.imageSmoothingEnabled=false;
c.style.width=(W*SCALE)+'px';
c.style.height=(H*SCALE)+'px';

function drawPixel(x,y,on){
  if(x<0||y<0||x>=W||y>=H) return;
  ctx.fillStyle = on ? '#fff':'#000';
  ctx.fillRect(x,y,1,1);
}

const ws=new WebSocket((location.protocol==='https:'?'wss':'ws')+'://'+location.host+'/ws');
const statusEl=document.getElementById('status');
ws.onopen = ()=> statusEl.textContent='WS: connected';
ws.onclose = ()=> statusEl.textContent='WS: disconnected';
ws.onerror = ()=> statusEl.textContent='WS: error';
ws.onmessage = ev => {
  const m = JSON.parse(ev.data);
  if(m.type==='state'){
    ctx.fillStyle='#000'; ctx.fillRect(0,0,W,H);
    for(const p of (m.pixels||[])) drawPixel(p.x,p.y,true);
  }else if(m.type==='system' && m.event==='clear'){
    ctx.fillStyle='#000'; ctx.fillRect(0,0,W,H);
  }else if(m.type==='op' && m.op){
    const pts=m.op.points||[]; const states=m.op.states||[];
    for(let i=0;i<pts.length;i++){
      const [x,y]=pts[i];
      const st = states.length?!!states[i]:true;
      drawPixel(x,y,st);
    }
  }
};

function clamp(n,min,max){return Math.max(min,Math.min(max,n));}
function sendToggle(x,y){
  if(ws.readyState!==1) return;
  ws.send(JSON.stringify({v:1,type:'op',room:'paintsource/global',op:{tool:'toggle',points:[[x,y]]}}));
}

c.addEventListener('contextmenu',e=>e.preventDefault());
c.addEventListener('mousedown', e=>{
  const r=c.getBoundingClientRect();
  const x = Math.floor((e.clientX - r.left) * (c.width / r.width));
  const y = Math.floor((e.clientY - r.top)  * (c.height / r.height));
  sendToggle(clamp(x,0,W-1), clamp(y,0,H-1));
});

document.getElementById('clear').onclick = async ()=>{ try{ await fetch('/clear',{method:'POST'});}catch(e){} };
</script>
</body>
</html>"""

    HTML = (HTML_TEMPLATE
             .replace("__GRID_W__", str(GRID_W))
             .replace("__GRID_H__", str(GRID_H))
             .replace("__SCALE__", str(SCALE)))

    def toggle_point(x:int,y:int)->bool:
        cur = framebuffer.get((x,y), False)
        new = not cur
        framebuffer[(x,y)] = new
        return new

    def serialize_state():
        return {"type":"state","w":GRID_W,"h":GRID_H,
                "pixels":[{"x":x,"y":y} for (x,y),v in framebuffer.items() if v]}

    @app.get("/", response_class=HTMLResponse)
    async def index():
        return HTML

    @app.get("/state")
    async def state():
        return JSONResponse(serialize_state())

    @app.post("/clear")
    async def clear():
        framebuffer.clear()
        msg = {"type":"system","event":"clear"}
        dead=[]
        for ws in list(clients):
            try: await ws.send_text(json.dumps(msg))
            except Exception: dead.append(ws)
        for ws in dead: clients.discard(ws)
        return {"ok": True}

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket):
        await ws.accept()
        await ws.send_text(json.dumps(serialize_state()))
        clients.add(ws)
        try:
            while True:
                raw = await ws.receive_text()
                msg = json.loads(raw)
                pts = msg.get("op", {}).get("points", [])
                safe_pts=[]; states=[]
                for x,y in pts:
                    try: x=int(x); y=int(y)
                    except Exception: continue
                    if 0<=x<GRID_W and 0<=y<GRID_H:
                        states.append(1 if toggle_point(x,y) else 0)
                        safe_pts.append([x,y])
                if not safe_pts: continue
                enriched = {"type":"op","op":{"tool":"toggle","points":safe_pts,"states":states}}
                dead=[]
                for peer in list(clients):
                    try: await peer.send_text(json.dumps(enriched))
                    except Exception: dead.append(peer)
                for peer in dead: clients.discard(peer)
        except WebSocketDisconnect:
            pass
        finally:
            clients.discard(ws)
    return app

def main():
    ap = argparse.ArgumentParser(description="PaintSource v1")
    ap.add_argument("--cols","-c", type=int, default=160, help="Canvas columns (width)")
    ap.add_argument("--rows","-r", type=int, default=48,  help="Canvas rows (height)")
    ap.add_argument("--scale","-s", type=int, default=6,  help="Web CSS scale (px per cell)")
    ap.add_argument("--host", default="127.0.0.1", help="Bind host")
    ap.add_argument("--port","-p", type=int, default=8765, help="Bind port")
    args = ap.parse_args()
    app = make_app(args.cols, args.rows, args.scale)
    uvicorn.run(app, host=args.host, port=args.port)

if __name__ == "__main__":
    main()
