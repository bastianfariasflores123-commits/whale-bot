"""
trader.py — Ejecuta swaps REALES en Solana usando Jupiter Aggregator
Sin simulación — todo es real con la wallet de Phantom
"""

import asyncio
import aiohttp
import logging
import base64
import time
from typing import Optional

log = logging.getLogger(__name__)

JUPITER_QUOTE_URL = "https://quote-api.jup.ag/v6/quote"
JUPITER_SWAP_URL  = "https://quote-api.jup.ag/v6/swap"

SOL_MINT       = "So11111111111111111111111111111111111111112"
USDC_MINT      = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
SOL_PRECIO_USD = 150.0


class SolanaTrader:
    def __init__(self, private_key: str):
        self.private_key = private_key
        self.keypair     = None
        self.pubkey_str  = None
        self.session: Optional[aiohttp.ClientSession] = None

        if private_key:
            self._cargar_keypair()

    def _cargar_keypair(self):
        """
        Carga el keypair desde la clave privada de Phantom.
        Phantom exporta la clave en base58 de 64 bytes (secret + pubkey).
        """
        try:
            import base58 as b58lib
            from solders.keypair import Keypair

            # Decodificar base58 → 64 bytes
            key_bytes = b58lib.b58decode(self.private_key)

            if len(key_bytes) == 64:
                self.keypair    = Keypair.from_bytes(key_bytes)
                self.pubkey_str = str(self.keypair.pubkey())
                log.info(f"✅ Wallet cargada correctamente: {self.pubkey_str[:12]}...")
            elif len(key_bytes) == 32:
                # Solo secret key — intentar from_seed
                self.keypair    = Keypair.from_seed(key_bytes)
                self.pubkey_str = str(self.keypair.pubkey())
                log.info(f"✅ Wallet cargada (seed 32b): {self.pubkey_str[:12]}...")
            else:
                raise ValueError(f"Longitud de clave inválida: {len(key_bytes)} bytes")

        except Exception as e:
            log.error(f"❌ No se pudo cargar keypair: {e}")
            log.error("Verifica que SOLANA_PRIVATE_KEY sea la clave exportada desde Phantom")
            self.keypair = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session

    def esta_listo(self) -> bool:
        """Retorna True si el keypair está cargado y listo para operar."""
        return self.keypair is not None

    async def obtener_precio_sol(self) -> float:
        try:
            session = await self._get_session()
            url = f"https://price.jup.ag/v4/price?ids={SOL_MINT}"
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as r:
                if r.status == 200:
                    data   = await r.json()
                    precio = data.get("data", {}).get(SOL_MINT, {}).get("price", SOL_PRECIO_USD)
                    return float(precio)
        except Exception as e:
            log.warning(f"No se pudo obtener precio SOL: {e}")
        return SOL_PRECIO_USD

    async def obtener_cotizacion(self, input_mint: str, output_mint: str, monto_lamports: int) -> Optional[dict]:
        session = await self._get_session()
        params  = {
            "inputMint":        input_mint,
            "outputMint":       output_mint,
            "amount":           str(monto_lamports),
            "slippageBps":      "150",   # 1.5% slippage
            "onlyDirectRoutes": "false",
        }
        try:
            async with session.get(JUPITER_QUOTE_URL, params=params,
                                   timeout=aiohttp.ClientTimeout(total=10)) as r:
                if r.status == 200:
                    return await r.json()
                log.warning(f"Jupiter quote status: {r.status}")
        except Exception as e:
            log.error(f"Error cotización Jupiter: {e}")
        return None

    async def ejecutar_swap(self, quote_response: dict) -> Optional[str]:
        """Ejecuta el swap REAL. Retorna el hash de la transacción."""
        if not self.keypair:
            log.error("❌ No hay keypair cargado — no se puede ejecutar swap real")
            return None

        try:
            from solders.transaction import VersionedTransaction
            from solana.rpc.async_api import AsyncClient
            from solana.rpc.types import TxOpts

            session = await self._get_session()
            pubkey  = self.pubkey_str

            # 1. Pedir transacción serializada a Jupiter
            payload = {
                "quoteResponse":             quote_response,
                "userPublicKey":             pubkey,
                "wrapAndUnwrapSol":          True,
                "dynamicComputeUnitLimit":   True,
                "prioritizationFeeLamports": 5000,
            }

            async with session.post(JUPITER_SWAP_URL, json=payload,
                                    timeout=aiohttp.ClientTimeout(total=20)) as r:
                if r.status != 200:
                    log.error(f"Jupiter swap error status: {r.status}")
                    return None
                swap_data = await r.json()

            if "swapTransaction" not in swap_data:
                log.error(f"Jupiter no retornó swapTransaction: {swap_data}")
                return None

            # 2. Firmar la transacción
            tx_bytes = base64.b64decode(swap_data["swapTransaction"])
            tx       = VersionedTransaction.from_bytes(tx_bytes)

            # Firmar con el keypair
            signed_tx = VersionedTransaction(tx.message, [self.keypair])

            # 3. Enviar a la red
            async with AsyncClient("https://api.mainnet-beta.solana.com") as client:
                resp = await client.send_raw_transaction(
                    bytes(signed_tx),
                    opts=TxOpts(skip_preflight=False, preflight_commitment="confirmed")
                )
                tx_hash = str(resp.value)
                log.info(f"✅ Swap real ejecutado: {tx_hash[:20]}...")
                return tx_hash

        except Exception as e:
            log.error(f"Error ejecutando swap real: {e}")
            return None

    async def copiar_trade(self, token_mint: str, accion: str, monto_usd: float,
                           stop_loss: float, take_profit: float, max_minutos: float) -> dict:
        inicio     = time.time()
        precio_sol = await self.obtener_precio_sol()
        sol_amount = monto_usd / precio_sol
        lamports   = int(sol_amount * 1_000_000_000)

        log.info(f"{'🟢' if accion == 'compra' else '🔴'} Copiando {accion} | Token: {token_mint[:8]} | ${monto_usd}")

        resultado = {
            "token":        token_mint[:8] + "...",
            "token_mint":   token_mint,
            "accion":       accion,
            "invertido":    monto_usd,
            "tx_hash":      None,
            "pnl_usd":      0.0,
            "duracion_min": 0,
            "estado":       "error",
        }

        try:
            input_mint  = SOL_MINT    if accion == "compra" else token_mint
            output_mint = token_mint  if accion == "compra" else SOL_MINT

            # Cotización de entrada
            quote_entrada = await self.obtener_cotizacion(input_mint, output_mint, lamports)
            if not quote_entrada:
                resultado["estado"] = "sin_cotizacion"
                log.warning(f"Sin cotización para {token_mint[:8]}")
                return resultado

            # Ejecutar compra
            tx_entrada = await self.ejecutar_swap(quote_entrada)
            if not tx_entrada:
                resultado["estado"] = "swap_fallido"
                return resultado

            resultado["tx_hash"] = tx_entrada
            tokens_obtenidos     = int(quote_entrada.get("outAmount", 0))
            log.info(f"✅ Posición abierta | TX: {tx_entrada[:20]} | Tokens: {tokens_obtenidos}")

            # Monitorear posición
            max_segundos = max_minutos * 60
            sl_factor    = 1 - (stop_loss / 100)
            tp_factor    = 1 + (take_profit / 100)
            pnl          = 0.0

            while True:
                elapsed = (time.time() - inicio) / 60

                quote_actual = await self.obtener_cotizacion(token_mint, SOL_MINT, tokens_obtenidos)
                if quote_actual:
                    valor_sol = int(quote_actual.get("outAmount", 0)) / 1_000_000_000
                    valor_usd = valor_sol * precio_sol
                    pnl       = valor_usd - monto_usd
                    cambio    = valor_usd / monto_usd if monto_usd else 1

                    log.info(f"📊 Posición: ${valor_usd:.2f} | PnL: {'+' if pnl>=0 else ''}{pnl:.2f} | {elapsed:.1f}min")

                    if cambio >= tp_factor:
                        log.info(f"🎯 Take Profit {take_profit}% alcanzado")
                        break
                    if cambio <= sl_factor:
                        log.info(f"🛑 Stop Loss {stop_loss}% activado")
                        break

                if (time.time() - inicio) >= max_segundos:
                    log.info(f"⏱️ Timeout {max_minutos}min alcanzado")
                    break

                await asyncio.sleep(30)

            # Cerrar posición
            if accion == "compra" and tokens_obtenidos > 0:
                quote_salida = await self.obtener_cotizacion(token_mint, SOL_MINT, tokens_obtenidos)
                if quote_salida:
                    tx_salida    = await self.ejecutar_swap(quote_salida)
                    sol_final    = int(quote_salida.get("outAmount", 0)) / 1_000_000_000
                    valor_final  = sol_final * precio_sol
                    pnl          = valor_final - monto_usd
                    log.info(f"{'✅' if pnl>=0 else '❌'} Posición cerrada | PnL: {'+' if pnl>=0 else ''}${pnl:.2f}")

            duracion = round((time.time() - inicio) / 60, 1)
            resultado.update({
                "pnl_usd":      round(pnl, 4),
                "duracion_min": duracion,
                "estado":       "cerrado",
            })

        except Exception as e:
            log.error(f"Error en copiar_trade: {e}")
            resultado["estado"] = f"error: {str(e)[:80]}"

        return resultado

    async def cerrar(self):
        if self.session and not self.session.closed:
            await self.session.close()
