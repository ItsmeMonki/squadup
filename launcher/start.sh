#!/usr/bin/env bash
# ============================================================
#  SQUADUP — запуск приложения на macOS и Linux
#  Запуск:  ./start.sh          (порт по умолчанию 8000)
#           ./start.sh 8100     (другой порт)
#           SQUADUP_NO_OPEN=1 ./start.sh   (только сервер, без браузера)
# ============================================================
set -u
PORT="${1:-${PORT:-8000}}"
DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$DIR"

URL="http://localhost:$PORT"
LOG="${TMPDIR:-/tmp}/squadup.log"

# --- Python ---
if command -v python3 >/dev/null 2>&1; then PY=python3
elif command -v python >/dev/null 2>&1; then PY=python
else
  echo "[!] Python 3 не найден. Установи его: https://python.org/downloads"
  exit 1
fi

# --- сервер уже работает? ---
alive() { curl -s -m 2 "http://127.0.0.1:$PORT/healthz" >/dev/null 2>&1; }

if ! alive; then
  echo "Запускаю сервер SQUADUP на порту $PORT (лог: $LOG)…"
  nohup "$PY" server.py >"$LOG" 2>&1 &
  for _ in $(seq 1 40); do
    sleep 0.25
    alive && break
  done
  if ! alive; then
    echo "[!] Сервер не поднялся. Последние строки лога:"
    tail -n 15 "$LOG" 2>/dev/null
    exit 1
  fi
fi
echo "SQUADUP готов: $URL"

[ "${SQUADUP_NO_OPEN:-0}" = "1" ] && exit 0

# --- открываем в режиме приложения, если есть Chromium-браузер ---
for b in google-chrome chromium chromium-browser microsoft-edge brave-browser vivaldi; do
  if command -v "$b" >/dev/null 2>&1; then
    "$b" --app="$URL" --window-size=1280,860 >/dev/null 2>&1 &
    exit 0
  fi
done

# --- macOS: Chrome/Safari ---
if [ "$(uname)" = "Darwin" ]; then
  if [ -d "/Applications/Google Chrome.app" ]; then
    open -na "Google Chrome" --args --app="$URL" --window-size=1280,860
    exit 0
  fi
  open "$URL"
  exit 0
fi

# --- Linux: браузер по умолчанию ---
if command -v xdg-open >/dev/null 2>&1; then
  xdg-open "$URL" >/dev/null 2>&1 &
fi
exit 0
