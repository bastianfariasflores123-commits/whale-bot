@echo off
echo.
echo =============================================
echo   🐋 WHALE BOT — Instalador Windows
echo =============================================
echo.

:: Verificar Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ❌ Python no encontrado.
    echo.
    echo Por favor instala Python desde:
    echo https://python.org/downloads
    echo.
    echo ⚠️  Durante la instalacion marca la opcion:
    echo     "Add Python to PATH"
    echo.
    pause
    exit /b 1
)

echo ✅ Python encontrado
echo.
echo 📦 Instalando dependencias...
echo.

pip install -r requirements.txt

if errorlevel 1 (
    echo.
    echo ❌ Error instalando dependencias
    echo Intenta ejecutar como Administrador
    pause
    exit /b 1
)

echo.
echo ✅ Dependencias instaladas correctamente
echo.

:: Verificar si existe .env
if not exist .env (
    echo ⚙️  Creando archivo de configuracion...
    copy .env.example .env >nul
    echo.
    echo ⚠️  IMPORTANTE: Debes editar el archivo .env
    echo    Abrelo con el Bloc de Notas y rellena:
    echo    - TELEGRAM_TOKEN
    echo    - AUTHORIZED_USER_ID
    echo    - SOLANA_PRIVATE_KEY
    echo.
    echo Presiona cualquier tecla para abrir el archivo .env...
    pause >nul
    notepad .env
) else (
    echo ✅ Archivo .env ya existe
)

echo.
echo =============================================
echo   ✅ Instalacion completada
echo =============================================
echo.
echo Para iniciar el bot ejecuta:  iniciar.bat
echo.
pause
