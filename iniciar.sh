#!/bin/bash

echo ""
echo "============================================="
echo "  🐋 WHALE BOT — Iniciando..."
echo "============================================="
echo ""

# Verificar que existe .env
if [ ! -f .env ]; then
    echo "❌ No se encontró el archivo .env"
    echo "   Ejecuta primero: ./instalar_mac_linux.sh"
    exit 1
fi

# Cargar variables de entorno
export $(grep -v '^#' .env | grep -v '^$' | xargs)

# Verificar que están configuradas
if [ -z "$TELEGRAM_TOKEN" ] || [ "$TELEGRAM_TOKEN" = "123456789:ABCdefGHIjklMNOpqrSTUvwxYZ" ]; then
    echo "❌ Debes configurar el archivo .env primero"
    echo "   Ejecuta: nano .env"
    exit 1
fi

echo "✅ Configuración cargada"
echo ""
echo "🚀 Iniciando bot... (Ctrl+C para detener)"
echo ""

python3 bot.py
