#!/usr/bin/env bash
# Остановить сервер SQUADUP (macOS / Linux)
pkill -f "server.py" && echo "Сервер SQUADUP остановлен." || echo "Работающих экземпляров не найдено."
