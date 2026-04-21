"""
analyzer.py — Analiza wallets usando GMGN como fuente principal
GMGN tiene datos pre-calculados: win rate exacto, PnL en USD, historial completo
Si GMGN falla, cae a análisis on-chain como respaldo
"""

import asyncio
import aiohttp
import logging
import time
from typing import Optional

log = logging.getLogger(__name__)

# RPCs públicas de Solana (respaldo)
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

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    "Referer": "https://gmgn.ai/",
    "Origin": "https://gmgn.ai",
}


class WalletAnalyzer:
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
        self.rpc_idx = 0

    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(headers=HEADERS)
        return self.session

    def _rpc(self) -> str:
        url = SOLANA_RPC_URLS[self.rpc_idx % len(SOLANA_RPC_URLS)]
        self.rpc_idx += 1
        return url

    async def _rpc_call(self, method: str, params: list) -> Optional[any]:
        s = await self._get_session()
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
    #  GMGN — FUENTE PRINCIPAL
    # ─────────────────────────────────────────────────────────────────────────

    async def _obtener_datos_gmgn(self, wallet: str) -> Optional[dict]:
        s = await self._get_session()
        endpoints = [
            f"https://gmgn.ai/api/v1/wallet_stat/sol/{wallet}?period=30d",
            f"https://gmgn.ai/defi/quotation/v1/wallet_stat/sol/{wallet}?period=30d",
            f"https://gmgn.ai/api/v1/smartmoney/sol/walletNew/{wallet}?period=30d",
        ]
        for url in endpoints:
            try:
                async with s.get(url, timeout=aiohttp.ClientTimeout(total=15)) as r:
                    if r.status == 200:
                        data = await r.json()
                        log.info(f"GMGN OK para {wallet[:12]}")
                        return self._parsear_gmgn(data, wallet)
            except Exception as e:
                log.warning(f"GMGN falló: {e}")
        return None

    def _parsear_gmgn(self, data: dict, wallet: str) -> Optional[dict]:
        try:
            info = data.get("data") or data.get("wallet") or data.get("result") or data
            if not info:
                return None

            win_rate = float(info.get("winrate") or info.get("win_rate") or info.get("winRate") or 0)
            if win_rate <= 1:
                win_rate = win_rate * 100

            total_trades = int(info.get("total_trade_count") or info.get("totalTradeCount") or info.get("trade_count") or 0)
            ganados      = int(info.get("win_count") or info.get("winCount") or info.get("profit_count") or 0)
            perdidos     = total_trades - ganados

            pnl_usd    = float(info.get("realized_profit") or info.get("realizedProfit") or info.get("total_profit_usd") or 0)
            avg_profit = float(info.get("avg_profit_usd") or info.get("avgProfitUsd") or 0)
            avg_loss   = float(info.get("avg_loss_usd") or info.get("avgLossUsd") or 0)

            profit_factor = abs(avg_profit / avg_loss) if avg_loss and avg_loss != 0 else avg_profit

            first_trade   = info.get("first_active_timestamp") or info.get("firstActiveTimestamp") or 0
            dias_activo   = min(int((time.time() - first_trade) / 86400), 365) if first_trade else 30
            trades_por_dia = total_trades / max(dias_activo, 1)
            tokens_unicos  = int(info.get("token_num") or info.get("tokenNum") or 0)

            if total_trades < 5 or win_rate == 0:
                return None

            return {
                "fuente": "GMGN", "wallet": wallet,
                "win_rate": round(win_rate, 1), "total_trades": total_trades,
                "ganados": ganados, "perdidos": perdidos,
                "pnl_usd": round(pnl_usd, 2), "avg_profit_usd": round(avg_profit, 2),
                "avg_loss_usd": round(avg_loss, 2), "profit_factor": round(profit_factor, 2),
                "dias_activo": dias_activo, "trades_por_dia": round(trades_por_dia, 1),
                "tokens_unicos": tokens_unicos,
            }
        except Exception as e:
            log.error(f"Error parseando GMGN: {e}")
            return None

    # ─────────────────────────────────────────────────────────────────────────
    #  ANÁLISIS PRINCIPAL
    # ─────────────────────────────────────────────────────────────────────────

    async def analizar(self, wallet: str) -> dict:
        log.info(f"Analizando wallet: {wallet[:12]}...")

        # Intento 1: GMGN (5-10 segundos)
        datos_gmgn = await self._obtener_datos_gmgn(wallet)
        if datos_gmgn:
            log.info(f"Usando datos GMGN para {wallet[:12]}")
            return self._calcular_score_gmgn(wallet, datos_gmgn)

        # Intento 2: On-chain (respaldo)
        log.info(f"Usando análisis on-chain para {wallet[:12]}")
        return await self._analizar_onchain(wallet)

    async def _analizar_onchain(self, wallet: str) -> dict:
        todas_sigs = []
        ultimo = None
        for _ in range(4):
            params = {"limit": 250}
            if ultimo:
                params["before"] = ultimo
            lote = await self._rpc_call("getSignaturesForAddress", [wallet, params]) or []
            if not lote:
                break
            todas_sigs.extend(lote)
            ultimo = lote[-1].get("signature")
            hace_90 = int(time.time()) - (90 * 24 * 3600)
            if (lote[-1].get("blockTime") or 0) < hace_90:
                break
            await asyncio.sleep(0.3)

        if not todas_sigs:
            return self._resultado_vacio(wallet, "Sin historial de transacciones")

        hace_90 = int(time.time()) - (90 * 24 * 3600)
        sigs_recientes = [s for s in todas_sigs if (s.get("blockTime") or 0) >= hace_90]

        if len(sigs_recientes) < 5:
            return self._resultado_vacio(wallet, "Muy poca actividad reciente")

        trades = await self._procesar_transacciones(sigs_recientes[:100])
        if not trades:
            return self._resultado_vacio(wallet, "No se detectaron trades en DEX conocidos")

        return self._calcular_metricas(wallet, trades, len(sigs_recientes))

    async def _procesar_transacciones(self, sigs: list) -> list:
        trades = []
        for i in range(0, len(sigs), 10):
            lote    = sigs[i:i+10]
            tareas  = [self._analizar_tx(s["signature"], s.get("blockTime", 0)) for s in lote]
            results = await asyncio.gather(*tareas, return_exceptions=True)
            for r in results:
                if isinstance(r, dict) and r:
                    trades.append(r)
            await asyncio.sleep(0.2)
        return trades

    async def _analizar_tx(self, signature: str, block_time: int) -> Optional[dict]:
        try:
            tx_data = await self._rpc_call("getTransaction", [signature, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}])
            if not tx_data:
                return None
            meta    = tx_data.get("meta", {})
            message = tx_data.get("transaction", {}).get("message", {})
            if meta.get("err"):
                return None
            account_keys = message.get("accountKeys", [])
            es_dex = any(
                (key_info.get("pubkey", "") if isinstance(key_info, dict) else str(key_info)) in DEX_PROGRAMAS
                for key_info in account_keys
            )
            if not es_dex:
                return None
            pre_sol   = sum(meta.get("preBalances",  [0])[:5]) / 1e9
            post_sol  = sum(meta.get("postBalances", [0])[:5]) / 1e9
            fee_sol   = meta.get("fee", 0) / 1e9
            delta_sol = (post_sol - pre_sol) + fee_sol
            pre_map   = {b["mint"]: float(b["uiTokenAmount"]["uiAmount"] or 0) for b in meta.get("preTokenBalances", [])}
            post_map  = {b["mint"]: float(b["uiTokenAmount"]["uiAmount"] or 0) for b in meta.get("postTokenBalances", [])}
            token_principal = next((m for m in (set(pre_map) | set(post_map)) if m not in (SOL_MINT, USDC_MINT)), None)
            return {"signature": signature, "timestamp": block_time, "delta_sol": round(delta_sol, 6), "es_ganancia": delta_sol > 0, "token_mint": token_principal}
        except Exception as e:
            log.debug(f"Error TX {signature[:12]}: {e}")
            return None

    def _calcular_score_gmgn(self, wallet: str, d: dict) -> dict:
        score = 0.0
        if d["win_rate"] >= 65:      score += 3.0
        elif d["win_rate"] >= 55:    score += 2.0
        elif d["win_rate"] >= 45:    score += 1.0
        if d["profit_factor"] >= 2:  score += 2.0
        elif d["profit_factor"] >= 1.5: score += 1.5
        elif d["profit_factor"] >= 1:   score += 1.0
        if d["total_trades"] >= 40:  score += 2.0
        elif d["total_trades"] >= 20: score += 1.5
        elif d["total_trades"] >= 10: score += 1.0
        if d["trades_por_dia"] <= 10:  score += 2.0
        elif d["trades_por_dia"] <= 20: score += 1.0
        if d["pnl_usd"] > 0:         score += 1.0
        score = min(round(score, 1), 10.0)
        if score >= 7.5:
            rec, emoji = "✅ MUY RECOMENDADA — excelente historial", "🟢"
        elif score >= 5.5:
            rec, emoji = "🟡 ACEPTABLE — úsala con precaución", "🟡"
        else:
            rec, emoji = "🔴 NO RECOMENDADA — historial débil", "🔴"
        return {
            "wallet": wallet, "fuente": "GMGN ✨", "score": score,
            "emoji_score": emoji, "recomendacion": rec,
            "win_rate": d["win_rate"], "total_trades": d["total_trades"],
            "ganados": d["ganados"], "perdidos": d["perdidos"],
            "avg_ganancia_sol": d["avg_profit_usd"], "avg_perdida_sol": d["avg_loss_usd"],
            "profit_factor": d["profit_factor"], "pnl_total_sol": d["pnl_usd"],
            "trades_por_dia": d["trades_por_dia"], "tokens_unicos": d["tokens_unicos"],
            "dias_analizados": d["dias_activo"], "es_bot": d["trades_por_dia"] > 50,
            "error": None, "pnl_en_usd": True,
        }

    def _calcular_metricas(self, wallet: str, trades: list, total_sigs: int) -> dict:
        total      = len(trades)
        ganados    = [t for t in trades if t["es_ganancia"]]
        perdidos_l = [t for t in trades if not t["es_ganancia"]]
        win_rate   = (len(ganados) / total * 100) if total else 0
        ganancias  = [t["delta_sol"] for t in ganados]
        perdidas   = [abs(t["delta_sol"]) for t in perdidos_l]
        avg_g      = sum(ganancias) / len(ganancias) if ganancias else 0
        avg_p      = sum(perdidas)  / len(perdidas)  if perdidas  else 0
        pf         = (avg_g / avg_p) if avg_p > 0 else avg_g
        pnl        = sum(t["delta_sol"] for t in trades)
        timestamps = sorted([t["timestamp"] for t in trades if t["timestamp"]])
        es_bot     = False
        if len(timestamps) > 10:
            intervalos    = [timestamps[i+1] - timestamps[i] for i in range(len(timestamps)-1)]
            es_bot        = (sum(intervalos) / len(intervalos)) < 10
        rango_dias     = (timestamps[-1] - timestamps[0]) / 86400 if timestamps else 0
        trades_por_dia = total / max(rango_dias, 1)
        score = 0.0
        if win_rate >= 65:      score += 3.0
        elif win_rate >= 55:    score += 2.0
        elif win_rate >= 45:    score += 1.0
        if pf >= 2:             score += 2.0
        elif pf >= 1.5:         score += 1.5
        elif pf >= 1:           score += 1.0
        if total >= 40:         score += 2.0
        elif total >= 20:       score += 1.5
        elif total >= 10:       score += 1.0
        if not es_bot:
            score += 2.0 if trades_por_dia <= 10 else 1.0
        if pnl > 0:             score += 1.0
        score = min(round(score, 1), 10.0)
        if es_bot:              rec, emoji = "⛔ NO RECOMENDADA — posible bot", "🔴"
        elif score >= 7.5:      rec, emoji = "✅ MUY RECOMENDADA — excelente historial", "🟢"
        elif score >= 5.5:      rec, emoji = "🟡 ACEPTABLE — úsala con precaución", "🟡"
        else:                   rec, emoji = "🔴 NO RECOMENDADA — historial débil", "🔴"
        return {
            "wallet": wallet, "fuente": "On-chain", "score": score,
            "emoji_score": emoji, "recomendacion": rec,
            "win_rate": round(win_rate, 1), "total_trades": total,
            "ganados": len(ganados), "perdidos": len(perdidos_l),
            "avg_ganancia_sol": round(avg_g, 4), "avg_perdida_sol": round(avg_p, 4),
            "profit_factor": round(pf, 2), "pnl_total_sol": round(pnl, 4),
            "trades_por_dia": round(trades_por_dia, 1),
            "tokens_unicos": len(set(t["token_mint"] for t in trades if t["token_mint"])),
            "dias_analizados": round(rango_dias), "es_bot": es_bot,
            "error": None, "pnl_en_usd": False,
        }

    def _resultado_vacio(self, wallet: str, motivo: str) -> dict:
        return {
            "wallet": wallet, "fuente": "N/A", "score": 0.0, "emoji_score": "⚫",
            "recomendacion": f"❌ {motivo}", "win_rate": 0, "total_trades": 0,
            "ganados": 0, "perdidos": 0, "avg_ganancia_sol": 0, "avg_perdida_sol": 0,
            "profit_factor": 0, "pnl_total_sol": 0, "trades_por_dia": 0,
            "tokens_unicos": 0, "dias_analizados": 0, "es_bot": False,
            "error": motivo, "pnl_en_usd": False,
        }

    async def cerrar(self):
        if self.session and not self.session.closed:
            await self.session.close()
