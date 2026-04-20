#!/bin/bash

echo ""
echo "============================================="
echo "  🐋 WHALE BOT — Instalador Mac/Linux"
echo "============================================="
echo ""

# Verificar Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python3 no encontrado."
    echo ""
    echo "Instálalo con:"
    echo "  Mac:   brew install python3"
    echo "  Linux: sudo apt install python3 python3-pip"
    echo ""
    exit 1
fi

echo "✅ Python encontrado: $(python3 --version)"
echo ""
echo "📦 Instalando dependencias..."
echo ""

pip3 install -r requirements.txt

if [ $? -ne 0 ]; then
    echo ""
    echo "❌ Error instalando dependencias"
    echo "Intenta con: sudo pip3 install -r requirements.txt"
    exit 1
fi

echo ""
echo "✅ Dependencias instaladas"
echo ""

# Crear .env si no existe
if [ ! -f .env ]; then
    cp .env.example .env
    echo "⚙️  Archivo .env creado"
    echo ""
    echo "⚠️  IMPORTANTE: Edita el archivo .env con tus datos:"
    echo "   nano .env"
    echo ""
    echo "Rellena estas 3 variables:"
    echo "   TELEGRAM_TOKEN=..."
    echo "   AUTHORIZED_USER_ID=..."
    echo "   SOLANA_PRIVATE_KEY=..."
    echo ""
else
    echo "✅ Archivo .env ya existe"
fi

# Dar permisos de ejecución al script de inicio
chmod +x iniciar.sh

echo ""
echo "============================================="
echo "  ✅ Instalación completada"
echo "============================================="
echo ""
echo "Para iniciar el bot ejecuta:  ./iniciar.sh"
echo ""
