# term_client.py — PaintSource v1 TTY client (toggle-only)
import asyncio, curses, json, websockets, time

WS_URL = "ws://127.0.0.1:8765/ws"

def draw_pixel(stdscr, x, y, on):
    ch = "█" if on else " "
    try: stdscr.addstr(y, x, ch)
    except curses.error: pass

async def recv_loop(stdscr, ws, grid):
    while True:
        m = json.loads(await ws.recv())
        t = m.get("type")
        if t == "state":
            stdscr.clear()
            for p in m.get("pixels", []):
                draw_pixel(stdscr, p["x"], p["y"], True)
            status(stdscr, grid); stdscr.refresh()
        elif t == "system" and m.get("event") == "clear":
            stdscr.clear(); status(stdscr, grid); stdscr.refresh()
        elif t == "op":
            pts = m.get("op", {}).get("points", [])
            states = m.get("op", {}).get("states", [])
            for (x,y), s in zip(pts, states):
                draw_pixel(stdscr, x, y, bool(s))
            status(stdscr, grid); stdscr.refresh()

def status(stdscr, grid):
    rows, cols = stdscr.getmaxyx()
    msg = f"Target: {grid['w']}x{grid['h']} • Your term: {cols}x{rows} • q=quit"
    try: stdscr.addstr(0, 0, msg[:max(0, cols-1)])
    except curses.error: pass

async def send_toggle(ws, x, y):
    await ws.send(json.dumps({"v":1,"type":"op","room":"paintsource/global",
                              "op":{"tool":"toggle","points":[[int(x),int(y)]]}}))

async def main(stdscr):
    curses.curs_set(0); stdscr.nodelay(True); stdscr.keypad(True)
    curses.mouseinterval(0)
    try: curses.mousemask(curses.ALL_MOUSE_EVENTS | curses.REPORT_MOUSE_POSITION)
    except Exception: pass

    grid = {"w":160,"h":48}
    status(stdscr, grid); stdscr.refresh()

    async with websockets.connect(WS_URL) as ws:
        # learn size from initial state
        first = json.loads(await ws.recv())
        if first.get("type") == "state":
            grid["w"] = int(first.get("w", grid["w"]))
            grid["h"] = int(first.get("h", grid["h"]))
            stdscr.clear()
            for p in first.get("pixels", []):
                draw_pixel(stdscr, p["x"], p["y"], True)
            status(stdscr, grid); stdscr.refresh()
        asyncio.create_task(recv_loop(stdscr, ws, grid))

        drawing=False
        while True:
            k = stdscr.getch()
            if k == -1:
                await asyncio.sleep(0.01); continue
            if k in (ord('q'), 27): break
            if k == curses.KEY_MOUSE:
                try: _id, mx, my, _z, bstate = curses.getmouse()
                except curses.error: continue
                if not (0 <= mx < grid["w"] and 0 <= my < grid["h"]): continue
                if bstate & (curses.BUTTON1_PRESSED | curses.BUTTON1_CLICKED):
                    drawing=True; await send_toggle(ws, mx, my)
                elif drawing and (bstate & getattr(curses, "REPORT_MOUSE_POSITION", 0) or bstate & getattr(curses, "BUTTON1_PRESSED", 0)):
                    await send_toggle(ws, mx, my)
                if bstate & getattr(curses, "BUTTON1_RELEASED", 0):
                    drawing=False

if __name__ == "__main__":
    curses.wrapper(lambda scr: asyncio.run(main(scr)))
