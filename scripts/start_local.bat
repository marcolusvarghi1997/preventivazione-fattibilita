@echo off
setlocal
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (echo ERRORE: eseguire prima scripts\setup_windows.bat & exit /b 1)
set "DJANGO_DEBUG=True"
set "DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost"
set "PORT_WAS_SET=1"
if not defined SERVER_PORT (
  set "PORT_WAS_SET=0"
  set "SERVER_PORT=8000"
)
powershell -NoProfile -ExecutionPolicy Bypass -Command "$listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, [int]$env:SERVER_PORT); try { $listener.Start(); $listener.Stop(); exit 0 } catch { exit 1 }"
if errorlevel 1 (
  if "%PORT_WAS_SET%"=="1" (
    echo ERRORE: la porta %SERVER_PORT% non e disponibile o e riservata da Windows.
    echo Scegliere un'altra porta, ad esempio: set SERVER_PORT=8765
    exit /b 1
  )
  echo La porta 8000 non e disponibile. Provo automaticamente la porta 8765...
  set "SERVER_PORT=8765"
  powershell -NoProfile -ExecutionPolicy Bypass -Command "$listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, [int]$env:SERVER_PORT); try { $listener.Start(); $listener.Stop(); exit 0 } catch { exit 1 }"
  if errorlevel 1 (
    echo ERRORE: anche la porta 8765 non e disponibile.
    echo Impostare una porta libera, ad esempio: set SERVER_PORT=9000
    exit /b 1
  )
)
echo Applicazione disponibile solo su questo PC: http://127.0.0.1:%SERVER_PORT%
echo Premere CTRL+C per arrestare.
".venv\Scripts\waitress-serve.exe" --listen=127.0.0.1:%SERVER_PORT% config.wsgi:application
endlocal
