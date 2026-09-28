@echo off
rem ============================================================
rem  SQUADUP — запуск приложения на Windows
rem  Двойной клик по этому файлу: поднимает сервер и открывает
rem  приложение в отдельном окне (без адресной строки).
rem ============================================================
setlocal enabledelayedexpansion
set PORT=8000
if not "%1"=="" set PORT=%1

cd /d "%~dp0.."

where python >nul 2>nul
if errorlevel 1 (
  echo.
  echo [!] Python не найден. Установи Python 3 с https://python.org/downloads
  echo     Важно: при установке поставь галочку "Add python.exe to PATH".
  echo.
  pause
  exit /b 1
)

rem --- сервер уже запущен? проверяем порт через PowerShell ---
powershell -NoProfile -Command "try{(New-Object Net.Sockets.TcpClient('127.0.0.1',%PORT%)).Close();exit 0}catch{exit 1}" >nul 2>nul
if errorlevel 1 (
  echo Запускаю сервер SQUADUP на порту %PORT% ...
  start "SQUADUP server" /min python server.py
  rem ждём до 15 секунд, пока сервер ответит
  for /l %%i in (1,1,30) do (
    powershell -NoProfile -Command "try{(New-Object Net.Sockets.TcpClient('127.0.0.1',%PORT%)).Close();exit 0}catch{exit 1}" >nul 2>nul
    if !errorlevel!==0 goto :ready
    timeout /t 1 /nobreak >nul
  )
)
:ready
set URL=http://localhost:%PORT%

rem --- открываем в режиме приложения (Chrome / Edge / Brave) ---
for %%B in (
  "%ProgramFiles%\Google\Chrome\Application\chrome.exe"
  "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
  "%LocalAppData%\Google\Chrome\Application\chrome.exe"
  "%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"
  "%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"
  "%ProgramFiles%\BraveSoftware\Brave-Browser\Application\brave.exe"
) do (
  if exist %%B (
    start "" %%B --app=%URL% --window-size=1280,860
    goto :done
  )
)

rem --- если Chrome/Edge нет — открываем браузер по умолчанию ---
start "" %URL%
:done
endlocal
exit /b 0
