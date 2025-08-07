#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PaintSource.py — Canvas collaboratif sur IPFS-like via Flask+SSE
Client console curses + SSE — zéro polling, refresh instantané
"""

import curses
import threading
import requests
import json
import time
from datetime import datetime

# —————————————————————————————————————————————
# CONFIGURATION
# —————————————————————————————————————————————
API_BASE       = "http://localhost:5000"         # Ton serveur Flask SSE
STREAM_ENDPOINT= f"{API_BASE}/canvas/stream"     # SSE stream
POST_ENDPOINT  = f"{API_BASE}/canvas"            # POST mises à jour
CANVAS_W, CANVAS_H = 80, 24                      # Dimensions du canevas

# —————————————————————————————————————————————
# ÉTAT PARTAGÉ
# —————————————————————————————————————————————
canvas = [[" "] * CANVAS_W for _ in range(CANVAS_H)]
lock   = threading.Lock()

# —————————————————————————————————————————————
# THREAD D’ÉCOUTE SSE
# —————————————————————————————————————————————
def sse_listener():
    """Écoute les événements SSE et met à jour le canevas."""
    try:
        resp = requests.get(STREAM_ENDPOINT, stream=True, timeout=5.0)
        for raw in resp.iter_lines():
            if not raw or not raw.startswith(b"data:"):
                continue
            payload = json.loads(raw.lstrip(b"data: "))
            with lock:
                # Message complet
                if "full" in payload:
                    grid = payload["full"]
                    for y in range(min(len(grid), CANVAS_H)):
                        for x in range(min(len(grid[y]), CANVAS_W)):
                            canvas[y][x] = grid[y][x]
                # Reset global
                elif payload.get("reset"):
                    for y in range(CANVAS_H):
                        for x in range(CANVAS_W):
                            canvas[y][x] = " "
                # Petit update
                elif all(k in payload for k in ("x","y","ch")):
                    x, y, ch = payload["x"], payload["y"], payload["ch"]
                    if 0 <= x < CANVAS_W and 0 <= y < CANVAS_H:
                        canvas[y][x] = ch
    except Exception as e:
        # En cas de déconnexion, on réessaie après un court délai
        time.sleep(2)
        sse_listener()

# —————————————————————————————————————————————
# ENVOI D’UNE MISE À JOUR
# —————————————————————————————————————————————
def send_update(x, y, ch):
    """POST JSON {"x","y","ch"} au serveur."""
    try:
        requests.post(POST_ENDPOINT, json={"x":x,"y":y,"ch":ch}, timeout=1.0)
    except:
        pass

# —————————————————————————————————————————————
# AFFICHAGE CURSES
# —————————————————————————————————————————————
def main_curses(stdscr):
    curses.curs_set(1)
    stdscr.nodelay(True)
    x = y = 0

    def render(ch): 
        return ch if ch != " " else "·"

    while True:
        stdscr.clear()
        max_y, max_x = stdscr.getmaxyx()
        w = min(CANVAS_W, max_x-2)
        h = min(CANVAS_H, max_y-4)

        # Bords
        try: stdscr.addstr(0, 0, "+" + "-"*w + "+")
        except: pass

        # Canvas
        with lock:
            for ry in range(h):
                row = "".join(render(canvas[ry][cx]) for cx in range(w))
                try: stdscr.addstr(1+ry, 0, f"|{row}|")
                except: pass

        # Instructions
        instr = "←↑↓→: bouger · Entrée: reset curseur · ESC: quitter"
        try: stdscr.addstr(1+h, 0, "+" + "-"*w + "+")
        except: pass
        try: stdscr.addstr(2+h, 0, instr[:max_x])
        except: pass

        # Place le curseur, clampé
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
        elif key >= 32 and key <= 126:
            ch = chr(key)
            with lock:
                canvas[y][x] = ch
            send_update(x, y, ch)
        else:
            time.sleep(0.01)

# —————————————————————————————————————————————
# POINT D’ENTRÉE
# —————————————————————————————————————————————
if __name__ == "__main__":
    # Lance l’écoute SSE en arrière-plan
    threading.Thread(target=sse_listener, daemon=True).start()
    # Lance l’interface console
    curses.wrapper(main_curses)
