@echo off
setlocal
cd /d "%~dp0.."
if not exist "db.sqlite3" (echo ERRORE: database db.sqlite3 non trovato. & exit /b 1)
if not exist "backups" mkdir "backups"
for /f %%T in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "STAMP=%%T"
set "DEST=backups\db_%STAMP%.sqlite3"
if exist "%DEST%" (echo ERRORE: il backup %DEST% esiste gia. Nessun file sovrascritto. & exit /b 1)
copy /b "db.sqlite3" "%DEST%" >nul || (echo ERRORE durante la copia. & exit /b 1)
echo Backup creato: %DEST%
endlocal
