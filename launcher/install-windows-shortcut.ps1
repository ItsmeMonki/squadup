# ============================================================
#  SQUADUP — создаёт ярлыки с иконкой на рабочем столе и в меню «Пуск»
#  Запуск: правый клик → «Выполнить с помощью PowerShell»
#  либо:  powershell -ExecutionPolicy Bypass -File install-windows-shortcut.ps1
# ============================================================
$ErrorActionPreference = 'Stop'

$launcherDir = $PSScriptRoot
$root        = Split-Path -Parent $launcherDir
$startBat    = Join-Path $launcherDir 'start.bat'
$icon        = Join-Path $root 'static\icons\squadup.ico'

if (-not (Test-Path $startBat)) { throw "Не найден start.bat рядом со скриптом." }
if (-not (Test-Path $icon))     { $icon = Join-Path $root 'static\icons\icon-512.png' }

$shell = New-Object -ComObject WScript.Shell
$targets = @(
  [Environment]::GetFolderPath('Desktop'),
  (Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs')
)

foreach ($dir in $targets) {
  $lnkPath = Join-Path $dir 'SQUADUP.lnk'
  $lnk = $shell.CreateShortcut($lnkPath)
  $lnk.TargetPath       = $startBat
  $lnk.WorkingDirectory = $launcherDir
  $lnk.IconLocation     = $icon
  $lnk.Description      = 'SQUADUP — поиск тиммейтов в кооперативных и соревновательных играх'
  $lnk.WindowStyle      = 7   # свёрнуто, чтобы консоль не мешала
  $lnk.Save()
  Write-Host "Ярлык создан: $lnkPath"
}

Write-Host ''
Write-Host 'Готово! Теперь SQUADUP можно запускать с рабочего стола или из меню «Пуск».'
Write-Host 'Совет: в открывшемся приложении открой меню браузера → «Установить SQUADUP»,'
Write-Host 'тогда оно появится в списке программ как обычное приложение.'
