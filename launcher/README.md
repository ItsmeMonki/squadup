# launcher — «установка» SQUADUP на своём компьютере

Пока приложение живёт локально, его можно запускать как обычную программу: иконка на рабочем столе, отдельное окно без адресной строки.

## Windows

1. Установлен Python 3? Проверка: открой «Командную строку» и набери `python --version`.
   Если нет — поставь с [python.org/downloads](https://www.python.org/downloads/) с галочкой **Add python.exe to PATH**.
2. Двойной клик по **`start.bat`** — откроется окно приложения (сервер поднимется сам).
3. Чтобы появилась иконка на рабочем столе и в «Пуск»: правый клик по **`install-windows-shortcut.ps1`**, затем «Выполнить с помощью PowerShell».
4. Порт можно поменять: `start.bat 8100`.

## macOS

```bash
chmod +x start.sh stop.sh
./start.sh
```

Откроется окно Chrome в режиме приложения (или браузер по умолчанию). Ярлык можно добавить через Automator либо просто установить PWA из адресной строки («Установить SQUADUP»).

## Linux

```bash
chmod +x start.sh stop.sh
./start.sh
# иконка в меню приложений:
cp squadup.desktop ~/.local/share/applications/
# при необходимости поправь пути внутри файла (Exec=... и Icon=...)
```

## Полезно знать

| Действие | Команда |
|---|---|
| Остановить сервер | `./stop.sh` (Windows: закрой окно «SQUADUP server») |
| Другой порт | `./start.sh 8100` / `start.bat 8100` |
| Лог сервера | `/tmp/squadup.log` (Linux/macOS) |
| Телефон в той же Wi-Fi | открой `http://IP-КОМПЬЮТЕРА:8000` — но установить PWA с http-адреса нельзя, нужен HTTPS (см. DEPLOY.md) |
