# 🐋 WHALE BOT — Guía Completa Lista para el Lunes

═══════════════════════════════════════════════════════
  ANTES DE EMPEZAR — CONSIGUE ESTAS 3 COSAS
═══════════════════════════════════════════════════════

1. TOKEN DE TELEGRAM  → lo obtienes de @BotFather
2. TU ID DE TELEGRAM  → lo obtienes de @userinfobot
3. CLAVE DE PHANTOM   → desde la app Phantom Wallet


═══════════════════════════════════════════════════════
  PASO 1 — CREAR TU BOT DE TELEGRAM (5 minutos)
═══════════════════════════════════════════════════════

1. Abre Telegram
2. Busca @BotFather y escríbele
3. Escribe: /newbot
4. Ponle nombre: "Mi Whale Bot"
5. Ponle username terminado en "bot": mi_whale_bot
6. BotFather te dará un TOKEN:
   123456789:ABCdefGHIjklMNOpqrSTUvwxYZ  ← guárdalo

Para obtener tu ID de Telegram:
1. Busca @userinfobot
2. Escríbele /start
3. Te responde con tu ID numérico ← guárdalo


═══════════════════════════════════════════════════════
  PASO 2 — CREAR TU WALLET DE SOLANA (10 minutos)
═══════════════════════════════════════════════════════

1. Instala Phantom Wallet
   Chrome → busca "Phantom Wallet" en Chrome Web Store
   Celular → busca "Phantom" en App Store o Play Store

2. Crea una wallet nueva
   Guarda las 12 palabras semilla EN PAPEL (nunca digital)

3. Deposita SOL:
   Compra SOL en Binance u otro exchange
   Envíalo a tu dirección de Phantom
   Con $30 USD en SOL tienes suficiente para empezar

4. Exporta tu clave privada:
   Phantom → Configuración ⚙️ → Seguridad y privacidad
   → Exportar clave privada → ingresa contraseña
   → Copia la clave larga que aparece ← guárdala

⚠️  NUNCA compartas tu clave privada con nadie


═══════════════════════════════════════════════════════
  PASO 3 — INSTALAR PYTHON
═══════════════════════════════════════════════════════

Windows:
   Ve a https://python.org/downloads
   Descarga Python 3.11 o superior
   ⚠️ Durante instalación marca: "Add Python to PATH"

Mac:
   Ya viene instalado. Si no funciona:
   Instala Homebrew (https://brew.sh) y luego: brew install python3

Verifica abriendo la consola/terminal:
   python --version    (Windows)
   python3 --version   (Mac)
   Debe mostrar: Python 3.11.x o superior


═══════════════════════════════════════════════════════
  PASO 4 — INSTALAR EL BOT (5 minutos)
═══════════════════════════════════════════════════════

Windows:
   1. Pon todos los archivos en una carpeta llamada whale-bot
   2. Doble clic en: instalar_windows.bat
   3. El instalador hace todo solo
   4. Se abrirá el archivo .env automáticamente

Mac/Linux:
   1. Abre Terminal
   2. cd /ruta/a/whale-bot
   3. chmod +x instalar_mac_linux.sh
   4. ./instalar_mac_linux.sh


═══════════════════════════════════════════════════════
  PASO 5 — CONFIGURAR TUS DATOS (2 minutos)
═══════════════════════════════════════════════════════

Abre el archivo .env con el Bloc de Notas y rellena:

   TELEGRAM_TOKEN=pega_tu_token_aqui
   AUTHORIZED_USER_ID=pega_tu_id_numerico_aqui
   SOLANA_PRIVATE_KEY=pega_tu_clave_privada_aqui

Guarda el archivo.


═══════════════════════════════════════════════════════
  PASO 6 — INICIAR EL BOT
═══════════════════════════════════════════════════════

Windows:   doble clic en iniciar.bat
Mac/Linux: ./iniciar.sh

Verás en consola: 🐋 Whale Bot arrancando...

Ve a Telegram, abre tu bot y escríbele /start
Aparecerá el menú principal con todos los botones.


═══════════════════════════════════════════════════════
  PASO 7 — CONFIGURAR PARÁMETROS DE TRADING
═══════════════════════════════════════════════════════

Escríbele al bot estos comandos uno por uno:

   /set monto 5
   /set stop_loss 8
   /set take_profit 25
   /set max_minutos 45

Verifica con /config — debe mostrar:
   💰 Cantidad por trade: $5 USD
   🛑 Stop Loss: 8%
   🎯 Take Profit: 25%
   ⏱️ Max tiempo: 45 min


═══════════════════════════════════════════════════════
  PASO 8 — ENCONTRAR WALLETS DE BALLENAS
═══════════════════════════════════════════════════════

Dónde buscar (todo gratis):
   → birdeye.so/leaderboard    ← MEJOR OPCIÓN
   → dexscreener.com           ← Top traders de cada token
   → solscan.io                ← Transacciones grandes

Proceso:
   1. Entra a birdeye.so/leaderboard
   2. Copia direcciones del top
   3. Analiza en el bot: /analizar <dirección>
   4. Solo añade si cumple TODO esto:

      ✅ Score 7.5 o más (de 10)
      ✅ Win rate 60% o más
      ✅ Profit factor 2x o más
      ✅ Trades en 90 días: 30 o más
      ✅ ¿Es bot?: NO

   5. Si pasa todo: /añadir <dirección>

Para comparar varias a la vez:
   /comparar <wallet1> <wallet2> <wallet3>

Meta del lunes: tener 3 wallets con score 7.5+


═══════════════════════════════════════════════════════
  PASO 9 — ARRANCAR EL MONITOREO
═══════════════════════════════════════════════════════

Con tus 3 wallets añadidas:
   1. Escribe /start
   2. Pulsa ▶️ Iniciar bot
   3. El bot dice: "▶️ Bot iniciado. Monitoreando ballenas..."
   4. ¡Listo! El bot trabaja solo desde aquí.


═══════════════════════════════════════════════════════
  TODOS LOS COMANDOS DEL BOT
═══════════════════════════════════════════════════════

GESTIÓN DE WALLETS:
   /start              → Menú principal con botones
   /añadir <wallet>    → Empieza a copiar esa wallet
   /lista              → Ve todas las wallets activas
   /quitar <wallet>    → Deja de copiar esa wallet

ANÁLISIS DE WALLETS:
   /analizar <wallet>         → Score y métricas completas
   /comparar <w1> <w2> <w3>  → Compara hasta 5 wallets rankeadas

MÉTRICAS DE GANANCIAS:
   /hoy     → Ganancia del día, trades, win rate
   /semana  → Resumen semanal con gráfico por día
   /mes     → Resumen mensual con proyección y meta $100
   /stats   → Estadísticas totales desde el inicio

CONFIGURACIÓN:
   /config              → Ver configuración actual
   /set monto 5         → Cambiar cantidad por trade
   /set stop_loss 8     → Cambiar stop loss en %
   /set take_profit 25  → Cambiar take profit en %
   /set max_minutos 45  → Cambiar tiempo máximo por trade


═══════════════════════════════════════════════════════
  QUÉ VES CUANDO EL BOT CIERRA UN TRADE
═══════════════════════════════════════════════════════

   ✅ Operación cerrada

   🪙 Token: BONK
   📋 Acción: COMPRA
   💰 Invertido: $5.00
   💵 Resultado: +$1.25
   ⏱️ Duración: 23 min
   🔗 TX: 7xKXtg2C...

   📊 P&L acumulado: +$47.80


═══════════════════════════════════════════════════════
  QUÉ VES EN /semana
═══════════════════════════════════════════════════════

   📆 Resumen semanal

   📈 Ganancia semana: +$22.75
   ⬆️ +18% vs semana anterior

   🔢 Trades: 38  ✅ Ganados: 23  ❌ Perdidos: 15
   🏆 Win rate: 60%  ██████░░░░

   📅 Por día:
   Lun 🟩🟩 +$4.20
   Mar 🟩🟩🟩 +$6.50
   Mié 🟥 -$1.20
   Jue 🟩🟩 +$5.05
   Vie 🟩🟩🟩 +$7.55
   Sáb 🟩 +$2.55
   Dom ⬜ sin trades

   🌟 Mejor día: Viernes → +$7.55
   📈 Promedio diario: +$3.25


═══════════════════════════════════════════════════════
  QUÉ VES EN /mes
═══════════════════════════════════════════════════════

   🗓️ Resumen mensual — 12 días activo

   📈 Ganancia del mes: +$52.30

   🎯 Progreso hacia meta $100:
   █████░░░░░ 52%
   ⏳ Días para $100: 11 días

   📈 Promedio diario: +$4.35
   🔮 Proyección al mes: +$130.50


═══════════════════════════════════════════════════════
  RUTINA SEMANAL — SOLO 15 MINUTOS CADA LUNES
═══════════════════════════════════════════════════════

   1. /semana        → ver cómo fue la semana
   2. /lista         → ver tus wallets
   3. /analizar      → revisar score de cada wallet
   4. Si alguna bajó de 7.5 → /quitar + busca reemplazo
   5. Si todo bien   → no toques nada, el bot sigue solo


═══════════════════════════════════════════════════════
  REGLAS DE ORO — NO LAS ROMPAS
═══════════════════════════════════════════════════════

✅ Solo wallets con score 7.5 o más
✅ Revisar wallets cada 2 semanas
✅ Si 3 pérdidas seguidas en una wallet → pausarla
✅ No subir monto hasta tener el doble de capital mínimo
✅ Reinvertir casi todo los primeros 3 meses
✅ Retirar solo $30 fijos los primeros meses

❌ Nunca añadir wallet con score bajo de 7.5
❌ Nunca subir el monto más de 50% de golpe
❌ Nunca retirar todo cuando va bien
❌ Nunca apagar el bot en la primera semana mala


═══════════════════════════════════════════════════════
  PLAN MES A MES
═══════════════════════════════════════════════════════

Mes 1: 3 wallets | $5/trade  → ganancia ~$135 | retiras $30
Mes 2: 10 wallets | $8/trade → ganancia ~$521 | retiras $80
Mes 3: 12 wallets | $15/trade → ganancia ~$1,500 | retiras $230
Mes 4: 14 wallets | $25/trade → ganancia ~$2,975 | retiras $530
Mes 5: 15 wallets | $40/trade → ganancia ~$5,362 | retiras $1,230
Mes 6: 16 wallets | $60/trade → ganancia ~$8,236 | retiras $2,030
Mes 7: 18 wallets | $80/trade → ganancia ~$11,787 | retiras $3,030


═══════════════════════════════════════════════════════
  CORRER 24/7 SIN TU PC — RAILWAY (GRATIS)
═══════════════════════════════════════════════════════

Para que el bot corra aunque apagues el computador:

1. Crea cuenta en github.com (gratis)
2. Crea repositorio PRIVADO y sube los archivos
   ⚠️ NUNCA subas el .env — el .gitignore ya lo bloquea
3. Crea cuenta en railway.app (gratis)
4. New Project → Deploy from GitHub → selecciona tu repo
5. Ve a Variables y agrega las 3 variables de tu .env
6. Railway mantiene el bot corriendo 24/7 automáticamente


═══════════════════════════════════════════════════════
  SOLUCIÓN DE PROBLEMAS
═══════════════════════════════════════════════════════

"No module named telegram"
→ pip install -r requirements.txt

"Bot no responde"
→ Verifica TELEGRAM_TOKEN y AUTHORIZED_USER_ID en .env

"No se pudo cargar keypair"
→ Modo simulación activo (no ejecuta trades reales)
→ Verifica SOLANA_PRIVATE_KEY en .env

"Error de conexión"
→ La red de Solana está congestionada
→ El bot reintenta automáticamente. Espera 5 minutos.

"Trades muy lentos"
→ Normal. Las ballenas no operan las 24 horas.
→ El bot detecta en máximo 15 segundos cuando hay movimiento.


═══════════════════════════════════════════════════════
  ARCHIVOS DEL PROYECTO
═══════════════════════════════════════════════════════

bot.py                 → Bot principal de Telegram
analyzer.py            → Analizador de wallets con score /10
monitor.py             → Monitoreo on-chain de Solana
trader.py              → Ejecución de trades via Jupiter DEX
database.py            → Base de datos local SQLite
requirements.txt       → Dependencias Python
.env.example           → Plantilla de configuración
instalar_windows.bat   → Instalador automático Windows
iniciar.bat            → Iniciar bot en Windows
instalar_mac_linux.sh  → Instalador automático Mac/Linux
iniciar.sh             → Iniciar bot en Mac/Linux
Procfile               → Para Railway (servidor 24/7)
.gitignore             → Protege tu .env en GitHub
GUIA.md                → Esta guía


═══════════════════════════════════════════════════════
  ⚠️  ADVERTENCIAS FINALES
═══════════════════════════════════════════════════════

RIESGO FINANCIERO
El copy trading no garantiza ganancias.
Puedes perder parte o todo el capital invertido.
Empieza pequeño y aprende antes de escalar.

CLAVE PRIVADA
NUNCA la compartas. NUNCA la subas a internet.
Quien la tenga tiene acceso total a tu wallet.

NO ES GARANTÍA
Las proyecciones son estimaciones basadas en promedios.
La consistencia y la selección de wallets lo es todo.
