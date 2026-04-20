@echo off
echo.
echo =============================================
echo   🐋 WHALE BOT — Iniciando...
echo =============================================
echo.

:: Verificar que existe .env
if not exist .env (
    echo ❌ No se encontro el archivo .env
    echo    Ejecuta primero: instalar_windows.bat
    pause
    exit /b 1
)

:: Verificar que .env tiene valores reales
findstr /c:"TELEGRAM_TOKEN=tu_token" .env >nul 2>&1
if not errorlevel 1 (
    echo ❌ Debes configurar el archivo .env primero
    echo    Abrelo con el Bloc de Notas y rellena tus datos
    pause
    notepad .env
    exit /b 1
)

echo ✅ Configuracion encontrada
echo.
echo 🚀 Iniciando bot... (Ctrl+C para detener)
echo.

:: Cargar variables de entorno desde .env
for /f "tokens=1,2 delims==" %%a in (.env) do (
    if not "%%a"=="" if not "%%b"=="" (
        set "%%a=%%b"
    )
)

python bot.py

echo.
echo Bot detenido.
pause
