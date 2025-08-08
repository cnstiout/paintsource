# term_client.py — PRO TTY (BrushChar-compatible with server features)
import asyncio, curses, json, websockets, uuid, time, argparse, string

def parse_args():
    ap = argparse.ArgumentParser(description="PaintSource TTY client")
    ap.add_argument("--ws", default="ws://127.0.0.1:7100/ws", help="WebSocket URL")
    ap.add_argument("--cols", type=int, default=None, help="Force grid width (else learn from server)")
    ap.add_argument("--rows", type=int, default=None, help="Force grid height (else learn from server)")
    return ap.parse_args()

def draw_cell(stdscr, x, y, ch):
    if ch is None: ch = " "
    try: stdscr.addstr(y, x, ch)
    except curses.error: pass

def draw_status(stdscr, grid_w, grid_h, brush):
    rows, cols = stdscr.getmaxyx()
    msg = f"Target: {grid_w}x{grid_h} • Brush: {repr(brush) if brush else 'toggle(█/ )'} • q=quit"
    try: stdscr.addstr(0, 0, msg[:max(0, cols-1)])
    except curses.error: pass

async def recv_loop(stdscr, ws, grid):
    while True:
        m = json.loads(await ws.recv())
        t = m.get("type")
        if t == "state":
            if grid["w"] is None or grid["h"] is None:
                grid["w"] = int(m.get("w", 80))
                grid["h"] = int(m.get("h", 24))
            stdscr.clear()
            for p in m.get("pixels", []):
                draw_cell(stdscr, p["x"], p["y"], p.get("char", "█"))
            draw_status(stdscr, grid["w"], grid["h"], grid.get("brush"))
            stdscr.refresh()
        elif t == "system" and m.get("event") == "clear":
            stdscr.clear(); draw_status(stdscr, grid["w"], grid["h"], grid.get("brush")); stdscr.refresh()
        elif t == "op":
            pts = m.get("op", {}).get("points", [])
            chars = m.get("op", {}).get("chars", [])
            if chars and len(chars)==len(pts):
                for (x,y), ch in zip(pts, chars):
                    draw_cell(stdscr, x, y, ch if ch is not None else " ")
                draw_status(stdscr, grid["w"], grid["h"], grid.get("brush"))
                stdscr.refresh()

async def send_draw(ws, x, y, brush):
    op = {"tool":"put","points":[[x,y]]}
    if brush and len(brush)==1:
        op["char"] = brush
    msg = {"v":1,"type":"op","room":"paintsource/global","user":{"id":str(uuid.uuid4()),"nick":"tty"},
           "ts":int(time.time()*1000),"op":op}
    await ws.send(json.dumps(msg))

async def main(stdscr, args):
    curses.curs_set(0); stdscr.nodelay(True); stdscr.keypad(True)
    curses.mouseinterval(0)
    try: curses.mousemask(curses.ALL_MOUSE_EVENTS | curses.REPORT_MOUSE_POSITION)
    except Exception: pass

    grid = {"w": args.cols, "h": args.rows, "brush": None}
    draw_status(stdscr, grid.get("w") or 80, grid.get("h") or 24, grid["brush"])
    stdscr.refresh()

    async with websockets.connect(args.ws) as ws:
        asyncio.create_task(recv_loop(stdscr, ws, grid))
        drawing=False
        while True:
            k = stdscr.getch()
            if k == -1:
                await asyncio.sleep(0.01); continue
            if k in (ord('q'), 27):
                break

            if 32 <= k <= 126:
                ch = chr(k)
                if ch in string.printable and len(ch) == 1:
                    grid["brush"] = ch
                    draw_status(stdscr, grid.get("w") or 80, grid.get("h") or 24, grid["brush"])
                    stdscr.refresh()
                    continue

            if k == curses.KEY_MOUSE and grid["w"] and grid["h"]:
                try: _id, mx, my, _z, bstate = curses.getmouse()
                except curses.error: continue
                if not (0 <= mx < grid["w"] and 0 <= my < grid["h"]): continue
                if bstate & (curses.BUTTON1_PRESSED | curses.BUTTON1_CLICKED):
                    drawing=True; await send_draw(ws, mx, my, grid["brush"])
                elif drawing and (bstate & getattr(curses, "REPORT_MOUSE_POSITION", 0) or bstate & getattr(curses, "BUTTON1_PRESSED", 0)):
                    await send_draw(ws, mx, my, grid["brush"])
                if bstate & getattr(curses, "BUTTON1_RELEASED", 0):
                    drawing=False
                    grid["brush"] = None
                    draw_status(stdscr, grid.get("w") or 80, grid.get("h") or 24, grid["brush"])
                    stdscr.refresh()

if __name__ == "__main__":
    args = parse_args()
    curses.wrapper(lambda scr: asyncio.run(main(scr, args)))
