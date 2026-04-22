"""
🐋 WHALE COPY TRADING BOT - SOLANA
Bot de Telegram para copiar automáticamente movimientos de ballenas en Solana
"""

import os
import asyncio
import logging
import json
from datetime import datetime

# Cargar variables de entorno desde .env automáticamente
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)
from monitor import WalletMonitor
from trader import SolanaTrader
from database import Database
from analyzer import WalletAnalyzer

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO
)
log = logging.getLogger(__name__)

# ── Config desde variables de entorno ────────────────────────────────────────
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN", "")
MY_WALLET_KEY    = os.getenv("SOLANA_PRIVATE_KEY", "")   # clave privada de tu wallet
AUTHORIZED_USER  = int(os.getenv("AUTHORIZED_USER_ID", "0"))  # tu Telegram user ID

# ── Estado global del bot ─────────────────────────────────────────────────────
db       = Database()
monitor  = WalletMonitor()
trader   = SolanaTrader(MY_WALLET_KEY)
analyzer = WalletAnalyzer()

# ─────────────────────────────────────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def solo_autorizado(func):
    """Decorador: solo el dueño del bot puede usarlo."""
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id != AUTHORIZED_USER:
            await update.message.reply_text("⛔ No autorizado.")
            return
        return await func(update, ctx)
    return wrapper


def menu_principal():
    teclado = [
        [InlineKeyboardButton("🐋 Mis ballenas",    callback_data="lista_ballenas")],
        [InlineKeyboardButton("➕ Anadir ballena",  callback_data="anadir_ballena")],
        [
            InlineKeyboardButton("📅 Hoy",       callback_data="hoy"),
            InlineKeyboardButton("📆 Semana",    callback_data="semana"),
            InlineKeyboardButton("🗓️ Mes",       callback_data="mes"),
        ],
        [InlineKeyboardButton("📊 Estadísticas",    callback_data="estadisticas")],
        [InlineKeyboardButton("⚙️ Configuración",   callback_data="config")],
        [InlineKeyboardButton("▶️ Iniciar bot",     callback_data="iniciar"),
         InlineKeyboardButton("⏹️ Detener bot",     callback_data="detener")],
    ]
    return InlineKeyboardMarkup(teclado)


# ─────────────────────────────────────────────────────────────────────────────
#  COMANDOS
# ─────────────────────────────────────────────────────────────────────────────

@solo_autorizado
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    texto = (
        "🐋 *Whale Copy Trading Bot*\n\n"
        "Copia automáticamente los trades de ballenas en Solana.\n\n"
        "Selecciona una opción:"
    )
    await update.message.reply_text(texto, parse_mode="Markdown",
                                    reply_markup=menu_principal())


@solo_autorizado
async def cmd_anadir(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text(
            "Uso: `/anadir <wallet_address>`\n\n"
            "Ejemplo:\n`/anadir 7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU`",
            parse_mode="Markdown"
        )
        return

    wallet = ctx.args[0].strip()

    # Validación básica de dirección Solana (32-44 chars base58)
    if not (32 <= len(wallet) <= 44):
        await update.message.reply_text("❌ Dirección inválida. Verifica que sea una wallet de Solana.")
        return

    if db.wallet_existe(wallet):
        await update.message.reply_text("⚠️ Ya estás siguiendo esa wallet.")
        return

    db.agregar_wallet(wallet)
    await update.message.reply_text(
        f"✅ *Wallet añadida:*\n`{wallet}`\n\n"
        f"El bot ahora monitoreará sus movimientos.",
        parse_mode="Markdown"
    )
    log.info(f"Wallet añadida: {wallet}")


@solo_autorizado
async def cmd_lista(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    wallets = db.obtener_wallets()
    if not wallets:
        await update.message.reply_text("No tienes ninguna ballena registrada.\nUsa /anadir <wallet>")
        return

    texto = "🐋 *Ballenas que sigues:*\n\n"
    for i, w in enumerate(wallets, 1):
        estado = "🟢 Activa" if w["activa"] else "🔴 Pausada"
        texto += f"{i}. `{w['address'][:8]}...{w['address'][-4:]}`  {estado}\n"

    await update.message.reply_text(texto, parse_mode="Markdown")


@solo_autorizado
async def cmd_config(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cfg = db.obtener_config()
    texto = (
        "⚙️ *Configuración actual:*\n\n"
        f"💰 Cantidad por trade: `${cfg['monto_usd']} USD`\n"
        f"🛑 Stop Loss: `{cfg['stop_loss_pct']}%`\n"
        f"🎯 Take Profit: `{cfg['take_profit_pct']}%`\n"
        f"⏱️ Max tiempo en trade: `{cfg['max_minutos']} min`\n\n"
        "Para cambiar un valor usa:\n"
        "`/set monto 15`\n"
        "`/set stop_loss 10`\n"
        "`/set take_profit 25`\n"
        "`/set max_minutos 60`"
    )
    await update.message.reply_text(texto, parse_mode="Markdown")


@solo_autorizado
async def cmd_set(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if len(ctx.args) < 2:
        await update.message.reply_text("Uso: `/set <parametro> <valor>`", parse_mode="Markdown")
        return

    param = ctx.args[0].lower()
    try:
        valor = float(ctx.args[1])
    except ValueError:
        await update.message.reply_text("❌ El valor debe ser un número.")
        return

    campos_validos = {"monto": "monto_usd", "stop_loss": "stop_loss_pct",
                      "take_profit": "take_profit_pct", "max_minutos": "max_minutos"}

    if param not in campos_validos:
        await update.message.reply_text(f"❌ Parámetro inválido. Válidos: {', '.join(campos_validos)}")
        return

    db.actualizar_config(campos_validos[param], valor)
    await update.message.reply_text(f"✅ `{param}` actualizado a `{valor}`", parse_mode="Markdown")


@solo_autorizado
async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    stats = db.obtener_estadisticas()
    emoji_pnl = "📈" if stats["pnl_total"] >= 0 else "📉"
    texto = (
        f"📊 *Estadísticas del bot:*\n\n"
        f"🔢 Trades totales: `{stats['total_trades']}`\n"
        f"✅ Ganados: `{stats['ganados']}`\n"
        f"❌ Perdidos: `{stats['perdidos']}`\n"
        f"🏆 Win rate: `{stats['win_rate']:.1f}%`\n"
        f"{emoji_pnl} P&L total: `${stats['pnl_total']:.2f}`\n"
        f"💵 Mejor trade: `+${stats['mejor_trade']:.2f}`\n"
        f"💸 Peor trade: `-${stats['peor_trade']:.2f}`"
    )
    await update.message.reply_text(texto, parse_mode="Markdown")


@solo_autorizado
async def cmd_analizar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text(
            "Uso: `/analizar <wallet_address>`\n\n"
            "Ejemplo:\n`/analizar 7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU`\n\n"
            "⏳ El análisis tarda ~30 segundos.",
            parse_mode="Markdown"
        )
        return

    wallet = ctx.args[0].strip()
    if not (32 <= len(wallet) <= 44):
        await update.message.reply_text("❌ Dirección inválida.")
        return

    msg = await update.message.reply_text(
        f"🔍 Analizando wallet...\n`{wallet[:12]}...{wallet[-6:]}`\n\n"
        "⏳ Revisando últimos 90 días de historial...",
        parse_mode="Markdown"
    )

    try:
        r = await analyzer.analizar(wallet)
        texto = _formatear_analisis(r)
        await msg.edit_text(texto, parse_mode="Markdown")

        # Si el score es bueno, ofrecer anadirla
        if r["score"] >= 6.0 and not r["es_bot"]:
            teclado = InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    f"➕ Anadir esta wallet al bot",
                    callback_data=f"anadir_confirmado:{wallet}"
                )
            ]])
            await update.message.reply_text(
                "¿Quieres anadir esta wallet para copiarla automáticamente?",
                reply_markup=teclado
            )

    except Exception as e:
        await msg.edit_text(f"❌ Error analizando la wallet: {str(e)[:100]}")


@solo_autorizado
async def cmd_comparar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Analiza y compara múltiples wallets a la vez."""
    if len(ctx.args) < 2:
        await update.message.reply_text(
            "Uso: `/comparar <wallet1> <wallet2> <wallet3>`\n\n"
            "Analiza varias wallets y las ordena por score.\n"
            "Máximo 5 wallets a la vez.",
            parse_mode="Markdown"
        )
        return

    wallets = ctx.args[:5]  # máximo 5
    msg = await update.message.reply_text(
        f"🔍 Comparando {len(wallets)} wallets...\n⏳ Esto puede tardar 1-2 minutos.",
        parse_mode="Markdown"
    )

    resultados = []
    for i, wallet in enumerate(wallets):
        await msg.edit_text(
            f"🔍 Analizando wallet {i+1}/{len(wallets)}...\n"
            f"`{wallet[:12]}...{wallet[-6:]}`",
            parse_mode="Markdown"
        )
        r = await analyzer.analizar(wallet)
        resultados.append(r)

    # Ordenar por score descendente
    resultados.sort(key=lambda x: x["score"], reverse=True)

    texto = "📊 *Comparación de wallets — ranking:*\n\n"
    for i, r in enumerate(resultados, 1):
        medalla = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"][i-1]
        texto += (
            f"{medalla} `{r['wallet'][:8]}...{r['wallet'][-4:]}`\n"
            f"   {r['emoji_score']} Score: *{r['score']}/10* | "
            f"Win rate: *{r['win_rate']}%* | "
            f"Trades: *{r['total_trades']}*\n"
            f"   {r['recomendacion']}\n\n"
        )

    texto += "Usa `/analizar <wallet>` para ver el detalle completo de cualquiera."
    await msg.edit_text(texto, parse_mode="Markdown")


def _formatear_analisis(r: dict) -> str:
    """Formatea el resultado del análisis para Telegram."""
    if r["error"]:
        return (
            f"❌ *No se pudo analizar la wallet*\n\n"
            f"`{r['wallet'][:12]}...{r['wallet'][-6:]}`\n\n"
            f"Motivo: {r['error']}"
        )

    # Barra de score visual
    llenas  = int(r["score"])
    vacias  = 10 - llenas
    barra   = "█" * llenas + "░" * vacias

    # PnL en SOL con emoji
    pnl_emoji = "📈" if r["pnl_total_sol"] >= 0 else "📉"
    pnl_signo = "+" if r["pnl_total_sol"] >= 0 else ""

    # Velocidad de trading
    if r["es_bot"]:
        velocidad = "⚠️ Sospechoso (posible bot)"
    elif r["trades_por_dia"] > 10:
        velocidad = f"⚡ Alta ({r['trades_por_dia']}/día)"
    elif r["trades_por_dia"] > 3:
        velocidad = f"🔄 Moderada ({r['trades_por_dia']}/día)"
    else:
        velocidad = f"🐢 Baja ({r['trades_por_dia']}/día)"

    return (
        f"🔍 *Análisis de Wallet*\n"
        f"`{r['wallet'][:12]}...{r['wallet'][-6:]}`\n\n"

        f"{'─'*30}\n"
        f"*SCORE: {r['score']}/10* {r['emoji_score']}\n"
        f"`{barra}`\n"
        f"{r['recomendacion']}\n"
        f"{'─'*30}\n\n"

        f"📊 *Rendimiento ({r['dias_analizados']} días):*\n"
        f"🏆 Win rate: `{r['win_rate']}%`\n"
        f"✅ Ganados: `{r['ganados']}` trades\n"
        f"❌ Perdidos: `{r['perdidos']}` trades\n"
        f"📋 Total: `{r['total_trades']}` trades\n\n"

        f"💰 *Rentabilidad:*\n"
        f"📈 Ganancia prom: `+{r['avg_ganancia_sol']} SOL` por trade\n"
        f"📉 Pérdida prom: `-{r['avg_perdida_sol']} SOL` por trade\n"
        f"⚖️ Profit factor: `{r['profit_factor']}x`\n"
        f"{pnl_emoji} PnL total: `{pnl_signo}{r['pnl_total_sol']} SOL`\n\n"

        f"🔬 *Perfil de trading:*\n"
        f"⚡ Velocidad: {velocidad}\n"
        f"🪙 Tokens distintos: `{r['tokens_unicos']}`\n"
    )


@solo_autorizado
async def cmd_hoy(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Muestra las métricas del día de hoy."""
    stats = db.obtener_estadisticas_periodo(1)

    if stats["total_trades"] == 0:
        await update.message.reply_text(
            "📅 *Hoy*\n\nAún no hay trades cerrados hoy.\n"
            "El bot está monitoreando tus wallets. 👀",
            parse_mode="Markdown"
        )
        return

    pnl     = stats["pnl_total"]
    emoji   = "📈" if pnl >= 0 else "📉"
    signo   = "+" if pnl >= 0 else ""

    # Barra visual de win rate
    wr      = int(stats["win_rate"] / 10)
    barra   = "█" * wr + "░" * (10 - wr)

    texto = (
        f"📅 *Resumen de hoy*\n\n"
        f"{emoji} *Ganancia del día: `{signo}${pnl}`*\n\n"
        f"{'─'*28}\n"
        f"🔢 Trades: `{stats['total_trades']}`\n"
        f"✅ Ganados: `{stats['ganados']}`\n"
        f"❌ Perdidos: `{stats['perdidos']}`\n"
        f"🏆 Win rate: `{stats['win_rate']}%`\n"
        f"`{barra}`\n\n"
        f"💰 Mejor trade: `+${stats['mejor_trade']}`\n"
        f"💸 Peor trade: `${stats['peor_trade']}`\n"
        f"📊 Promedio por trade: `{signo}${stats['promedio_trade']}`\n"
    )
    await update.message.reply_text(texto, parse_mode="Markdown")


@solo_autorizado
async def cmd_semana(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Muestra las métricas detalladas de la semana."""
    stats = db.obtener_resumen_semanal()

    if stats["total_trades"] == 0:
        await update.message.reply_text(
            "📆 *Esta semana*\n\nAún no hay trades esta semana.\n"
            "Añade wallets y dale ▶️ Iniciar para comenzar.",
            parse_mode="Markdown"
        )
        return

    pnl        = stats["pnl_total"]
    pnl_ant    = stats["pnl_semana_anterior"]
    variacion  = stats["variacion_pct"]
    emoji_pnl  = "📈" if pnl >= 0 else "📉"
    signo      = "+" if pnl >= 0 else ""

    # Flecha de comparación con semana anterior
    if variacion > 0:
        flecha = f"⬆️ +{variacion}% vs semana anterior"
    elif variacion < 0:
        flecha = f"⬇️ {variacion}% vs semana anterior"
    else:
        flecha = "➡️ Igual que semana anterior"

    # Mejor y peor día
    mejor_dia_fecha = stats["mejor_dia"][0] or "N/A"
    mejor_dia_pnl   = stats["mejor_dia"][1]
    peor_dia_fecha  = stats["peor_dia"][0] or "N/A"
    peor_dia_pnl    = stats["peor_dia"][1]

    # Mini gráfico de días
    grafico = _grafico_dias(stats["ganancias_por_dia"])

    # Win rate barra
    wr    = int(stats["win_rate"] / 10)
    barra = "█" * wr + "░" * (10 - wr)

    texto = (
        f"📆 *Resumen semanal*\n\n"
        f"{emoji_pnl} *Ganancia semana: `{signo}${pnl}`*\n"
        f"{flecha}\n\n"
        f"{'─'*28}\n"
        f"📊 *Rendimiento:*\n"
        f"🔢 Trades: `{stats['total_trades']}`\n"
        f"✅ Ganados: `{stats['ganados']}`\n"
        f"❌ Perdidos: `{stats['perdidos']}`\n"
        f"🏆 Win rate: `{stats['win_rate']}%`\n"
        f"`{barra}`\n\n"
        f"{'─'*28}\n"
        f"📅 *Por día:*\n"
        f"{grafico}\n\n"
        f"🌟 Mejor día: `{mejor_dia_fecha}` → `+${mejor_dia_pnl:.2f}`\n"
        f"💀 Peor día: `{peor_dia_fecha}` → `${peor_dia_pnl:.2f}`\n"
        f"📈 Promedio diario: `{'+' if stats['promedio_diario'] >= 0 else ''}${stats['promedio_diario']}`\n\n"
        f"{'─'*28}\n"
        f"💰 Mejor trade: `+${stats['mejor_trade']}`\n"
        f"💸 Peor trade: `${stats['peor_trade']}`\n"
        f"📊 Promedio/trade: `{'+' if stats['promedio_trade'] >= 0 else ''}${stats['promedio_trade']}`\n"
    )
    await update.message.reply_text(texto, parse_mode="Markdown")


@solo_autorizado
async def cmd_mes(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Muestra las métricas del mes con proyección."""
    stats = db.obtener_resumen_mensual()

    if stats["total_trades"] == 0:
        await update.message.reply_text(
            "🗓️ *Este mes*\n\nAún no hay trades este mes.\n"
            "Añade wallets y dale ▶️ Iniciar para comenzar.",
            parse_mode="Markdown"
        )
        return

    pnl       = stats["pnl_total"]
    proyeccion = stats["proyeccion_mes"]
    emoji_pnl = "📈" if pnl >= 0 else "📉"
    signo     = "+" if pnl >= 0 else ""

    # Progreso hacia meta de $100
    meta          = 100.0
    progreso_pct  = min((pnl / meta) * 100, 100) if meta > 0 else 0
    barras_llenas = int(progreso_pct / 10)
    barra_meta    = "█" * barras_llenas + "░" * (10 - barras_llenas)

    # Días para llegar a meta
    if stats["dias_para_meta"] > 0 and pnl < meta:
        dias_meta_txt = f"⏳ Días para $100: `{stats['dias_para_meta']} días`"
    elif pnl >= meta:
        dias_meta_txt = "🎯 ¡Meta de $100 alcanzada!"
    else:
        dias_meta_txt = "📊 Sigue acumulando datos..."

    # Win rate barra
    wr    = int(stats["win_rate"] / 10)
    barra_wr = "█" * wr + "░" * (10 - wr)

    texto = (
        f"🗓️ *Resumen mensual*\n"
        f"_{stats['dias_activo']} días activo_\n\n"
        f"{emoji_pnl} *Ganancia del mes: `{signo}${pnl}`*\n\n"
        f"{'─'*28}\n"
        f"🎯 *Progreso hacia meta $100:*\n"
        f"`{barra_meta}` {progreso_pct:.0f}%\n"
        f"{dias_meta_txt}\n\n"
        f"{'─'*28}\n"
        f"📊 *Rendimiento:*\n"
        f"🔢 Trades totales: `{stats['total_trades']}`\n"
        f"✅ Ganados: `{stats['ganados']}`\n"
        f"❌ Perdidos: `{stats['perdidos']}`\n"
        f"🏆 Win rate: `{stats['win_rate']}%`\n"
        f"`{barra_wr}`\n\n"
        f"{'─'*28}\n"
        f"💰 *Dinero:*\n"
        f"📈 Promedio diario: `{'+' if stats['promedio_diario'] >= 0 else ''}${stats['promedio_diario']}`\n"
        f"🔮 Proyección al mes: `+${proyeccion}`\n"
        f"💵 Mejor trade: `+${stats['mejor_trade']}`\n"
        f"💸 Peor trade: `${stats['peor_trade']}`\n"
    )
    await update.message.reply_text(texto, parse_mode="Markdown")


def _grafico_dias(ganancias_por_dia: dict) -> str:
    """Genera un mini gráfico de texto con los últimos 7 días."""
    if not ganancias_por_dia:
        return "Sin datos"

    from datetime import datetime, timedelta
    hoy   = datetime.now().date()
    lineas = []

    for i in range(6, -1, -1):
        fecha     = hoy - timedelta(days=i)
        fecha_str = str(fecha)
        pnl       = ganancias_por_dia.get(fecha_str, None)
        dia_label = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"][fecha.weekday()]

        if pnl is None:
            lineas.append(f"`{dia_label}` ⬜ sin trades")
        elif pnl > 0:
            barras = min(int(pnl / 2), 8)
            lineas.append(f"`{dia_label}` {'🟩' * max(barras, 1)} +${pnl:.2f}")
        else:
            lineas.append(f"`{dia_label}` 🟥 ${pnl:.2f}")

    return "\n".join(lineas)


@solo_autorizado
async def cmd_backup(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Muestra el string de wallets para guardar en Railway."""
    import json
    wallets = db.obtener_wallets()
    if not wallets:
        await update.message.reply_text("No tienes wallets guardadas aún.")
        return

    addresses = [w["address"] for w in wallets]
    backup    = json.dumps(addresses)

    texto = (
        "💾 *Backup de tus wallets*\n\n"
        "Para que sobrevivan los deploys, copia este valor y "
        "agrégalo en Railway como variable de entorno:\n\n"
        f"*Nombre:* `WALLETS_BACKUP`\n"
        f"*Valor:*\n`{backup}`\n\n"
        "Railway → Variables → Nueva variable → pega el nombre y valor → Save"
    )
    await update.message.reply_text(texto, parse_mode="Markdown")


@solo_autorizado
async def cmd_quitar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Uso: `/quitar <wallet_address>`", parse_mode="Markdown")
        return
    wallet = ctx.args[0].strip()
    if db.quitar_wallet(wallet):
        await update.message.reply_text(f"✅ Wallet eliminada:\n`{wallet}`", parse_mode="Markdown")
    else:
        await update.message.reply_text("❌ No encontré esa wallet en tu lista.")


# ─────────────────────────────────────────────────────────────────────────────
#  CALLBACKS DE BOTONES
# ─────────────────────────────────────────────────────────────────────────────

@solo_autorizado
async def callback_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("anadir_confirmado:"):
        wallet = data.split(":", 1)[1]
        if db.wallet_existe(wallet):
            await query.message.reply_text("⚠️ Ya estás siguiendo esa wallet.")
        else:
            db.agregar_wallet(wallet)
            await query.message.reply_text(
                f"✅ Wallet añadida:\n`{wallet}`",
                parse_mode="Markdown"
            )

    elif data == "lista_ballenas":
        wallets = db.obtener_wallets()
        if not wallets:
            await query.message.reply_text("No tienes ballenas. Usa /anadir <wallet>")
        else:
            texto = "🐋 *Ballenas activas:*\n\n"
            for i, w in enumerate(wallets, 1):
                estado = "🟢" if w["activa"] else "🔴"
                texto += f"{i}. {estado} `{w['address'][:12]}...{w['address'][-6:]}`\n"
            await query.message.reply_text(texto, parse_mode="Markdown")

    elif data == "anadir_ballena":
        await query.message.reply_text(
            "Envía el comando:\n`/anadir <dirección_wallet>`", parse_mode="Markdown"
        )

    elif data == "hoy":
        stats = db.obtener_estadisticas_periodo(1)
        if stats["total_trades"] == 0:
            await query.message.reply_text("📅 *Hoy*\n\nAún no hay trades cerrados hoy.", parse_mode="Markdown")
        else:
            pnl   = stats["pnl_total"]
            emoji = "📈" if pnl >= 0 else "📉"
            signo = "+" if pnl >= 0 else ""
            wr    = int(stats["win_rate"] / 10)
            barra = "█" * wr + "░" * (10 - wr)
            texto = (
                f"📅 *Resumen de hoy*\n\n"
                f"{emoji} *Ganancia del día: `{signo}${pnl}`*\n\n"
                f"🔢 Trades: `{stats['total_trades']}`\n"
                f"✅ Ganados: `{stats['ganados']}`\n"
                f"❌ Perdidos: `{stats['perdidos']}`\n"
                f"🏆 Win rate: `{stats['win_rate']}%`\n"
                f"`{barra}`\n\n"
                f"💰 Mejor trade: `+${stats['mejor_trade']}`\n"
                f"💸 Peor trade: `${stats['peor_trade']}`"
            )
            await query.message.reply_text(texto, parse_mode="Markdown")

    elif data == "semana":
        stats = db.obtener_resumen_semanal()
        if stats["total_trades"] == 0:
            await query.message.reply_text("📆 *Esta semana*\n\nAún no hay trades esta semana.", parse_mode="Markdown")
        else:
            pnl      = stats["pnl_total"]
            variacion = stats["variacion_pct"]
            emoji    = "📈" if pnl >= 0 else "📉"
            signo    = "+" if pnl >= 0 else ""
            flecha   = f"⬆️ +{variacion}%" if variacion > 0 else f"⬇️ {variacion}%"
            wr       = int(stats["win_rate"] / 10)
            barra    = "█" * wr + "░" * (10 - wr)
            grafico  = _grafico_dias(stats["ganancias_por_dia"])
            texto = (
                f"📆 *Resumen semanal*\n\n"
                f"{emoji} *Ganancia semana: `{signo}${pnl}`*\n"
                f"{flecha} vs semana anterior\n\n"
                f"🔢 Trades: `{stats['total_trades']}`\n"
                f"✅ Ganados: `{stats['ganados']}`\n"
                f"❌ Perdidos: `{stats['perdidos']}`\n"
                f"🏆 Win rate: `{stats['win_rate']}%`\n"
                f"`{barra}`\n\n"
                f"📅 *Por día:*\n{grafico}\n\n"
                f"📈 Promedio diario: `{'+' if stats['promedio_diario'] >= 0 else ''}${stats['promedio_diario']}`"
            )
            await query.message.reply_text(texto, parse_mode="Markdown")

    elif data == "mes":
        stats = db.obtener_resumen_mensual()
        if stats["total_trades"] == 0:
            await query.message.reply_text("🗓️ *Este mes*\n\nAún no hay trades este mes.", parse_mode="Markdown")
        else:
            pnl        = stats["pnl_total"]
            proyeccion = stats["proyeccion_mes"]
            emoji      = "📈" if pnl >= 0 else "📉"
            signo      = "+" if pnl >= 0 else ""
            meta       = 100.0
            progreso   = min((pnl / meta) * 100, 100) if meta > 0 else 0
            llenas     = int(progreso / 10)
            barra_meta = "█" * llenas + "░" * (10 - llenas)
            dias_txt   = f"⏳ Días para $100: `{stats['dias_para_meta']} días`" if pnl < meta else "🎯 ¡Meta de $100 alcanzada!"
            wr         = int(stats["win_rate"] / 10)
            barra_wr   = "█" * wr + "░" * (10 - wr)
            texto = (
                f"🗓️ *Resumen mensual*\n"
                f"_{stats['dias_activo']} días activo_\n\n"
                f"{emoji} *Ganancia del mes: `{signo}${pnl}`*\n\n"
                f"🎯 *Progreso hacia $100:*\n"
                f"`{barra_meta}` {progreso:.0f}%\n"
                f"{dias_txt}\n\n"
                f"🔢 Trades: `{stats['total_trades']}`\n"
                f"🏆 Win rate: `{stats['win_rate']}%` `{barra_wr}`\n\n"
                f"📈 Promedio diario: `{'+' if stats['promedio_diario'] >= 0 else ''}${stats['promedio_diario']}`\n"
                f"🔮 Proyección al mes: `+${proyeccion}`"
            )
            await query.message.reply_text(texto, parse_mode="Markdown")

    elif data == "estadisticas":
        stats = db.obtener_estadisticas()
        emoji_pnl = "📈" if stats["pnl_total"] >= 0 else "📉"
        texto = (
            f"📊 *Estadísticas totales:*\n\n"
            f"🔢 Trades totales: `{stats['total_trades']}`\n"
            f"✅ Ganados: `{stats['ganados']}`\n"
            f"❌ Perdidos: `{stats['perdidos']}`\n"
            f"🏆 Win rate: `{stats['win_rate']:.1f}%`\n"
            f"{emoji_pnl} P&L total: `${stats['pnl_total']:.2f}`\n"
            f"💵 Mejor trade: `+${stats['mejor_trade']:.2f}`\n"
            f"💸 Peor trade: `${stats['peor_trade']:.2f}`"
        )
        await query.message.reply_text(texto, parse_mode="Markdown")

    elif data == "config":
        cfg = db.obtener_config()
        texto = (
            f"⚙️ *Configuración actual:*\n\n"
            f"💰 Cantidad por trade: `${cfg['monto_usd']} USD`\n"
            f"🛑 Stop Loss: `{cfg['stop_loss_pct']}%`\n"
            f"🎯 Take Profit: `{cfg['take_profit_pct']}%`\n"
            f"⏱️ Max tiempo en trade: `{cfg['max_minutos']} min`\n\n"
            f"Para cambiar usa:\n"
            f"`/set monto 5`\n"
            f"`/set stop_loss 8`\n"
            f"`/set take_profit 25`\n"
            f"`/set max_minutos 45`"
        )
        await query.message.reply_text(texto, parse_mode="Markdown")

    elif data == "iniciar":
        if ctx.bot_data.get("corriendo"):
            await query.message.reply_text("⚠️ El bot ya está corriendo.")
        else:
            ctx.bot_data["corriendo"] = True
            asyncio.create_task(loop_monitoreo(ctx))
            await query.message.reply_text("▶️ Bot iniciado. Monitoreando ballenas...")

    elif data == "detener":
        ctx.bot_data["corriendo"] = False
        await query.message.reply_text("⏹️ Bot detenido.")


# ─────────────────────────────────────────────────────────────────────────────
#  LOOP PRINCIPAL DE MONITOREO
# ─────────────────────────────────────────────────────────────────────────────

async def loop_monitoreo(ctx: ContextTypes.DEFAULT_TYPE):
    """
    Corre cada 15 segundos. Revisa las últimas 10 TXs de cada wallet
    para no perder ningún trade aunque la ballena opere rápido.
    """
    log.info("🔄 Loop de monitoreo iniciado")

    # Notificar estado del trader al arrancar
    if trader.esta_listo():
        await ctx.bot.send_message(
            chat_id    = AUTHORIZED_USER,
            text       = f"✅ *Bot iniciado correctamente*\n\n💼 Wallet: `{trader.pubkey_str[:12]}...`\n🐋 Monitoreando {len(db.obtener_wallets(solo_activas=True))} wallets",
            parse_mode = "Markdown"
        )
    else:
        await ctx.bot.send_message(
            chat_id    = AUTHORIZED_USER,
            text       = "⚠️ *Bot iniciado en modo simulación*\n\nNo se pudo cargar la wallet. Verifica SOLANA_PRIVATE_KEY en Railway.",
            parse_mode = "Markdown"
        )

    while ctx.bot_data.get("corriendo"):
        wallets = db.obtener_wallets(solo_activas=True)
        cfg     = db.obtener_config()

        for w in wallets:
            try:
                # Obtener TXs nuevas — pasamos un set vacío porque el filtro
                # real se hace abajo con db.tx_procesada() para evitar duplicados
                txs_nuevas = await monitor.obtener_transacciones_nuevas(
                    w["address"],
                    ya_procesadas=set()
                )

                for tx in txs_nuevas:
                    if not tx or not isinstance(tx, dict):
                        continue

                    sig = tx.get("signature")
                    if not sig:
                        continue

                    if db.tx_procesada(sig):
                        continue

                    log.info(f"🎯 Nueva TX: {sig[:20]} | {tx.get('accion','?')} | {tx.get('dex','?')}")

                    # Marcar primero para evitar doble ejecución
                    db.marcar_tx(sig)

                    # Ejecutar trade
                    resultado = await trader.copiar_trade(
                        token_mint  = tx["token_mint"],
                        accion      = tx["accion"],
                        monto_usd   = cfg["monto_usd"],
                        stop_loss   = cfg["stop_loss_pct"],
                        take_profit = cfg["take_profit_pct"],
                        max_minutos = cfg["max_minutos"],
                    )

                    # Protección: no procesar si resultado es inválido
                    if not resultado or not isinstance(resultado, dict):
                        log.error(f"Trade retornó resultado inválido para {tx.get('token_mint','?')[:8]}")
                        continue

                    # Solo registrar en BD si hubo intento real (no sin_cotizacion)
                    if resultado.get("estado") != "sin_cotizacion":
                        db.registrar_trade(resultado)

                    await notificar_resultado(ctx, tx, resultado)

            except Exception as e:
                log.error(f"Error procesando wallet {w['address'][:8]}: {e}", exc_info=True)

        await asyncio.sleep(15)

    log.info("⏹️ Loop de monitoreo detenido")


async def notificar_resultado(ctx, tx: dict, resultado: dict):
    """Envía la notificación de resultado al usuario de Telegram."""
    pnl      = resultado.get("pnl_usd", 0)
    emoji    = "✅" if pnl >= 0 else "❌"
    signo    = "+" if pnl >= 0 else "-"
    duracion = resultado.get("duracion_min", 0)

    razones = {
        "take_profit": "🎯 Take Profit",
        "stop_loss":   "🛑 Stop Loss",
        "timeout":     "⏱️ Timeout",
    }
    razon = razones.get(resultado.get("razon_cierre", ""), "⏹️ Manual")

    mensaje = (
        f"{emoji} *Operación cerrada — {razon}*\n\n"
        f"🪙 Token: `{resultado.get('token', 'N/A')}`\n"
        f"📋 Acción: `{tx['accion'].upper()}`\n"
        f"💰 Invertido: `${resultado.get('invertido', 0):.2f}`\n"
        f"💵 Resultado: `{signo}${abs(pnl):.2f}`\n"
        f"⏱️ Duración: `{duracion} min`\n"
        f"🔗 TX: `{resultado.get('tx_hash', 'N/A')[:20]}...`\n\n"
        f"📊 P&L acumulado: `${db.obtener_estadisticas()['pnl_total']:.2f}`"
    )

    await ctx.bot.send_message(
        chat_id    = AUTHORIZED_USER,
        text       = mensaje,
        parse_mode = "Markdown"
    )


# ─────────────────────────────────────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    if not TELEGRAM_TOKEN:
        raise ValueError("Falta TELEGRAM_TOKEN en las variables de entorno")
    if not AUTHORIZED_USER:
        raise ValueError("Falta AUTHORIZED_USER_ID en las variables de entorno")

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    # Comandos
    app.add_handler(CommandHandler("start",    cmd_start))
    app.add_handler(CommandHandler("anadir",   cmd_anadir))
    app.add_handler(CommandHandler("lista",    cmd_lista))
    app.add_handler(CommandHandler("quitar",   cmd_quitar))
    app.add_handler(CommandHandler("config",   cmd_config))
    app.add_handler(CommandHandler("set",      cmd_set))
    app.add_handler(CommandHandler("stats",    cmd_stats))
    app.add_handler(CommandHandler("analizar", cmd_analizar))
    app.add_handler(CommandHandler("comparar", cmd_comparar))
    app.add_handler(CommandHandler("hoy",      cmd_hoy))
    app.add_handler(CommandHandler("semana",   cmd_semana))
    app.add_handler(CommandHandler("mes",      cmd_mes))
    app.add_handler(CommandHandler("backup",   cmd_backup))

    # Botones inline
    app.add_handler(CallbackQueryHandler(callback_handler))

    log.info("🐋 Whale Bot arrancando...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
