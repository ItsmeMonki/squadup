# ---------- SQUADUP: контейнер для облака (Railway / Render / Fly / VPS) ----------
FROM python:3.13-slim

# Приложению нужны только стандартная библиотека Python и SQLite — зависимостей нет.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000 \
    DB_PATH=/data/squadup.db

# Необязательно: вход через Discord. Пусто = кнопка Discord скрыта, вход по нику работает.
# Задай DISCORD_CLIENT_ID и DISCORD_CLIENT_SECRET (а при желании DISCORD_REDIRECT_URI)
# в переменных окружения платформы — см. DEPLOY.md, раздел «Вход через Discord».
ENV DISCORD_CLIENT_ID="" \
    DISCORD_CLIENT_SECRET=""

WORKDIR /app

COPY server.py ./
COPY webpush.py ./
COPY requirements.txt ./
COPY static ./static

# push-уведомления требуют cryptography; остальное — стандартная библиотека.
RUN pip install --no-cache-dir -r requirements.txt

# Том для базы: если платформа примонтирует сюда диск, данные переживут перезапуск.
# (Контейнер запускается от root, потому что облачные тома монтируются root-овыми.)
RUN mkdir -p /data

EXPOSE 8000

# healthcheck средствами Python — curl в slim-образе нет
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python3 -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4).status==200 else 1)"

CMD ["python3", "server.py"]
