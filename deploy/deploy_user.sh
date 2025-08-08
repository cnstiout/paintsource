#!/usr/bin/env bash
set -euo pipefail

# Defaults
SERVER=""
REMOTE_PATH="~/paintsource_v1"
COLS=160
ROWS=48
SCALE=6
PORT=9000

usage(){ cat <<EOF
Usage: $0 --server user@host [--path ~/paintsource_v1] [--cols 160] [--rows 48] [--scale 6] [--port 9000]
Deploy without root (no systemd/nginx). Starts app on a user port.
EOF
exit 1; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --server) SERVER="$2"; shift 2;;
    --path)   REMOTE_PATH="$2"; shift 2;;
    --cols)   COLS="$2"; shift 2;;
    --rows)   ROWS="$2"; shift 2;;
    --scale)  SCALE="$2"; shift 2;;
    --port)   PORT="$2"; shift 2;;
    *) usage;;
  esac
done

[[ -z "$SERVER" ]] && usage

echo "[*] Rsync to $SERVER:$REMOTE_PATH"
rsync -avz --delete --exclude '__pycache__' --exclude '.venv' ./ "$SERVER":"$REMOTE_PATH"/

echo "[*] Setup venv, install, and run app.py on port $PORT"
ssh "$SERVER" bash -lc "
  cd '$REMOTE_PATH' && \
  python3 -m venv .venv && source .venv/bin/activate && \
  pip install -U pip -r requirements.txt && \
  nohup .venv/bin/python app.py --host 127.0.0.1 --port $PORT --cols $COLS --rows $ROWS --scale $SCALE > paintsource.log 2>&1 &
  echo 'PID:' \$! > paintsource.pid
  sleep 1
  tail -n 50 paintsource.log || true
"
echo "[✓] Started on server 127.0.0.1:$PORT"
echo "Tip: create a tunnel: ssh -N -L 8765:127.0.0.1:$PORT $SERVER  # then open http://127.0.0.1:8765/"
