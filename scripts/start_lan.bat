@echo off
setlocal EnableExtensions
cd /d "%~dp0.."

if not exist ".venv\Scripts\python.exe" (
  echo ERRORE: ambiente Python mancante. Eseguire prima scripts\setup_windows.bat
  goto :startup_error
)

".venv\Scripts\python.exe" -c "import django, jazzmin, waitress" >nul 2>&1
if errorlevel 1 (
  echo ERRORE: dipendenze mancanti o ambiente Python non valido.
  echo Eseguire scripts\setup_windows.bat, poi riprovare.
  goto :startup_error
)

set "DJANGO_DEBUG=False"
if not defined DJANGO_ALLOWED_HOSTS set "DJANGO_ALLOWED_HOSTS=*"

if not defined DJANGO_SECRET_KEY (
  if not exist "dati" mkdir "dati"
  if not exist "dati\django_secret_key.txt" (
    echo Generazione della chiave privata locale...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "$bytes = New-Object byte[] 48; [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes); $secret = -join ($bytes | ForEach-Object { $_.ToString('x2') }); [IO.File]::WriteAllText((Join-Path (Get-Location) 'dati\django_secret_key.txt'), $secret)"
    if errorlevel 1 (
      echo ERRORE: impossibile creare la chiave privata in dati\django_secret_key.txt.
      goto :startup_error
    )
  )
  set /p "DJANGO_SECRET_KEY="<"dati\django_secret_key.txt"
)

if not defined DJANGO_SECRET_KEY (
  echo ERRORE: chiave privata locale vuota o non leggibile.
  goto :startup_error
)

echo Controllo configurazione e aggiornamento dati...
".venv\Scripts\python.exe" manage.py check
if errorlevel 1 goto :django_error
".venv\Scripts\python.exe" manage.py migrate --noinput
if errorlevel 1 goto :django_error
".venv\Scripts\python.exe" manage.py cleanup_invalid_sessions --verbosity 0
if errorlevel 1 goto :django_error
".venv\Scripts\python.exe" manage.py collectstatic --noinput --verbosity 0
if errorlevel 1 goto :django_error

set "PORT_WAS_SET=1"
if not defined SERVER_PORT (
  set "PORT_WAS_SET=0"
  set "SERVER_PORT=8000"
)

call :check_port
if errorlevel 1 (
  if "%PORT_WAS_SET%"=="1" (
    echo ERRORE: la porta %SERVER_PORT% non e disponibile o e riservata da Windows.
    echo Scegliere un'altra porta, ad esempio: set SERVER_PORT=8765
    goto :startup_error
  )
  echo La porta 8000 non e disponibile. Provo automaticamente la porta 8765...
  set "SERVER_PORT=8765"
  call :check_port
  if errorlevel 1 (
    echo ERRORE: anche la porta 8765 non e disponibile.
    echo Impostare una porta libera, ad esempio: set SERVER_PORT=9000
    goto :startup_error
  )
)

echo.
echo Server LAN pronto sulla porta %SERVER_PORT%.
echo Gestione LAN: http://127.0.0.1:%SERVER_PORT%/admin/rete/
echo Dagli altri PC: http://NOME-O-IP-DEL-PC:%SERVER_PORT%
echo Ogni nuovo PC resta bloccato finche il superadmin non approva il suo indirizzo IP.
echo Un superadmin puo accedere alla gestione LAN anche da un PC remoto.
echo Non esporre questa applicazione direttamente su Internet.

if /I "%~1"=="--check" (
  echo Verifica avvio LAN completata correttamente.
  exit /b 0
)

echo CTRL+C chiede una sola conferma per interrompere il server.
echo Rispondendo S si chiudera anche questa finestra; rispondendo N il server restera attivo.
start "" /b ".venv\Scripts\python.exe" -m config.lan_server
exit /b 0

:check_port
powershell -NoProfile -ExecutionPolicy Bypass -Command "$listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Any, [int]$env:SERVER_PORT); try { $listener.Start(); $listener.Stop(); exit 0 } catch { exit 1 }"
exit /b %errorlevel%

:django_error
echo ERRORE: Django non ha completato la preparazione del server LAN.

:startup_error
echo.
echo Avvio LAN non riuscito. La finestra resta aperta per leggere l'errore.
if /I not "%~1"=="--check" pause
exit /b 1
