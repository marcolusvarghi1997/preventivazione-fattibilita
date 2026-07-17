@echo off
setlocal
cd /d "%~dp0.."
echo === Preparazione Preventivi Carpenteria ===
where py >nul 2>nul || (echo ERRORE: Python non trovato. Installare Python 3.13 a 64 bit. & exit /b 1)
if not exist ".venv\Scripts\python.exe" (
  echo Creo l'ambiente Python locale...
  py -3.13 -m venv .venv || exit /b 1
)
call ".venv\Scripts\activate.bat" || exit /b 1
python -m pip install --upgrade pip || exit /b 1
python -m pip install -r requirements.txt || exit /b 1
python manage.py migrate || exit /b 1
python manage.py seed_initial_data || exit /b 1
python manage.py collectstatic --noinput || exit /b 1
echo.
echo Installazione completata.
echo Se e la prima installazione, creare ora l'amministratore con:
echo   .venv\Scripts\python.exe manage.py createsuperuser
echo Poi avviare scripts\start_local.bat
endlocal
