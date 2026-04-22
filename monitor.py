"""
monitor.py — Monitorea wallets de Solana en busca de nuevas transacciones
Revisa las últimas 10 TXs por wallet en cada ciclo para no perder ninguna
"""

import asyncio
import aiohttp
import logging
from typing import Optional

log = logging.getLogger(__name__)

# RPCs públicos confiables — sin keys demo, todos funcionales
SOLANA_RPC_URLS = [
    "https://api.mainnet-beta.solana.com",
    "https://solana.publicnode.com",
    "https://endpoints.omniatech.io/v1/sol/mainnet/public",
    "https://go.getblock.io/solana-mainnet",
]

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

SOL_MINT  = "So11111111111111111111111111111111111111112"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"


class WalletMonitor:
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
        self.rpc_index = 0
        # Guarda la signature MÁS RECIENTE vista por cada wallet.
        # Al primer ciclo de cada wallet, se marca el estado actual sin procesar nada.
        # Así el bot solo reacciona a TXs que ocurren DESPUÉS de arrancar.
        self._ultima_sig: dict = {}   # wallet_address -> signature más reciente

    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session

    def _siguiente_rpc(self) -> str:
        url = SOLANA_RPC_URLS[self.rpc_index % len(SOLANA_RPC_URLS)]
        self.rpc_index += 1
        return url

    async def _rpc_call(self, method: str, params: list) -> Optional[any]:
        session = await self._get_session()
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        for _ in range(len(SOLANA_RPC_URLS)):
            url = self._siguiente_rpc()
            try:
                async with session.post(url, json=payload,
                                        timeout=aiohttp.ClientTimeout(total=10)) as r:
                    if r.status == 200:
                        data = await r.json()
                        return data.get("result")
            except Exception as e:
                log.warning(f"RPC {url[:40]} falló: {e}")
        return None

    async def obtener_transacciones_nuevas(self, wallet_address: str, ya_procesadas: set) -> list:
        sigs = await self._rpc_call(
            "getSignaturesForAddress",
            [wallet_address, {"limit": 10}]
        )

        if not sigs:
            return []

        # ── PRIMERA VEZ que vemos esta wallet en esta sesión ─────────────────
        # Guardamos la TX más reciente como "punto de partida" y no procesamos nada.
        # Esto evita copiar operaciones que la ballena hizo hace horas/días.
        if wallet_address not in self._ultima_sig:
            sig_reciente = sigs[0].get("signature") if sigs else None
            self._ultima_sig[wallet_address] = sig_reciente
            log.info(f"🔖 Wallet {wallet_address[:8]} inicializada — "
                     f"última TX: {sig_reciente[:16] if sig_reciente else 'ninguna'}... "
                     f"(operaciones anteriores ignoradas)")
            return []  # No procesar historial

        # ── CICLOS SIGUIENTES — solo TXs más nuevas que la última vista ──────
        ultima_conocida = self._ultima_sig[wallet_address]
        nuevas = []
        for s in sigs:
            sig = s.get("signature")
            if sig == ultima_conocida:
                break  # llegamos al punto donde quedamos, parar
            if not s.get("err"):
                nuevas.append(s)

        if not nuevas:
            return []

        # Actualizar la última sig vista (la más reciente de este ciclo)
        self._ultima_sig[wallet_address] = sigs[0].get("signature")

        resultado = []
        for sig_info in nuevas:
            sig = sig_info["signature"]
            # Doble filtro con la DB por si acaso
            if sig in ya_procesadas:
                continue
            tx = await self._analizar_signature(sig)
            if tx:
                resultado.append(tx)
            await asyncio.sleep(0.2)

        return resultado

    async def ultima_transaccion(self, wallet_address: str) -> Optional[dict]:
        sigs = await self._rpc_call(
            "getSignaturesForAddress",
            [wallet_address, {"limit": 5}]
        )
        if not sigs:
            return None

        for sig_info in sigs:
            if sig_info.get("err"):
                continue
            tx = await self._analizar_signature(sig_info["signature"])
            if tx:
                return tx

        return None

    async def _analizar_signature(self, signature: str) -> Optional[dict]:
        tx_data = await self._rpc_call(
            "getTransaction",
            [signature, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}]
        )
        if not tx_data:
            return None
        return self._analizar_transaccion(tx_data, signature)

    def _analizar_transaccion(self, tx_data: dict, signature: str) -> Optional[dict]:
        try:
            meta    = tx_data.get("meta", {})
            message = tx_data.get("transaction", {}).get("message", {})

            if meta.get("err"):
                return None

            account_keys = message.get("accountKeys", [])
            dex_usado    = None
            for key_info in account_keys:
                pubkey = key_info.get("pubkey", "") if isinstance(key_info, dict) else str(key_info)
                if pubkey in DEX_PROGRAMAS:
                    dex_usado = DEX_PROGRAMAS[pubkey]
                    break

            if not dex_usado:
                return None

            pre_tok  = meta.get("preTokenBalances",  [])
            post_tok = meta.get("postTokenBalances", [])
            pre_map  = {b["mint"]: float(b["uiTokenAmount"]["uiAmount"] or 0) for b in pre_tok}
            post_map = {b["mint"]: float(b["uiTokenAmount"]["uiAmount"] or 0) for b in post_tok}

            todos_mints    = set(pre_map.keys()) | set(post_map.keys())
            token_comprado = None
            token_vendido  = None
            monto_comprado = 0
            monto_vendido  = 0

            for mint in todos_mints:
                if mint in (SOL_MINT, USDC_MINT):
                    continue
                pre  = pre_map.get(mint, 0)
                post = post_map.get(mint, 0)
                diff = post - pre
                if diff > 0:
                    token_comprado = mint
                    monto_comprado = diff
                elif diff < 0:
                    token_vendido = mint
                    monto_vendido = abs(diff)

            if not token_comprado and not token_vendido:
                return None

            accion     = "compra" if token_comprado else "venta"
            token_mint = token_comprado or token_vendido

            log.info(f"🔍 TX detectada | DEX: {dex_usado} | Acción: {accion} | Token: {token_mint[:8]}")

            return {
                "signature":  signature,
                "dex":        dex_usado,
                "accion":     accion,
                "token_mint": token_mint,
                "monto":      monto_comprado if accion == "compra" else monto_vendido,
                "timestamp":  tx_data.get("blockTime", 0),
            }

        except Exception as e:
            log.error(f"Error analizando TX {signature[:12]}: {e}")
            return None

    async def cerrar(self):
        if self.session and not self.session.closed:
            await self.session.close()
