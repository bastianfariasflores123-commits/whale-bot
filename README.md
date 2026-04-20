# 🐋 Whale Copy Trading Bot

Bot de Telegram que copia automáticamente los trades de ballenas en Solana.

## Inicio rápido

### Windows
1. Doble clic en `instalar_windows.bat`
2. Rellena el archivo `.env` que se abre automáticamente
3. Doble clic en `iniciar.bat`

### Mac / Linux
```bash
chmod +x instalar_mac_linux.sh iniciar.sh
./instalar_mac_linux.sh
./iniciar.sh
```

## Comandos del bot

| Comando | Descripción |
|---------|-------------|
| `/start` | Menú principal |
| `/analizar <wallet>` | Analiza y puntúa una wallet (score /10) |
| `/comparar <w1> <w2> <w3>` | Compara varias wallets y las rankea |
| `/añadir <wallet>` | Añade una wallet para copiar |
| `/lista` | Ve todas las wallets activas |
| `/quitar <wallet>` | Deja de seguir una wallet |
| `/set monto 10` | Cambia cantidad por trade |
| `/set stop_loss 10` | Cambia stop loss (%) |
| `/set take_profit 25` | Cambia take profit (%) |
| `/set max_minutos 60` | Tiempo máximo por posición |
| `/config` | Ve configuración actual |
| `/stats` | Estadísticas de trading |

## Archivos del proyecto

```
whale-bot/
├── bot.py                  → Bot principal de Telegram
├── analyzer.py             → Analizador y scorer de wallets
├── monitor.py              → Monitoreo on-chain de Solana
├── trader.py               → Ejecución de trades via Jupiter
├── database.py             → Base de datos local SQLite
├── requirements.txt        → Dependencias Python
├── .env.example            → Plantilla de configuración
├── instalar_windows.bat    → Instalador Windows
├── iniciar.bat             → Iniciar bot en Windows
├── instalar_mac_linux.sh   → Instalador Mac/Linux
├── iniciar.sh              → Iniciar bot en Mac/Linux
├── Procfile                → Para Railway/Render (24/7)
└── GUIA.md                 → Guía detallada completa
```

## Variables de entorno (.env)

```
TELEGRAM_TOKEN=token_de_botfather
AUTHORIZED_USER_ID=tu_id_de_telegram
SOLANA_PRIVATE_KEY=clave_privada_de_phantom
```

## ⚠️ Advertencia

Trading de criptomonedas conlleva riesgo de pérdida total del capital.
Empieza con cantidades pequeñas mientras aprendes.
