#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# term_client.py — client curses pour PaintSource (HTTP + SSE, sans websockets)

import curses
import threading
import time
import json
import requests
import argparse

# ───────────── Config CLI ─────────────
parser = argparse.ArgumentParser()
parser.add_argument("--api", default="http://127.0.0.1:5000",
                    help="Base URL du serveur PaintSource (ex: http://192.168.1.29:5000)")
parser.add_argument("--w", type=int, default=80)
parser.add_argument("--h", type=int, default=24)
args = parser.parse_args()

API = args.api.rstrip("/")
CANVAS_W, CANVAS_H = args.w, args.h
URL_GET   = f"{API}/canvas"
URL_POST  = f"{API}/canvas"
URL_SSE   = f"{API}/canvas/stream"
URL_RESET = f"{API}/canvas/reset"

# ───────────── État partagé ─────────────
canvas = [[" "] * CANVAS_W for _ in range(CANVAS_H)]
lock = threading.Lock()

# ───────────── Réseau ─────────────
def fetch_initial():
    try:
        r = requests.get(URL_GET, timeout=5)
        r.raise_for_status()
        grid = r.json()
        with lock:
            H = min(len(grid), CANVAS_H)
            W = min(len(grid[0]) if grid else 0, CANVAS_W)
            for y in range(H):
                for x in range(W):
                    canvas[y][x] = grid[y][x]
    except Exception:
        pass

def sse_listener():
    """Écoute le flux SSE et met à jour le canvas en temps réel."""
    while True:
        try:
            with requests.get(URL_SSE, stream=True, timeout=30) as r:
                r.raise_for_status()
                for raw in r.iter_lines():
                    if not raw:
                        continue
                    if not raw.startswith(b"data:"):
                        continue
                    try:
                        payload = json.loads(raw[5:].strip())
                    except Exception:
                        continue
                    with lock:
                        if "full" in payload:
                            grid = payload["full"]
                            H = min(len(grid), CANVAS_H)
                            W = min(len(grid[0]) if grid else 0, CANVAS_W)
                            for y in range(H):
                                for x in range(W):
                                    canvas[y][x] = grid[y][x]
                        elif payload.get("reset"):
                            for y in range(CANVAS_H):
                                for x in range(CANVAS_W):
                                    canvas[y][x] = " "
                        else:
                            x = payload.get("x"); y = payload.get("y"); ch = payload.get("ch")
                            if (isinstance(x,int) and isinstance(y,int) and
                                0 <= x < CANVAS_W and 0 <= y < CANVAS_H and
                                isinstance(ch,str) and len(ch)==1):
                                canvas[y][x] = ch
        except Exception:
            time.sleep(1)  # backoff léger et on retente

def send_update(x, y, ch):
    try:
        requests.post(URL_POST, json={"x": x, "y": y, "ch": ch}, timeout=2)
    except Exception:
        pass

# ───────────── UI (curses) ─────────────
def main(stdscr):
    curses.curs_set(1)
    stdscr.nodelay(True)
    x = y = 0

    def render_cell(c):
        return c if c != " " else "·"

    while True:
        stdscr.clear()
        max_y, max_x = stdscr.getmaxyx()
        # on garde de la place pour bordures + 2 lignes d'infos
        w = max(1, min(CANVAS_W, max_x - 2))
        h = max(1, min(CANVAS_H, max_y - 3))

        # cadre haut
        try: stdscr.addstr(0, 0, "+" + "-"*w + "+")
        except curses.error: pass

        # contenu
        with lock:
            for ry in range(h):
                row = "".join(render_cell(canvas[ry][cx]) for cx in range(w))
                try: stdscr.addstr(1+ry, 0, "|" + row + "|")
                except curses.error: pass

        # cadre bas + infos
        try: stdscr.addstr(1+h, 0, "+" + "-"*w + "+")
        except curses.error: pass
        info = f"API: {API}  ←↑↓→: bouger  taper: dessiner  Entrée: (0,0)  ESC: quitter"
        try: stdscr.addstr(2+h, 0, info[:max_x])
        except curses.error: pass

        # clamp du curseur
        y = max(0, min(y, h-1))
        x = max(0, min(x, w-1))
        stdscr.move(1+y, 1+x)
        stdscr.refresh()

        key = stdscr.getch()
        if   key == curses.KEY_UP:    y -= 1
        elif key == curses.KEY_DOWN:  y += 1
        elif key == curses.KEY_LEFT:  x -= 1
        elif key == curses.KEY_RIGHT: x += 1
        elif key in (10,13):          x, y = 0, 0
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
