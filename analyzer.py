"""
analyzer.py — Analiza el historial de una wallet y genera un score de calidad
Usa RPCs públicas de Solana + Birdeye API (plan gratuito)
"""

import asyncio
import aiohttp
import logging
import time
from typing import Optional

log = logging.getLogger(__name__)

SOLANA_RPC_URLS = [
    "https://api.mainnet-beta.solana.com",
    "https://solana-api.projectserum.com",
    "https://rpc.ankr.com/solana",
]

SOL_MINT  = "So11111111111111111111111111111111111111112"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

DEX_PROGRAMAS = {
    "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4": "Jupiter",
    "JUP4Fb2cqiRUcaTHdrPC8h2gNsA2ETXiPDD33WcGuJB":  "Jupiter v4",
    "JUP3c2Uh3WA4Ng34tw6kPd2G4LFvdpUtkzEgBAWUdT":  "Jupiter v3",
    "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8": "Raydium AMM",
    "5quBtoiQqxF9Jv6KYKctB59NT3gtJD2Y65kdnB1Uev3h": "Raydium AMM v2",
    "CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK": "Raydium CLMM",
    "routeUGWgWzqBWFcrCfv8tritsqukccJPu3q5GPP3xS":  "Raydium Router",
    "9W959DqEETiGZocYWCQPaJ6sBmUzgfxXfqGeTEdp3aQP": "Orca",
    "whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc":  "Orca Whirlpool",
    "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P":  "Pump.fun",
    "Eo7WjKq67rjJQSZxS6z3YkapzY3eMj6Xy8X5EkTiEc":  "Meteora",
    "LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo":  "Meteora DLMM",
    "EewxydAPCCVuNEyrVN68PuSYdQ7wKn27V9Gjeoi8dy3S": "Lifinity",
    "PhoeNiXZ8ByJGLkxNfZRnkUfjvmuYqLR89jjFHGqdXY":  "Phoenix",
    "srmqPvymJeFKQ4zGQed1GFppgkRHL9kaELCbyksJejpH":  "Openbook",
}


class WalletAnalyzer:
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
        self.rpc_idx = 0

    async def _session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session

    def _rpc(self) -> str:
        url = SOLANA_RPC_URLS[self.rpc_idx % len(SOLANA_RPC_URLS)]
        self.rpc_idx += 1
        return url

    async def _rpc_call(self, method: str, params: list) -> Optional[any]:
        s = await self._session()
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        for _ in range(len(SOLANA_RPC_URLS)):
            try:
                async with s.post(self._rpc(), json=payload,
                                  timeout=aiohttp.ClientTimeout(total=12)) as r:
                    if r.status == 200:
                        data = await r.json()
                        return data.get("result")
            except Exception as e:
                log.warning(f"RPC falló: {e}")
        return None

    # ─────────────────────────────────────────────────────────────────────────
    #  ANÁLISIS PRINCIPAL
    # ─────────────────────────────────────────────────────────────────────────

    async def analizar(self, wallet: str) -> dict:
        """
        Analiza los últimos 90 días de actividad de la wallet.
        Retorna un dict con todas las métricas y el score final.
        """
        log.info(f"Analizando wallet: {wallet[:12]}...")

        # Obtener hasta 1000 transacciones en lotes de 250
        todas_sigs = []
        ultimo = None

        for _ in range(4):  # máximo 4 lotes = 1000 transacciones
            params = {"limit": 250}
            if ultimo:
                params["before"] = ultimo

            lote = await self._rpc_call(
                "getSignaturesForAddress",
                [wallet, params]
            ) or []

            if not lote:
                break

            todas_sigs.extend(lote)
            ultimo = lote[-1].get("signature")

            # Si el último del lote ya es de hace más de 90 días, paramos
            hace_90_dias = int(time.time()) - (90 * 24 * 3600)
            if (lote[-1].get("blockTime") or 0) < hace_90_dias:
                break

            await asyncio.sleep(0.3)  # pausa entre lotes

        if not todas_sigs:
            return self._resultado_vacio(wallet, "Sin historial de transacciones")

        # Filtrar solo los últimos 90 días
        hace_90_dias = int(time.time()) - (90 * 24 * 3600)
        sigs_recientes = [s for s in todas_sigs if (s.get("blockTime") or 0) >= hace_90_dias]

        if len(sigs_recientes) < 5:
            return self._resultado_vacio(wallet, "Muy poca actividad reciente (menos de 5 trades)")

        # Analizar hasta 100 transacciones para no tardar demasiado
        trades = await self._procesar_transacciones(sigs_recientes[:100])

        if not trades:
            return self._resultado_vacio(wallet, "No se detectaron trades en DEX conocidos")

        # Calcular métricas
        return self._calcular_metricas(wallet, trades, len(sigs_recientes))

    async def _procesar_transacciones(self, sigs: list) -> list:
        """Procesa las transacciones en lotes para no sobrecargar la RPC."""
        trades = []

        # Procesar de a 5 para ser respetuosos con la RPC pública
        for i in range(0, len(sigs), 5):
            lote = sigs[i:i+5]
            tareas = [self._analizar_tx(s["signature"], s.get("blockTime", 0)) for s in lote]
            resultados = await asyncio.gather(*tareas, return_exceptions=True)

            for r in resultados:
                if isinstance(r, dict) and r:
                    trades.append(r)

            await asyncio.sleep(0.5)  # pausa entre lotes

        return trades

    async def _analizar_tx(self, signature: str, block_time: int) -> Optional[dict]:
        """Analiza una transacción individual."""
        try:
            tx_data = await self._rpc_call(
                "getTransaction",
                [signature, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}]
            )
            if not tx_data:
                return None

            meta    = tx_data.get("meta", {})
            message = tx_data.get("transaction", {}).get("message", {})

            # Verificar si hay error
            if meta.get("err"):
                return None

            # Verificar si interactúa con DEX
            account_keys = message.get("accountKeys", [])
            es_dex = False
            for key_info in account_keys:
                pubkey = key_info.get("pubkey", "") if isinstance(key_info, dict) else str(key_info)
                if pubkey in DEX_PROGRAMAS:
                    es_dex = True
                    break

            if not es_dex:
                return None

            # Calcular cambios de balance SOL (aproximación del PnL)
            pre_sol  = sum(meta.get("preBalances",  [0])[:5]) / 1e9
            post_sol = sum(meta.get("postBalances", [0])[:5]) / 1e9
            fee_sol  = meta.get("fee", 0) / 1e9
            delta_sol = (post_sol - pre_sol) + fee_sol  # excluir fee del cálculo

            # Analizar tokens intercambiados
            pre_tok  = meta.get("preTokenBalances",  [])
            post_tok = meta.get("postTokenBalances", [])
            pre_map  = {b["mint"]: float(b["uiTokenAmount"]["uiAmount"] or 0) for b in pre_tok}
            post_map = {b["mint"]: float(b["uiTokenAmount"]["uiAmount"] or 0) for b in post_tok}

            mints_cambiados = set(pre_map.keys()) | set(post_map.keys())
            token_principal = None
            for mint in mints_cambiados:
                if mint not in (SOL_MINT, USDC_MINT):
                    token_principal = mint
                    break

            return {
                "signature":  signature,
                "timestamp":  block_time,
                "delta_sol":  round(delta_sol, 6),
                "es_ganancia": delta_sol > 0,
                "token_mint": token_principal,
            }

        except Exception as e:
            log.debug(f"Error en TX {signature[:12]}: {e}")
            return None

    def _calcular_metricas(self, wallet: str, trades: list, total_sigs: int) -> dict:
        """Calcula todas las métricas y el score final."""

        total      = len(trades)
        ganados    = [t for t in trades if t["es_ganancia"]]
        perdidos   = [t for t in trades if not t["es_ganancia"]]
        win_rate   = (len(ganados) / total * 100) if total else 0

        ganancias  = [t["delta_sol"] for t in ganados]
        perdidas   = [abs(t["delta_sol"]) for t in perdidos]

        avg_ganancia = sum(ganancias) / len(ganancias) if ganancias else 0
        avg_perdida  = sum(perdidas)  / len(perdidas)  if perdidas  else 0
        profit_factor = (avg_ganancia / avg_perdida) if avg_perdida > 0 else avg_ganancia

        pnl_total_sol = sum(t["delta_sol"] for t in trades)

        # Detectar si es bot (muchos trades en poco tiempo)
        timestamps = sorted([t["timestamp"] for t in trades if t["timestamp"]])
        es_bot     = False
        if len(timestamps) > 10:
            intervalos = [timestamps[i+1] - timestamps[i] for i in range(len(timestamps)-1)]
            avg_intervalo = sum(intervalos) / len(intervalos)
            es_bot = avg_intervalo < 10  # menos de 10 segundos entre trades = probable bot

        # Días activa
        if timestamps:
            rango_dias = (timestamps[-1] - timestamps[0]) / 86400
            trades_por_dia = total / max(rango_dias, 1)
        else:
            rango_dias     = 0
            trades_por_dia = 0

        # ── Calcular score 0-10 ───────────────────────────────────────────────
        score = 0.0

        # Win rate (máx 3 puntos)
        if win_rate >= 65:   score += 3.0
        elif win_rate >= 55: score += 2.0
        elif win_rate >= 45: score += 1.0

        # Profit factor (máx 2 puntos)
        if profit_factor >= 2.0:   score += 2.0
        elif profit_factor >= 1.5: score += 1.5
        elif profit_factor >= 1.0: score += 1.0

        # Volumen de trades (máx 2 puntos)
        if total >= 40:   score += 2.0
        elif total >= 20: score += 1.5
        elif total >= 10: score += 1.0

        # Consistencia / no es bot (máx 2 puntos)
        if not es_bot:
            if trades_por_dia <= 10: score += 2.0
            else:                    score += 1.0

        # PnL positivo (máx 1 punto)
        if pnl_total_sol > 0: score += 1.0

        score = min(round(score, 1), 10.0)

        # ── Recomendación ─────────────────────────────────────────────────────
        if es_bot:
            recomendacion = "⛔ NO RECOMENDADA — parece un bot automatizado"
            emoji_score   = "🔴"
        elif score >= 7.5:
            recomendacion = "✅ MUY RECOMENDADA — excelente historial"
            emoji_score   = "🟢"
        elif score >= 5.5:
            recomendacion = "🟡 ACEPTABLE — úsala con precaución"
            emoji_score   = "🟡"
        else:
            recomendacion = "🔴 NO RECOMENDADA — historial débil"
            emoji_score   = "🔴"

        # Tokens únicos operados
        tokens_unicos = len(set(t["token_mint"] for t in trades if t["token_mint"]))

        return {
            "wallet":          wallet,
            "score":           score,
            "emoji_score":     emoji_score,
            "recomendacion":   recomendacion,
            "win_rate":        round(win_rate, 1),
            "total_trades":    total,
            "ganados":         len(ganados),
            "perdidos":        len(perdidos),
            "avg_ganancia_sol": round(avg_ganancia, 4),
            "avg_perdida_sol":  round(avg_perdida, 4),
            "profit_factor":   round(profit_factor, 2),
            "pnl_total_sol":   round(pnl_total_sol, 4),
            "trades_por_dia":  round(trades_por_dia, 1),
            "tokens_unicos":   tokens_unicos,
            "dias_analizados": round(rango_dias),
            "es_bot":          es_bot,
            "error":           None,
        }

    def _resultado_vacio(self, wallet: str, motivo: str) -> dict:
        return {
            "wallet":          wallet,
            "score":           0.0,
            "emoji_score":     "⚫",
            "recomendacion":   f"❌ {motivo}",
            "win_rate":        0,
            "total_trades":    0,
            "ganados":         0,
            "perdidos":        0,
            "avg_ganancia_sol": 0,
            "avg_perdida_sol":  0,
            "profit_factor":   0,
            "pnl_total_sol":   0,
            "trades_por_dia":  0,
            "tokens_unicos":   0,
            "dias_analizados": 0,
            "es_bot":          False,
            "error":           motivo,
        }

    async def cerrar(self):
        if self.session and not self.session.closed:
            await self.session.close()
