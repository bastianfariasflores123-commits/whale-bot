"""
trader.py — Ejecuta swaps en Solana usando Jupiter Aggregator (mejor precio garantizado)
Jupiter es la plataforma DEX más usada en Solana, sin costo extra por usarla.
"""

import asyncio
import aiohttp
import logging
import base64
import time
from typing import Optional

log = logging.getLogger(__name__)

# Jupiter API (gratis, sin API key)
JUPITER_QUOTE_URL = "https://quote-api.jup.ag/v6/quote"
JUPITER_SWAP_URL  = "https://quote-api.jup.ag/v6/swap"

# Mints importantes
SOL_MINT  = "So11111111111111111111111111111111111111112"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

# Precio aproximado de SOL en USD (se actualiza dinámicamente)
SOL_PRECIO_USD = 150.0


class SolanaTrader:
    def __init__(self, private_key: str):
        self.private_key  = private_key
        self.keypair      = None
        self.session: Optional[aiohttp.ClientSession] = None

        if private_key:
            self._cargar_keypair()

    def _cargar_keypair(self):
        """Carga el keypair desde la clave privada."""
        try:
            from solders.keypair import Keypair  # type: ignore
            key_bytes    = base64.b58decode(self.private_key)
            self.keypair = Keypair.from_bytes(key_bytes)
            log.info(f"Wallet cargada: {str(self.keypair.pubkey())[:12]}...")
        except Exception as e:
            log.warning(f"No se pudo cargar keypair: {e}. Modo simulación activado.")
            self.keypair = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session

    async def obtener_precio_sol(self) -> float:
        """Obtiene el precio actual de SOL en USD desde Jupiter."""
        try:
            session = await self._get_session()
            url = f"https://price.jup.ag/v4/price?ids={SOL_MINT}"
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as r:
                if r.status == 200:
                    data = await r.json()
                    precio = data.get("data", {}).get(SOL_MINT, {}).get("price", SOL_PRECIO_USD)
                    return float(precio)
        except Exception as e:
            log.warning(f"No se pudo obtener precio SOL: {e}")
        return SOL_PRECIO_USD

    async def obtener_cotizacion(self, input_mint: str, output_mint: str, monto_lamports: int) -> Optional[dict]:
        """Obtiene la mejor cotización de Jupiter para el swap."""
        session = await self._get_session()
        params  = {
            "inputMint":        input_mint,
            "outputMint":       output_mint,
            "amount":           str(monto_lamports),
            "slippageBps":      "100",   # 1% slippage máximo
            "onlyDirectRoutes": "false",
        }
        try:
            async with session.get(JUPITER_QUOTE_URL, params=params,
                                   timeout=aiohttp.ClientTimeout(total=10)) as r:
                if r.status == 200:
                    return await r.json()
        except Exception as e:
            log.error(f"Error obteniendo cotización: {e}")
        return None

    async def ejecutar_swap(self, quote_response: dict) -> Optional[str]:
        """Ejecuta el swap con la cotización obtenida. Retorna el hash de TX."""
        if not self.keypair:
            # Modo simulación
            log.info("🎭 SIMULACIÓN: swap ejecutado (sin keypair real)")
            return f"SIM_{int(time.time())}"

        try:
            from solders.transaction import VersionedTransaction  # type: ignore
            from solana.rpc.async_api import AsyncClient           # type: ignore

            session  = await self._get_session()
            pubkey   = str(self.keypair.pubkey())

            # Solicitar la transacción serializada a Jupiter
            payload = {
                "quoteResponse":             quote_response,
                "userPublicKey":             pubkey,
                "wrapAndUnwrapSol":          True,
                "dynamicComputeUnitLimit":   True,
                "prioritizationFeeLamports": 1000,  # fee de prioridad (~$0.0001)
            }

            async with session.post(JUPITER_SWAP_URL, json=payload,
                                    timeout=aiohttp.ClientTimeout(total=15)) as r:
                if r.status != 200:
                    log.error(f"Jupiter swap error: {r.status}")
                    return None
                swap_data = await r.json()

            # Firmar y enviar la transacción
            tx_bytes = base64.b64decode(swap_data["swapTransaction"])
            tx       = VersionedTransaction.from_bytes(tx_bytes)
            tx.sign([self.keypair])

            async with AsyncClient("https://api.mainnet-beta.solana.com") as client:
                resp = await client.send_raw_transaction(bytes(tx))
                return str(resp.value)

        except Exception as e:
            log.error(f"Error ejecutando swap: {e}")
            return None

    async def copiar_trade(self, token_mint: str, accion: str, monto_usd: float,
                           stop_loss: float, take_profit: float, max_minutos: float) -> dict:
        """
        Copia un trade de ballena.
        - accion: "compra" | "venta"
        - monto_usd: cuántos USD invertir (cantidad fija configurada por el usuario)
        Retorna dict con resultado de la operación.
        """
        inicio = time.time()

        # Convertir USD a lamports (unidad de SOL, 1 SOL = 1_000_000_000 lamports)
        precio_sol   = await self.obtener_precio_sol()
        sol_amount   = monto_usd / precio_sol
        lamports     = int(sol_amount * 1_000_000_000)

        log.info(f"Copiando {accion} de {token_mint[:8]}... | ${monto_usd} USD | {sol_amount:.4f} SOL")

        resultado_base = {
            "token":      token_mint[:8] + "...",
            "token_mint": token_mint,
            "accion":     accion,
            "invertido":  monto_usd,
            "tx_hash":    None,
            "pnl_usd":    0.0,
            "duracion_min": 0,
            "estado":     "error",
        }

        try:
            # Determinar dirección del swap
            if accion == "compra":
                input_mint  = SOL_MINT
                output_mint = token_mint
            else:
                input_mint  = token_mint
                output_mint = SOL_MINT

            # Obtener cotización de entrada
            quote_entrada = await self.obtener_cotizacion(input_mint, output_mint, lamports)
            if not quote_entrada:
                resultado_base["estado"] = "sin_cotizacion"
                return resultado_base

            # Ejecutar swap de entrada
            tx_entrada = await self.ejecutar_swap(quote_entrada)
            if not tx_entrada:
                resultado_base["estado"] = "swap_fallido"
                return resultado_base

            resultado_base["tx_hash"] = tx_entrada
            tokens_obtenidos = int(quote_entrada.get("outAmount", 0))

            log.info(f"✅ Swap ejecutado: {tx_entrada[:20]}... | Tokens: {tokens_obtenidos}")

            # ── Monitorear posición (esperar SL/TP/timeout) ──────────────────
            precio_entrada = monto_usd / (tokens_obtenidos or 1)
            max_segundos   = max_minutos * 60
            sl_factor      = 1 - (stop_loss / 100)
            tp_factor      = 1 + (take_profit / 100)

            pnl = 0.0
            while True:
                elapsed = (time.time() - inicio) / 60

                # Obtener precio actual del token en SOL
                quote_actual = await self.obtener_cotizacion(
                    token_mint, SOL_MINT, tokens_obtenidos
                )

                if quote_actual:
                    valor_actual_sol     = int(quote_actual.get("outAmount", 0)) / 1_000_000_000
                    valor_actual_usd     = valor_actual_sol * precio_sol
                    pnl                  = valor_actual_usd - monto_usd
                    cambio_pct           = valor_actual_usd / monto_usd if monto_usd else 1

                    log.info(f"Posición: ${valor_actual_usd:.2f} | P&L: {'+' if pnl>=0 else ''}{pnl:.2f} | {elapsed:.1f}min")

                    # Check take profit
                    if cambio_pct >= tp_factor:
                        log.info(f"🎯 Take Profit alcanzado ({take_profit}%)")
                        break

                    # Check stop loss
                    if cambio_pct <= sl_factor:
                        log.info(f"🛑 Stop Loss activado ({stop_loss}%)")
                        break

                # Check timeout
                if (time.time() - inicio) >= max_segundos:
                    log.info(f"⏱️ Timeout alcanzado ({max_minutos} min)")
                    break

                await asyncio.sleep(30)  # revisar cada 30 segundos

            # ── Cerrar posición (vender tokens) ──────────────────────────────
            if accion == "compra" and tokens_obtenidos > 0:
                quote_salida = await self.obtener_cotizacion(token_mint, SOL_MINT, tokens_obtenidos)
                if quote_salida:
                    tx_salida = await self.ejecutar_swap(quote_salida)
                    sol_obtenido = int(quote_salida.get("outAmount", 0)) / 1_000_000_000
                    valor_final  = sol_obtenido * precio_sol
                    pnl          = valor_final - monto_usd

            duracion = round((time.time() - inicio) / 60, 1)
            resultado_base.update({
                "pnl_usd":      round(pnl, 4),
                "duracion_min": duracion,
                "estado":       "cerrado",
            })

        except Exception as e:
            log.error(f"Error en copiar_trade: {e}")
            resultado_base["estado"] = f"error: {str(e)[:50]}"

        return resultado_base

    async def cerrar(self):
        if self.session and not self.session.closed:
            await self.session.close()
