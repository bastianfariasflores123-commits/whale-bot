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

# URLs de Jupiter — con fallback por si una falla
JUPITER_QUOTE_URLS = [
    "https://quote-api.jup.ag/v6/quote",
    "https://jupiter-swap-api.quiknode.pro/quote",
]
JUPITER_SWAP_URLS = [
    "https://quote-api.jup.ag/v6/swap",
    "https://jupiter-swap-api.quiknode.pro/swap",
]

# URLs para obtener precio de SOL — múltiples fuentes
SOL_PRECIO_URLS = [
    "https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd",
    "https://price.jup.ag/v4/price?ids=So11111111111111111111111111111111111111112",
    "https://api.binance.com/api/v3/ticker/price?symbol=SOLUSDT",
]

# RPCs Solana confiables para enviar transacciones
SOLANA_RPC_URLS = [
    "https://api.mainnet-beta.solana.com",
    "https://rpc.ankr.com/solana",
    "https://solana-mainnet.g.alchemy.com/v2/demo",
    "https://mainnet.helius-rpc.com/?api-key=demo",
]

SOL_MINT       = "So11111111111111111111111111111111111111112"
USDC_MINT      = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
SOL_PRECIO_USD = 140.0  # fallback si todas las APIs fallan


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

            key_bytes = b58lib.b58decode(self.private_key)

            if len(key_bytes) == 64:
                self.keypair    = Keypair.from_bytes(key_bytes)
                self.pubkey_str = str(self.keypair.pubkey())
                log.info(f"✅ Wallet cargada correctamente: {self.pubkey_str[:12]}...")
            elif len(key_bytes) == 32:
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
        return self.keypair is not None

    async def obtener_precio_sol(self) -> float:
        """Obtiene el precio de SOL desde múltiples fuentes con fallback."""
        session = await self._get_session()

        # Fuente 1: CoinGecko
        try:
            async with session.get(
                "https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd",
                timeout=aiohttp.ClientTimeout(total=5)
            ) as r:
                if r.status == 200:
                    data = await r.json()
                    precio = data.get("solana", {}).get("usd", 0)
                    if precio > 0:
                        log.info(f"💲 Precio SOL (CoinGecko): ${precio}")
                        return float(precio)
        except Exception as e:
            log.warning(f"CoinGecko falló: {e}")

        # Fuente 2: Jupiter Price API
        try:
            async with session.get(
                f"https://price.jup.ag/v4/price?ids={SOL_MINT}",
                timeout=aiohttp.ClientTimeout(total=5)
            ) as r:
                if r.status == 200:
                    data   = await r.json()
                    precio = data.get("data", {}).get(SOL_MINT, {}).get("price", 0)
                    if precio > 0:
                        log.info(f"💲 Precio SOL (Jupiter): ${precio}")
                        return float(precio)
        except Exception as e:
            log.warning(f"Jupiter price falló: {e}")

        # Fuente 3: Binance
        try:
            async with session.get(
                "https://api.binance.com/api/v3/ticker/price?symbol=SOLUSDT",
                timeout=aiohttp.ClientTimeout(total=5)
            ) as r:
                if r.status == 200:
                    data   = await r.json()
                    precio = float(data.get("price", 0))
                    if precio > 0:
                        log.info(f"💲 Precio SOL (Binance): ${precio}")
                        return precio
        except Exception as e:
            log.warning(f"Binance falló: {e}")

        log.warning(f"⚠️ Todas las fuentes de precio fallaron — usando fallback ${SOL_PRECIO_USD}")
        return SOL_PRECIO_USD

    async def obtener_cotizacion(self, input_mint: str, output_mint: str, monto_lamports: int) -> Optional[dict]:
        """Obtiene cotización de Jupiter con reintentos y fallback de URL."""
        session = await self._get_session()
        params  = {
            "inputMint":        input_mint,
            "outputMint":       output_mint,
            "amount":           str(monto_lamports),
            "slippageBps":      "150",
            "onlyDirectRoutes": "false",
        }

        for url in JUPITER_QUOTE_URLS:
            for intento in range(3):  # 3 reintentos por URL
                try:
                    async with session.get(
                        url, params=params,
                        timeout=aiohttp.ClientTimeout(total=15)
                    ) as r:
                        if r.status == 200:
                            data = await r.json()
                            if data and "outAmount" in data:
                                return data
                            log.warning(f"Jupiter cotización vacía (intento {intento+1})")
                        else:
                            log.warning(f"Jupiter quote status {r.status} en {url[:40]}")
                except Exception as e:
                    log.warning(f"Jupiter quote error (intento {intento+1}): {e}")

                if intento < 2:
                    await asyncio.sleep(1)  # espera 1s entre reintentos

        log.error("❌ Jupiter no disponible — no se pudo obtener cotización")
        return None

    async def ejecutar_swap(self, quote_response: dict) -> Optional[str]:
        """Ejecuta el swap REAL con reintentos. Retorna el hash de la transacción."""
        if not self.keypair:
            log.error("❌ No hay keypair cargado — no se puede ejecutar swap real")
            return None

        try:
            from solders.transaction import VersionedTransaction

            session = await self._get_session()
            pubkey  = self.pubkey_str

            payload = {
                "quoteResponse":             quote_response,
                "userPublicKey":             pubkey,
                "wrapAndUnwrapSol":          True,
                "dynamicComputeUnitLimit":   True,
                "prioritizationFeeLamports": 5000,
            }

            # Intentar cada URL de swap con reintentos
            swap_data = None
            for url in JUPITER_SWAP_URLS:
                for intento in range(3):
                    try:
                        async with session.post(
                            url, json=payload,
                            timeout=aiohttp.ClientTimeout(total=25)
                        ) as r:
                            if r.status == 200:
                                swap_data = await r.json()
                                if "swapTransaction" in swap_data:
                                    break
                                log.warning(f"Jupiter swap sin swapTransaction: {swap_data}")
                            else:
                                log.warning(f"Jupiter swap status {r.status} en {url[:40]}")
                    except Exception as e:
                        log.warning(f"Jupiter swap error (intento {intento+1}): {e}")

                    if intento < 2:
                        await asyncio.sleep(1)

                if swap_data and "swapTransaction" in swap_data:
                    break

            if not swap_data or "swapTransaction" not in swap_data:
                log.error("❌ No se pudo obtener swapTransaction de Jupiter")
                return None

            # Firmar la transacción
            tx_bytes  = base64.b64decode(swap_data["swapTransaction"])
            tx        = VersionedTransaction.from_bytes(tx_bytes)
            signed_tx = VersionedTransaction(tx.message, [self.keypair])

            # Enviar a la red con fallback de RPC
            for rpc_url in SOLANA_RPC_URLS:
                try:
                    from solana.rpc.async_api import AsyncClient
                    from solana.rpc.types import TxOpts

                    async with AsyncClient(rpc_url) as client:
                        resp    = await client.send_raw_transaction(
                            bytes(signed_tx),
                            opts=TxOpts(skip_preflight=False, preflight_commitment="confirmed")
                        )
                        tx_hash = str(resp.value)
                        log.info(f"✅ Swap ejecutado via {rpc_url[:30]}: {tx_hash[:20]}...")
                        return tx_hash
                except Exception as e:
                    log.warning(f"RPC {rpc_url[:30]} falló al enviar TX: {e}")

            log.error("❌ Todos los RPCs fallaron al enviar la transacción")
            return None

        except Exception as e:
            log.error(f"Error ejecutando swap real: {e}")
            return None

    async def copiar_trade(self, token_mint: str, accion: str, monto_usd: float,
                           stop_loss: float, take_profit: float, max_minutos: float) -> dict:
        inicio     = time.time()
        precio_sol = await self.obtener_precio_sol()
        sol_amount = monto_usd / precio_sol
        lamports   = int(sol_amount * 1_000_000_000)

        log.info(f"{'🟢' if accion == 'compra' else '🔴'} Copiando {accion} | Token: {token_mint[:8]} | ${monto_usd} | SOL: ${precio_sol:.2f}")

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
            input_mint  = SOL_MINT   if accion == "compra" else token_mint
            output_mint = token_mint if accion == "compra" else SOL_MINT

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

                # Actualizar precio SOL cada 5 minutos para mayor precisión
                if int(elapsed) % 5 == 0 and elapsed > 0:
                    precio_sol = await self.obtener_precio_sol()

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
                else:
                    log.warning(f"⚠️ Sin cotización al monitorear — reintentando en 30s")

                if (time.time() - inicio) >= max_segundos:
                    log.info(f"⏱️ Timeout {max_minutos}min alcanzado")
                    break

                await asyncio.sleep(30)

            # Cerrar posición
            if accion == "compra" and tokens_obtenidos > 0:
                # Reintentar hasta 3 veces el cierre
                for intento_cierre in range(3):
                    quote_salida = await self.obtener_cotizacion(token_mint, SOL_MINT, tokens_obtenidos)
                    if quote_salida:
                        tx_salida   = await self.ejecutar_swap(quote_salida)
                        if tx_salida:
                            sol_final   = int(quote_salida.get("outAmount", 0)) / 1_000_000_000
                            valor_final = sol_final * precio_sol
                            pnl         = valor_final - monto_usd
                            log.info(f"{'✅' if pnl>=0 else '❌'} Posición cerrada | PnL: {'+' if pnl>=0 else ''}${pnl:.2f}")
                            break
                    log.warning(f"Reintentando cierre {intento_cierre+1}/3...")
                    await asyncio.sleep(2)

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
