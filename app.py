# app.py — PaintSource PRO (stroke-lock web + letters + persistence + safe HTML)
import asyncio, json, argparse, time, pathlib
from typing import Dict, Tuple, Optional
from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.websockets import WebSocketDisconnect
import uvicorn

def make_app(cols: int, rows: int, scale: int, data_dir: str, autosave_sec: int):
    app = FastAPI()
    GRID_W = int(cols)
    GRID_H = int(rows)
    SCALE  = max(1, int(scale))
    AUTOSAVE_SEC = max(1, int(autosave_sec))

    framebuffer: Dict[Tuple[int,int], Optional[str]] = {}
    clients = set()

    DATA_DIR = pathlib.Path(data_dir).expanduser().resolve()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    STATE_PATH = DATA_DIR / "state.json"
    dirty_flag = {"dirty": False}
    autosave_task = {"task": None}

    def save_state():
        data = {"w": GRID_W, "h": GRID_H,
                "pixels": [{"x":x,"y":y,"char":ch} for (x,y), ch in framebuffer.items() if ch],
                "saved_at": int(time.time())}
        tmp = STATE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False))
        tmp.replace(STATE_PATH)

    def load_state():
        if not STATE_PATH.exists(): return
        try:
            data = json.loads(STATE_PATH.read_text())
        except Exception:
            return
        for p in data.get("pixels", []):
            try:
                x, y = int(p["x"]), int(p["y"]); ch = p.get("char")
            except Exception:
                continue
            if 0 <= x < GRID_W and 0 <= y < GRID_H and ch:
                framebuffer[(x,y)] = ch

    async def autosave_loop():
        while True:
            await asyncio.sleep(AUTOSAVE_SEC)
            if dirty_flag["dirty"]:
                try: save_state()
                except Exception: pass
                dirty_flag["dirty"] = False

    HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
  <meta charset='utf-8'>
  <title>PaintSource — __GRID_W__×__GRID_H__</title>
  <style>
    html,body{margin:0;height:100%;background:#111;color:#eee;font-family:ui-monospace, SFMono-Regular, Menlo, Consolas, monospace}
    #wrap{padding:16px}
    #c{border:1px solid #444;background:#000;image-rendering:pixelated;cursor:crosshair;display:block}
    .status{opacity:.8;margin:8px 16px}
  </style>
</head>
<body>
<div id="wrap">
  <h3 style="padding:16px 16px 0 16px;margin:0">PaintSource — __GRID_W__×__GRID_H__</h3>
  <canvas id="c" width="__CANVAS_W__" height="__CANVAS_H__"></canvas>
  <div class="status" id="status">WS: connecting… • Mode: idle</div>
</div>
<script>
const W = __GRID_W__, H = __GRID_H__, SCALE = __SCALE__;
const c = document.getElementById('c');
const ctx = c.getContext('2d', { alpha: false });
ctx.imageSmoothingEnabled = false;
ctx.textBaseline = 'top';
ctx.font = (SCALE) + 'px ui-monospace, SFMono-Regular, Menlo, Consolas, monospace';

const filled = new Set();
function key(x,y){ return x+','+y; }
function setLocal(x,y,ch){
  const k = key(x,y);
  if(!ch){ filled.delete(k); } else { filled.add(k); }
}

function drawCell(x,y,ch){
  ctx.fillStyle = '#000';
  ctx.fillRect(x*SCALE, y*SCALE, SCALE, SCALE);
  if(!ch) return;
  if(ch === '█'){
    ctx.fillStyle = '#fff';
    ctx.fillRect(x*SCALE, y*SCALE, SCALE, SCALE);
  } else {
    ctx.fillStyle = '#fff';
    ctx.fillText(ch, x*SCALE, y*SCALE);
  }
  setLocal(x,y,ch);
}

const ws = new WebSocket((location.protocol==='https:'?'wss':'ws')+'://'+location.host+'/ws');
const statusEl = document.getElementById('status');
function setStatus(conn, mode){ statusEl.textContent = 'WS: ' + conn + ' • Mode: ' + mode; }
ws.onopen = ()=> setStatus('connected', 'idle');
ws.onclose = ()=> setStatus('disconnected', 'idle');
ws.onerror = ()=> setStatus('error', 'idle');
ws.onmessage = ev => {
  const m = JSON.parse(ev.data);
  if(m.type==='state'){
    ctx.fillStyle='#000'; ctx.fillRect(0,0,W*SCALE,H*SCALE);
    filled.clear();
    for(const p of m.pixels||[]) drawCell(p.x, p.y, p.char);
  } else if(m.type==='system' && m.event==='clear'){
    ctx.fillStyle='#000'; ctx.fillRect(0,0,W*SCALE,H*SCALE);
    filled.clear();
  } else if(m.type==='op' && m.op){
    const pts = m.op.points||[];
    const chars = m.op.chars||[];
    for(let i=0;i<pts.length;i++){
      const [x,y] = pts[i];
      const ch = chars.length ? chars[i] : null;
      drawCell(x,y,ch);
    }
  }
};

let drawing=false;
let strokeChar = null;
let currentBrush = null;
let lastX=null, lastY=null;

window.addEventListener('keydown', (e)=>{
  if(e.key && e.key.length === 1){
    currentBrush = e.key;
    if(!drawing) setStatus('connected', 'char ' + JSON.stringify(currentBrush));
  }
});
window.addEventListener('keyup', (e)=>{
  if(e.key && e.key.length === 1 && currentBrush === e.key){
    currentBrush = null;
    if(!drawing) setStatus('connected', 'idle');
  }
});

function clamp(n, min, max){ return Math.max(min, Math.min(max, n)); }
function canvasToCell(e){
  const r=c.getBoundingClientRect();
  const lx = Math.floor((e.clientX - r.left)  * (c.width  / r.width));
  const ly = Math.floor((e.clientY - r.top)   * (c.height / r.height));
  const x = clamp(Math.floor(lx / SCALE), 0, W-1);
  const y = clamp(Math.floor(ly / SCALE), 0, H-1);
  return [x,y];
}

function bresenham(x0,y0,x1,y1){
  const pts=[];
  let dx=Math.abs(x1-x0), dy=-Math.abs(y1-y0);
  let sx=x0<x1?1:-1, sy=y0<y1?1:-1, err=dx+dy;
  while(true){
    pts.push([x0,y0]);
    if(x0===x1 && y0===y1) break;
    let e2=2*err;
    if(e2>=dy){ err+=dy; x0+=sx; }
    if(e2<=dx){ err+=dx; y0+=sy; }
  }
  return pts;
}

function sendSet(points, ch){
  if(ws.readyState!==1 || points.length===0) return;
  ws.send(JSON.stringify({
    v:1, type:'op', room:'paintsource/global',
    user:{nick:'web'}, ts:Date.now(),
    op:{tool:'set', mode:'set', points:points, char: ch ?? null}
  }));
}

c.addEventListener('contextmenu', e=>e.preventDefault());
c.addEventListener('mousedown', e=>{
  drawing=true;
  const [x,y]=canvasToCell(e);
  let targetChar = null;
  if(currentBrush && currentBrush.length===1){
    targetChar = currentBrush;
    setStatus('connected', 'char ' + JSON.stringify(targetChar));
  }else{
    const wasFilled = filled.has(key(x,y));
    targetChar = wasFilled ? null : '█';
    setStatus('connected', targetChar ? 'WHITE' : 'ERASE');
  }
  strokeChar = targetChar;
  lastX=x; lastY=y;
  drawCell(x,y,targetChar);
  sendSet([[x,y]], targetChar);
});
c.addEventListener('mousemove', e=>{
  if(!drawing) return;
  const [x,y]=canvasToCell(e);
  if(x===lastX && y===lastY) return;
  const pts = bresenham(lastX,lastY,x,y);
  lastX=x; lastY=y;
  for(const [px,py] of pts){ drawCell(px,py,strokeChar); }
  sendSet(pts, strokeChar);
});
function stopStroke(){
  drawing=false; strokeChar=null; lastX=lastY=null;
  setStatus('connected', currentBrush ? 'char ' + JSON.stringify(currentBrush) : 'idle');
}
c.addEventListener('mouseup',   stopStroke);
c.addEventListener('mouseleave',stopStroke);
</script>
</body>
</html>"""

    HTML = (HTML_TEMPLATE
            .replace("__GRID_W__", str(cols))
            .replace("__GRID_H__", str(rows))
            .replace("__SCALE__", str(scale))
            .replace("__CANVAS_W__", str(cols * scale))
            .replace("__CANVAS_H__", str(rows * scale))
           )

    def set_cell(x:int, y:int, ch: Optional[str]):
        framebuffer[(x,y)] = ch
        dirty_flag["dirty"] = True

    def toggle_cell(x:int, y:int):
        cur = framebuffer.get((x,y))
        framebuffer[(x,y)] = None if cur == '█' else '█'
        dirty_flag["dirty"] = True

    def serialize_state():
        pixels = [{"x":x,"y":y,"char":ch} for (x,y), ch in framebuffer.items() if ch]
        return {"type":"state", "w": GRID_W, "h": GRID_H, "pixels": pixels}

    @app.get("/", response_class=HTMLResponse)
    async def index():
        return HTML

    @app.get("/state")
    async def state():
        return JSONResponse(serialize_state())

    @app.post("/clear")
    async def clear():
        framebuffer.clear()
        dirty_flag["dirty"] = True
        msg = {"type":"system","event":"clear"}
        dead = []
        for ws in list(clients):
            try: await ws.send_text(json.dumps(msg))
            except Exception: dead.append(ws)
        for ws in dead:
            clients.discard(ws)
        return {"ok": True}

    @app.post("/save")
    async def manual_save():
        save_state()
        dirty_flag["dirty"] = False
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
                op = msg.get("op", {})
                tool = op.get("tool")
                pts = op.get("points", [])
                char = op.get("char", None)
                mode = op.get("mode")

                safe_pts, chars = [], []
                for x,y in pts:
                    try:
                        x = int(x); y = int(y)
                    except Exception:
                        continue
                    if not (0 <= x < GRID_W and 0 <= y < GRID_H):
                        continue
                    if tool == "set" and mode == "set":
                        set_cell(x,y,char if char else None)
                    elif tool in ("put","toggle"):
                        if "char" in op and op["char"] is not None:
                            set_cell(x,y,op["char"])
                        else:
                            toggle_cell(x,y)
                    else:
                        toggle_cell(x,y)
                    safe_pts.append([x,y])
                    chars.append(framebuffer.get((x,y)))

                if not safe_pts:
                    continue
                enriched = {"type":"op", "op":{"tool": tool or "put","points":safe_pts,"chars":chars}}
                dead = []
                for peer in list(clients):
                    try: await peer.send_text(json.dumps(enriched))
                    except Exception: dead.append(peer)
                for peer in dead:
                    clients.discard(peer)
        except WebSocketDisconnect:
            pass
        finally:
            clients.discard(ws)

    @app.on_event("startup")
    async def _startup():
        load_state()
        autosave_task["task"] = asyncio.create_task(autosave_loop())

    @app.on_event("shutdown")
    async def _shutdown():
        try: save_state()
        except Exception: pass
        t = autosave_task.get("task")
        if t: t.cancel()

    return app

def main():
    ap = argparse.ArgumentParser(description="PaintSource PRO")
    ap.add_argument("--cols", "-c", type=int, default=80, help="Canvas columns (width)")
    ap.add_argument("--rows", "-r", type=int, default=24, help="Canvas rows (height)")
    ap.add_argument("--scale", "-s", type=int, default=10, help="Web UI scale (px per cell)")
    ap.add_argument("--host", default="127.0.0.1", help="Bind host")
    ap.add_argument("--port", "-p", type=int, default=7100, help="Bind port")
    ap.add_argument("--data", default="./data", help="Directory for saved JSON state")
    ap.add_argument("--autosave-sec", type=int, default=3, help="Autosave interval (seconds)")
    args = ap.parse_args()

    app = make_app(args.cols, args.rows, args.scale, args.data, args.autosave_sec)
    uvicorn.run(app, host=args.host, port=args.port)

if __name__ == "__main__":
    main()
