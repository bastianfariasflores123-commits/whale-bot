"""
monitor.py — Monitorea wallets de Solana en busca de nuevas transacciones (swaps)
Usa la RPC pública de Solana (gratis, sin API key)
"""

import asyncio
import aiohttp
import logging
from typing import Optional

log = logging.getLogger(__name__)

# RPCs públicas de Solana (gratis)
SOLANA_RPC_URLS = [
    "https://api.mainnet-beta.solana.com",
    "https://solana-api.projectserum.com",
    "https://rpc.ankr.com/solana",
]

# Programas DEX conocidos en Solana
DEX_PROGRAMAS = {
    "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4": "Jupiter",
    "9W959DqEETiGZocYWCQPaJ6sBmUzgfxXfqGeTEdp3aQP": "Orca",
    "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8": "Raydium",
    "whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc":  "Whirlpool",
}


class WalletMonitor:
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
        self.rpc_index = 0  # rotación de RPCs

    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session

    def _siguiente_rpc(self) -> str:
        url = SOLANA_RPC_URLS[self.rpc_index % len(SOLANA_RPC_URLS)]
        self.rpc_index += 1
        return url

    async def _rpc_call(self, method: str, params: list) -> Optional[dict]:
        """Hace una llamada JSON-RPC a Solana."""
        session = await self._get_session()
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}

        for _ in range(len(SOLANA_RPC_URLS)):
            url = self._siguiente_rpc()
            try:
                async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as r:
                    if r.status == 200:
                        data = await r.json()
                        return data.get("result")
            except Exception as e:
                log.warning(f"RPC {url} falló: {e}")

        return None

    async def ultima_transaccion(self, wallet_address: str) -> Optional[dict]:
        """
        Obtiene la última transacción de la wallet.
        Retorna un dict con los datos del swap si es relevante, None si no.
        """
        # 1. Obtener últimas firmas de transacciones
        sigs = await self._rpc_call(
            "getSignaturesForAddress",
            [wallet_address, {"limit": 5}]
        )

        if not sigs:
            return None

        # Tomar la más reciente
        ultima_sig = sigs[0]
        signature  = ultima_sig.get("signature", "")

        if ultima_sig.get("err"):
            return None  # transacción fallida, ignorar

        # 2. Obtener los detalles de la transacción
        tx_data = await self._rpc_call(
            "getTransaction",
            [signature, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}]
        )

        if not tx_data:
            return None

        # 3. Analizar si es un swap en DEX
        return self._analizar_transaccion(tx_data, signature)

    def _analizar_transaccion(self, tx_data: dict, signature: str) -> Optional[dict]:
        """
        Analiza los datos de la transacción para determinar si es un swap.
        Retorna dict con info relevante o None si no es swap.
        """
        try:
            meta    = tx_data.get("meta", {})
            message = tx_data.get("transaction", {}).get("message", {})

            # Verificar si interactúa con algún DEX conocido
            account_keys = message.get("accountKeys", [])
            dex_usado    = None
            for key_info in account_keys:
                pubkey = key_info.get("pubkey", "") if isinstance(key_info, dict) else str(key_info)
                if pubkey in DEX_PROGRAMAS:
                    dex_usado = DEX_PROGRAMAS[pubkey]
                    break

            if not dex_usado:
                return None  # No es un swap en DEX conocido

            # Analizar cambios de balance para determinar qué token se compró/vendió
            pre_balances  = meta.get("preTokenBalances", [])
            post_balances = meta.get("postTokenBalances", [])

            token_comprado  = None
            token_vendido   = None
            monto_comprado  = 0
            monto_vendido   = 0

            # Mapear balances por mint
            pre_map  = {b["mint"]: float(b["uiTokenAmount"]["uiAmount"] or 0) for b in pre_balances}
            post_map = {b["mint"]: float(b["uiTokenAmount"]["uiAmount"] or 0) for b in post_balances}

            todos_mints = set(pre_map.keys()) | set(post_map.keys())

            for mint in todos_mints:
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

            return {
                "signature":   signature,
                "dex":         dex_usado,
                "accion":      accion,
                "token_mint":  token_mint,
                "monto":       monto_comprado if accion == "compra" else monto_vendido,
                "timestamp":   tx_data.get("blockTime", 0),
            }

        except Exception as e:
            log.error(f"Error analizando TX: {e}")
            return None

    async def cerrar(self):
        if self.session and not self.session.closed:
            await self.session.close()
