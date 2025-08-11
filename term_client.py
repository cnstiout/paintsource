#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import curses, threading, time, json, requests, argparse

parser = argparse.ArgumentParser()
parser.add_argument("--api", default="http://127.0.0.1:5000",
                    help="Base URL du serveur PaintSource (ex: http://192.168.1.29:5000)")
args = parser.parse_args()

API = args.api.rstrip("/")
CANVAS_W, CANVAS_H = 80, 24
URL_GET   = f"{API}/canvas"
URL_POST  = f"{API}/draw"
URL_SSE   = f"{API}/stream"

canvas = [[" "]*CANVAS_W for _ in range(CANVAS_H)]
lock = threading.Lock()

def fetch_initial():
    try:
        r = requests.get(URL_GET, timeout=5)
        r.raise_for_status()
        grid = r.json()
        with lock:
            for y in range(min(CANVAS_H, len(grid))):
                for x in range(min(CANVAS_W, len(grid[y]))):
                    canvas[y][x] = grid[y][x]
    except Exception as e:
        print("Erreur fetch_initial:", e)

def sse_listener():
    while True:
        try:
            with requests.get(URL_SSE, stream=True, timeout=60) as r:
                r.raise_for_status()
                for raw in r.iter_lines():
                    if not raw or not raw.startswith(b"data:"):
                        continue
                    try:
                        m = json.loads(raw[5:].strip())
                    except Exception:
                        continue
                    with lock:
                        if "full" in m:
                            grid = m["full"]
                            for y in range(min(CANVAS_H, len(grid))):
                                for x in range(min(CANVAS_W, len(grid[y]))):
                                    canvas[y][x] = grid[y][x]
                        elif m.get("reset"):
                            for y in range(CANVAS_H):
                                for x in range(CANVAS_W):
                                    canvas[y][x] = " "
                        else:
                            x, y, ch = m["x"], m["y"], m["ch"]
                            if 0 <= x < CANVAS_W and 0 <= y < CANVAS_H:
                                canvas[y][x] = ch
        except Exception:
            time.sleep(1)

def send_update(x, y, ch):
    try:
        requests.post(URL_POST, json={"x": x, "y": y, "ch": ch}, timeout=3)
    except Exception:
        pass

def main(stdscr):
    curses.curs_set(1)
    stdscr.nodelay(True)
    x = y = 0

    def render_cell(c):
        return c if c != " " else "."

    while True:
        stdscr.clear()
        max_y, max_x = stdscr.getmaxyx()
        w = min(CANVAS_W, max_x - 2)
        h = min(CANVAS_H, max_y - 3)

        try:
            stdscr.addstr(0, 0, "+" + "-"*w + "+")
        except curses.error:
            pass

        with lock:
            for ry in range(h):
                row = "".join(render_cell(canvas[ry][cx]) for cx in range(w))
                try:
                    stdscr.addstr(1+ry, 0, "|" + row + "|")
                except curses.error:
                    pass

        try:
            stdscr.addstr(1+h, 0, "+" + "-"*w + "+")
        except curses.error:
            pass

        info = f"API: {API} ←↑↓→: bouger · taper: dessiner · Entrée: (0,0) · ESC: quitter"
        try:
            stdscr.addstr(2+h, 0, info[:max_x])
        except curses.error:
            pass

        y = max(0, min(y, h-1))
        x = max(0, min(x, w-1))
        stdscr.move(1+y, 1+x)
        stdscr.refresh()

        key = stdscr.getch()
        if   key == curses.KEY_UP:    y -= 1
        elif key == curses.KEY_DOWN:  y += 1
        elif key == curses.KEY_LEFT:  x -= 1
        elif key == curses.KEY_RIGHT: x += 1
        elif key in (10, 13):         x, y = 0, 0
        elif key == 27:               break
        elif key == -1:
            time.sleep(0.01); continue
        else:
            try:
                ch = chr(key)
            except ValueError:
                continue
            with lock:
                canvas[y][x] = ch
            send_update(x, y, ch)

if __name__ == "__main__":
    fetch_initial()
    threading.Thread(target=sse_listener, daemon=True).start()
    curses.wrapper(main)
