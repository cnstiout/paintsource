#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Client terminal “style ssh” pour PaintSource.
- Connexion à une URL (HTTP/HTTPS), ex: https://botsu.fr/paintsource
- Découverte auto du sous-chemin (BASE) depuis l’URL donnée
- UI curses (clavier + clic basique si supporté par le terminal)
- Temps réel via SSE (sans lib externe)
- Envoi POST sur /canvas
"""

import argparse, curses, json, threading, time
import requests
from urllib.parse import urlparse, urlunparse

# -------------------- CLI args --------------------
p = argparse.ArgumentParser(description="Client terminal pour PaintSource (style ssh)")
p.add_argument("url", help="Ex: https://botsu.fr/paintsource  ou  http://192.168.1.29:5000")
p.add_argument("--w", type=int, default=80, help="Largeur locale du rendu (par défaut 80)")
p.add_argument("--h", type=int, default=24, help="Hauteur locale du rendu (par défaut 24)")
p.add_argument("--insecure", action="store_true", help="Ignorer la vérification TLS (certificat auto-signé)")
args = p.parse_args()

VERIFY_TLS = not args.insecure

# -------------------- URL & Endpoints --------------------
def normalize_base(url: str):
    # Force schéma si absent
    if not (url.startswith("http://") or url.startswith("https://")):
        url = "https://" + url
    u = urlparse(url)

    # S’il n’y a pas de path, on laisse "" (ex: http://ip:5000)
    base_path = u.path.rstrip("/")
    # Cas fréquent : l’utilisateur pointe la racine du site HTTPS (botsu.fr)
    # On tentera d’abord tel quel, puis /paintsource si la racine n’expose rien.

    def build(path):
        return urlunparse((u.scheme, u.netloc, path, "", "", ""))

    # Construire deux candidats : celui demandé et /paintsource si vide
    primary = build(base_path if base_path else "/")
    fallback = build("/paintsource")
    return primary, fallback

PRIMARY_BASE, FALLBACK_BASE = normalize_base(args.url)

def endpoints(base):
    # S’assurer d’un trailing slash logique côté client pour des joins simples
    base = base.rstrip("/")
    return {
        "base": base,
        "get":  f"{base}/canvas",
        "post": f"{base}/canvas",
        "sse":  f"{base}/stream"
    }

# -------------------- HTTP helpers --------------------
session = requests.Session()
session.headers.update({"User-Agent": "PaintSource-CLI/1.0"})

def try_fetch_grid(eps):
    try:
        r = session.get(eps["get"], timeout=6, verify=VERIFY_TLS)
        if r.ok:
            return r.json()
    except Exception:
        pass
    return None

# Découverte automatique du bon BASE (PRIMARY d’abord, sinon FALLBACK)
EPS = endpoints(PRIMARY_BASE)
grid = try_fetch_grid(EPS)
if grid is None:
    EPS = endpoints(FALLBACK_BASE)
    grid = try_fetch_grid(EPS)
    if grid is None:
        raise SystemExit(
            f"[x] Impossible d’accéder au serveur PaintSource.\n"
            f"    Testé : {PRIMARY_BASE} et {FALLBACK_BASE}\n"
            f"    Vérifie l’URL, le proxy Apache et que l’app tourne."
        )

CANVAS_W = len(grid[0]) if grid and isinstance(grid, list) and grid and isinstance(grid[0], list) else args.w
CANVAS_H = len(grid)    if grid and isinstance(grid, list) else args.h
CANVAS_W = max(1, min(CANVAS_W, 512))
CANVAS_H = max(1, min(CANVAS_H, 256))

canvas = [[" "] * CANVAS_W for _ in range(CANVAS_H)]
lock = threading.Lock()

def http_post_update(x, y, ch):
    try:
        session.post(EPS["post"], json={"x": x, "y": y, "ch": ch}, timeout=3, verify=VERIFY_TLS)
    except Exception:
        pass

# -------------------- SSE listener --------------------
def sse_lines(url, timeout=65):
    """
    Itère les lignes d’un endpoint SSE sans lib externe.
    """
    with session.get(url, stream=True, timeout=timeout, verify=VERIFY_TLS,
                     headers={"Accept": "text/event-stream"}) as r:
        r.raise_for_status()
        buf = b""
        for chunk in r.iter_content(chunk_size=1024):
            if not chunk:
                continue
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                yield line

def sse_loop():
    backoff = 1.0
    while True:
        try:
            for raw in sse_lines(EPS["sse"]):
                if not raw.startswith(b"data:"):
                    continue
                try:
                    msg = json.loads(raw[5:].strip())
                except Exception:
                    continue
                with lock:
                    if "full" in msg and isinstance(msg["full"], list):
                        g = msg["full"]
                        h = min(CANVAS_H, len(g))
                        w = min(CANVAS_W, len(g[0]) if g else 0)
                        for y in range(h):
                            for x in range(w):
                                canvas[y][x] = g[y][x]
                    elif msg.get("reset"):
                        for y in range(CANVAS_H):
                            for x in range(CANVAS_W):
                                canvas[y][x] = " "
                    else:
                        x = msg.get("x"); y = msg.get("y"); ch = msg.get("ch")
                        if (isinstance(x,int) and isinstance(y,int) and
                            0 <= x < CANVAS_W and 0 <= y < CANVAS_H and
                            isinstance(ch,str) and len(ch)==1):
                            canvas[y][x] = ch
            # Si on sort de la boucle sans exception : on retente après un petit backoff
            time.sleep(backoff)
            backoff = min(10.0, backoff * 1.5)
        except Exception:
            time.sleep(backoff)
            backoff = min(10.0, backoff * 1.5)

# -------------------- Curses UI --------------------
def run_curses(stdscr):
    curses.curs_set(1)
    stdscr.nodelay(True)

    # Souris: activée si supportée
    try:
        curses.mousemask(curses.ALL_MOUSE_EVENTS | curses.REPORT_MOUSE_POSITION)
    except Exception:
        pass

    x = y = 0

    def dot(c):  # rendu des “vides”
        return c if c != " " else "."

    info_url = EPS["base"]

    while True:
        stdscr.clear()
        max_y, max_x = stdscr.getmaxyx()
        w = max(1, min(CANVAS_W, max_x - 2))
        h = max(1, min(CANVAS_H, max_y - 3))

        # Cadre
        try: stdscr.addstr(0, 0, "+" + "-"*w + "+")
        except curses.error: pass

        with lock:
            for ry in range(h):
                row = "".join(dot(canvas[ry][cx]) for cx in range(w))
                try: stdscr.addstr(1+ry, 0, "|" + row + "|")
                except curses.error: pass

        try: stdscr.addstr(1+h, 0, "+" + "-"*w + "+")
        except curses.error: pass

        help_line = f"{info_url}  ←↑↓→: bouger  taper: dessiner  clic-gauche: espace  clic-droit: #  Entrée:0,0  ESC:quit"
        try: stdscr.addstr(2+h, 0, help_line[:max_x])
        except curses.error: pass

        # Curseur dans les bornes
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
        elif key == 27:               return
        elif key == curses.KEY_MOUSE:
            # Dessin souris basique (pas de drag continu garanti selon terminal)
            try:
                _, mx, my, _, b = curses.getmouse()
                cx = max(0, min(w-1, mx-1))
                cy = max(0, min(h-1, my-1))
                ch = "#" if (b & (getattr(curses, "BUTTON3_PRESSED", 0))) else " "
                with lock:
                    canvas[cy][cx] = ch
                http_post_update(cx, cy, ch)
            except Exception:
                pass
        elif key == -1:
            time.sleep(0.01)
            continue
        else:
            # n’importe quel caractère imprimable
            try:
                ch = chr(key)
            except ValueError:
                continue
            if len(ch) == 1 and ch.isprintable():
                with lock:
                    canvas[y][x] = ch
                http_post_update(x, y, ch)

# -------------------- Boot --------------------
# Remplir l’état local initial depuis le serveur
with lock:
    H = min(CANVAS_H, len(grid))
    W = min(CANVAS_W, len(grid[0]) if grid else 0)
    for yy in range(H):
        for xx in range(W):
            canvas[yy][xx] = grid[yy][xx]

# Thread SSE
thr = threading.Thread(target=sse_loop, daemon=True)
thr.start()

# UI
curses.wrapper(run_curses)
