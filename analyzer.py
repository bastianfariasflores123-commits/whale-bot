"""
analyzer.py — Analiza wallets de Solana
Fuente principal: Helius API (rápido, 3-5s)
Respaldo: On-chain RPC (limitado a 50 TXs para no tardar)
"""

import asyncio
import aiohttp
import logging
import os
import time
from typing import Optional

log = logging.getLogger(__name__)

HELIUS_API_KEY = os.getenv("HELIUS_API_KEY", "")

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

    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session

    def _rpc(self) -> str:
        url = SOLANA_RPC_URLS[self.rpc_idx % len(SOLANA_RPC_URLS)]
        self.rpc_idx += 1
        return url

    async def _rpc_call(self, method: str, params: list) -> Optional[any]:
        s       = await self._get_session()
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        for _ in range(len(SOLANA_RPC_URLS)):
            try:
                async with s.post(self._rpc(), json=payload,
                                  timeout=aiohttp.ClientTimeout(total=10)) as r:
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
        log.info(f"Analizando wallet: {wallet[:12]}...")

        if HELIUS_API_KEY:
            log.info("Usando Helius ⚡")
            return await self._analizar_helius(wallet)

        log.info("Sin Helius — usando on-chain (respaldo rápido)")
        return await self._analizar_onchain(wallet)

    # ─────────────────────────────────────────────────────────────────────────
    #  HELIUS — fuente principal (3-5 segundos)
    # ─────────────────────────────────────────────────────────────────────────

    async def _analizar_helius(self, wallet: str) -> dict:
        s   = await self._get_session()
        url = f"https://api.helius.xyz/v0/addresses/{wallet}/transactions"
        params = {
            "api-key": HELIUS_API_KEY,
            "limit":   100,
            "type":    "SWAP",
        }
        try:
            async with s.get(url, params=params,
                             timeout=aiohttp.ClientTimeout(total=20)) as r:
                if r.status != 200:
                    log.warning(f"Helius error {r.status} — respaldo on-chain")
                    return await self._analizar_onchain(wallet)

                txs = await r.json()
                if not txs:
                    return self._resultado_vacio(wallet, "Sin historial de swaps")

                return self._procesar_helius(wallet, txs)

        except asyncio.TimeoutError:
            log.warning("Helius timeout — respaldo on-chain")
            return await self._analizar_onchain(wallet)
        except Exception as e:
            log.error(f"Helius falló: {e} — respaldo on-chain")
            return await self._analizar_onchain(wallet)

    def _procesar_helius(self, wallet: str, txs: list) -> dict:
        trades  = []
        hace_90 = time.time() - (90 * 24 * 3600)

        for tx in txs:
            try:
                ts = tx.get("timestamp", 0)
                if ts < hace_90:
                    continue

                eventos = tx.get("events", {})
                swap    = eventos.get("swap")
                if not swap:
                    continue

                native_input  = swap.get("nativeInput",  {}) or {}
                native_output = swap.get("nativeOutput", {}) or {}
                sol_gastado   = (native_input.get("amount",  0) or 0) / 1e9
                sol_recibido  = (native_output.get("amount", 0) or 0) / 1e9
                delta_sol     = sol_recibido - sol_gastado

                token_outputs = swap.get("tokenOutputs", [])
                token_inputs  = swap.get("tokenInputs",  [])
                token_mint    = None
                if token_outputs:
                    token_mint = token_outputs[0].get("mint")
                elif token_inputs:
                    token_mint = token_inputs[0].get("mint")

                trades.append({
                    "timestamp":   ts,
                    "delta_sol":   round(delta_sol, 6),
                    "es_ganancia": delta_sol > 0,
                    "token_mint":  token_mint,
                    "signature":   tx.get("signature", ""),
                })

            except Exception as e:
                log.debug(f"Error TX Helius: {e}")
                continue

        if not trades:
            return self._resultado_vacio(wallet, "No se detectaron swaps en los últimos 90 días")

        resultado           = self._calcular_metricas(wallet, trades, len(txs))
        resultado["fuente"] = "Helius ⚡"
        return resultado

    # ─────────────────────────────────────────────────────────────────────────
    #  ON-CHAIN — respaldo rápido (máx 50 TXs, sin loops infinitos)
    # ─────────────────────────────────────────────────────────────────────────

    async def _analizar_onchain(self, wallet: str) -> dict:
        # Solo 1 lote de 50 — suficiente para el análisis, no tarda minutos
        lote = await self._rpc_call(
            "getSignaturesForAddress",
            [wallet, {"limit": 50}]
        ) or []

        if not lote:
            return self._resultado_vacio(wallet, "Sin historial de transacciones")

        hace_90        = int(time.time()) - (90 * 24 * 3600)
        sigs_recientes = [s for s in lote if (s.get("blockTime") or 0) >= hace_90]

        if len(sigs_recientes) < 5:
            return self._resultado_vacio(wallet, "Muy poca actividad reciente (últimos 90 días)")

        trades = await self._procesar_transacciones(sigs_recientes[:50])

        if not trades:
            return self._resultado_vacio(wallet, "No se detectaron trades en DEX conocidos")

        return self._calcular_metricas(wallet, trades, len(sigs_recientes))

    async def _procesar_transacciones(self, sigs: list) -> list:
        trades = []
        # Procesar en lotes de 10 en paralelo
        for i in range(0, len(sigs), 10):
            lote    = sigs[i:i + 10]
            tareas  = [self._analizar_tx(s["signature"], s.get("blockTime", 0)) for s in lote]
            results = await asyncio.gather(*tareas, return_exceptions=True)
            for r in results:
                if isinstance(r, dict) and r:
                    trades.append(r)
            await asyncio.sleep(0.1)  # pausa mínima entre lotes
        return trades

    async def _analizar_tx(self, signature: str, block_time: int) -> Optional[dict]:
        try:
            tx_data = await self._rpc_call(
                "getTransaction",
                [signature, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}]
            )
            if not tx_data:
                return None

            meta    = tx_data.get("meta", {})
            message = tx_data.get("transaction", {}).get("message", {})

            if meta.get("err"):
                return None

            account_keys = message.get("accountKeys", [])
            es_dex = any(
                (key_info.get("pubkey", "") if isinstance(key_info, dict) else str(key_info))
                in DEX_PROGRAMAS
                for key_info in account_keys
            )
            if not es_dex:
                return None

            pre_sol   = sum(meta.get("preBalances",  [0])[:5]) / 1e9
            post_sol  = sum(meta.get("postBalances", [0])[:5]) / 1e9
            fee_sol   = meta.get("fee", 0) / 1e9
            delta_sol = (post_sol - pre_sol) + fee_sol

            pre_map  = {b["mint"]: float(b["uiTokenAmount"]["uiAmount"] or 0)
                        for b in meta.get("preTokenBalances", [])}
            post_map = {b["mint"]: float(b["uiTokenAmount"]["uiAmount"] or 0)
                        for b in meta.get("postTokenBalances", [])}

            token_principal = next(
                (m for m in (set(pre_map) | set(post_map))
                 if m not in (SOL_MINT, USDC_MINT)),
                None
            )

            return {
                "signature":   signature,
                "timestamp":   block_time,
                "delta_sol":   round(delta_sol, 6),
                "es_ganancia": delta_sol > 0,
                "token_mint":  token_principal,
            }

        except Exception as e:
            log.debug(f"Error TX {signature[:12]}: {e}")
            return None

    # ─────────────────────────────────────────────────────────────────────────
    #  SCORE Y MÉTRICAS
    # ─────────────────────────────────────────────────────────────────────────

    def _calcular_metricas(self, wallet: str, trades: list, total_sigs: int) -> dict:
        total      = len(trades)
        ganados    = [t for t in trades if t["es_ganancia"]]
        perdidos_l = [t for t in trades if not t["es_ganancia"]]
        win_rate   = (len(ganados) / total * 100) if total else 0

        ganancias = [t["delta_sol"] for t in ganados]
        perdidas  = [abs(t["delta_sol"]) for t in perdidos_l]
        avg_g     = sum(ganancias) / len(ganancias) if ganancias else 0
        avg_p     = sum(perdidas)  / len(perdidas)  if perdidas  else 0
        pf        = (avg_g / avg_p) if avg_p > 0 else avg_g
        pnl       = sum(t["delta_sol"] for t in trades)

        timestamps = sorted([t["timestamp"] for t in trades if t["timestamp"]])
        es_bot     = False
        if len(timestamps) > 10:
            intervalos = [timestamps[i + 1] - timestamps[i] for i in range(len(timestamps) - 1)]
            es_bot     = (sum(intervalos) / len(intervalos)) < 10

        rango_dias     = (timestamps[-1] - timestamps[0]) / 86400 if timestamps else 0
        trades_por_dia = total / max(rango_dias, 1)

        score = 0.0
        if win_rate >= 65:     score += 3.0
        elif win_rate >= 55:   score += 2.0
        elif win_rate >= 45:   score += 1.0
        if pf >= 2:            score += 2.0
        elif pf >= 1.5:        score += 1.5
        elif pf >= 1:          score += 1.0
        if total >= 40:        score += 2.0
        elif total >= 20:      score += 1.5
        elif total >= 10:      score += 1.0
        if not es_bot:
            score += 2.0 if trades_por_dia <= 10 else 1.0
        if pnl > 0:            score += 1.0
        score = min(round(score, 1), 10.0)

        if es_bot:            rec, emoji = "⛔ NO RECOMENDADA — posible bot",          "🔴"
        elif score >= 7.5:    rec, emoji = "✅ MUY RECOMENDADA — excelente historial",  "🟢"
        elif score >= 5.5:    rec, emoji = "🟡 ACEPTABLE — úsala con precaución",       "🟡"
        else:                 rec, emoji = "🔴 NO RECOMENDADA — historial débil",        "🔴"

        return {
            "wallet":           wallet,
            "fuente":           "On-chain",
            "score":            score,
            "emoji_score":      emoji,
            "recomendacion":    rec,
            "win_rate":         round(win_rate, 1),
            "total_trades":     total,
            "ganados":          len(ganados),
            "perdidos":         len(perdidos_l),
            "avg_ganancia_sol": round(avg_g, 4),
            "avg_perdida_sol":  round(avg_p, 4),
            "profit_factor":    round(pf, 2),
            "pnl_total_sol":    round(pnl, 4),
            "trades_por_dia":   round(trades_por_dia, 1),
            "tokens_unicos":    len(set(t["token_mint"] for t in trades if t["token_mint"])),
            "dias_analizados":  round(rango_dias),
            "es_bot":           es_bot,
            "error":            None,
            "pnl_en_usd":       False,
        }

    def _resultado_vacio(self, wallet: str, motivo: str) -> dict:
        return {
            "wallet":           wallet,
            "fuente":           "N/A",
            "score":            0.0,
            "emoji_score":      "⚫",
            "recomendacion":    f"❌ {motivo}",
            "win_rate":         0,
            "total_trades":     0,
            "ganados":          0,
            "perdidos":         0,
            "avg_ganancia_sol": 0,
            "avg_perdida_sol":  0,
            "profit_factor":    0,
            "pnl_total_sol":    0,
            "trades_por_dia":   0,
            "tokens_unicos":    0,
            "dias_analizados":  0,
            "es_bot":           False,
            "error":            motivo,
            "pnl_en_usd":       False,
        }

    async def cerrar(self):
        if self.session and not self.session.closed:
            await self.session.close()
