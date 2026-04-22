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

# Jupiter — public.jupiterapi.com primero, único que funciona en Railway
# lite.jup.ag y quote-api.jup.ag están bloqueados en Railway (DNS no resuelve)
JUPITER_QUOTE_URLS = [
    "https://public.jupiterapi.com/quote",
    "https://quote-api.jup.ag/v6/quote",
    "https://lite.jup.ag/v6/quote",
]
JUPITER_SWAP_URLS = [
    "https://public.jupiterapi.com/swap",
    "https://quote-api.jup.ag/v6/swap",
    "https://lite.jup.ag/v6/swap",
]

# RPCs — solana.publicnode.com crashea con PanicException, excluido
SOLANA_RPC_URLS = [
    "https://api.mainnet-beta.solana.com",
    "https://endpoints.omniatech.io/v1/sol/mainnet/public",
    "https://rpc.ankr.com/solana",
]

SOL_MINT       = "So11111111111111111111111111111111111111112"
USDC_MINT      = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
SOL_PRECIO_USD = 140.0


class SolanaTrader:
    def __init__(self, private_key: str):
        self.private_key = private_key
        self.keypair     = None
        self.pubkey_str  = None
        self.session: Optional[aiohttp.ClientSession] = None

        if private_key:
            self._cargar_keypair()

    def _cargar_keypair(self):
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
            self.keypair = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session

    def esta_listo(self) -> bool:
        return self.keypair is not None

    async def obtener_precio_sol(self) -> float:
        session = await self._get_session()

        try:
            async with session.get(
                "https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd",
                timeout=aiohttp.ClientTimeout(total=5)
            ) as r:
                if r.status == 200:
                    data   = await r.json()
                    precio = data.get("solana", {}).get("usd", 0)
                    if precio > 0:
                        log.info(f"💲 Precio SOL (CoinGecko): ${precio}")
                        return float(precio)
        except Exception as e:
            log.warning(f"CoinGecko falló: {e}")

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

        log.warning(f"⚠️ Precio SOL fallback: ${SOL_PRECIO_USD}")
        return SOL_PRECIO_USD

    async def obtener_cotizacion(self, input_mint: str, output_mint: str,
                                  monto_lamports: int, slippage_bps: int = 1500) -> Optional[dict]:
        session = await self._get_session()
        params  = {
            "inputMint":           input_mint,
            "outputMint":          output_mint,
            "amount":              str(monto_lamports),
            "slippageBps":         str(slippage_bps),
            "onlyDirectRoutes":    "false",
            "asLegacyTransaction": "false",  # necesario para tokens Token-2022 de Pump.fun
        }

        for quote_url in JUPITER_QUOTE_URLS:
            for intento in range(2):
                try:
                    async with session.get(
                        quote_url, params=params,
                        timeout=aiohttp.ClientTimeout(total=15)
                    ) as r:
                        if r.status == 200:
                            data = await r.json()
                            if data and "outAmount" in data:
                                log.info(f"✅ Cotización obtenida via {quote_url[:35]}")
                                return data
                        else:
                            text = await r.text()
                            log.warning(f"Jupiter {quote_url[:35]} status {r.status}: {text[:80]}")
                except Exception as e:
                    log.warning(f"Jupiter {quote_url[:35]} error (intento {intento+1}): {e}")

                if intento < 1:
                    await asyncio.sleep(1)

        log.error("❌ Jupiter no disponible tras todos los intentos")
        return None

    async def ejecutar_swap(self, quote_response: dict) -> Optional[str]:
        if not self.keypair:
            log.error("❌ No hay keypair cargado")
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
                "prioritizationFeeLamports": 50000,
            }

            swap_data = None
            for swap_url in JUPITER_SWAP_URLS:
                for intento in range(2):
                    try:
                        async with session.post(
                            swap_url, json=payload,
                            timeout=aiohttp.ClientTimeout(total=25)
                        ) as r:
                            if r.status == 200:
                                swap_data = await r.json()
                                if "swapTransaction" in swap_data:
                                    log.info(f"✅ SwapTX obtenida via {swap_url[:35]}")
                                    break
                                swap_data = None
                            else:
                                log.warning(f"Swap {swap_url[:35]} status {r.status}")
                    except Exception as e:
                        log.warning(f"Swap {swap_url[:35]} error (intento {intento+1}): {e}")

                    if intento < 1:
                        await asyncio.sleep(1)

                if swap_data and "swapTransaction" in swap_data:
                    break

            if not swap_data or "swapTransaction" not in swap_data:
                log.error("❌ No se pudo obtener swapTransaction")
                return None

            tx_bytes  = base64.b64decode(swap_data["swapTransaction"])
            tx        = VersionedTransaction.from_bytes(tx_bytes)
            signed_tx = VersionedTransaction(tx.message, [self.keypair])

            # skip_preflight=True para evitar crash PanicException con algunos RPCs
            for rpc_url in SOLANA_RPC_URLS:
                try:
                    from solana.rpc.async_api import AsyncClient
                    from solana.rpc.types import TxOpts

                    async with AsyncClient(rpc_url) as client:
                        resp    = await client.send_raw_transaction(
                            bytes(signed_tx),
                            opts=TxOpts(skip_preflight=True, preflight_commitment="confirmed")
                        )
                        tx_hash = str(resp.value)
                        log.info(f"✅ Swap enviado via {rpc_url[:35]}: {tx_hash[:20]}...")
                        return tx_hash
                except Exception as e:
                    log.warning(f"RPC {rpc_url[:35]} falló: {e}")

            log.error("❌ Todos los RPCs fallaron al enviar TX")
            return None

        except Exception as e:
            log.error(f"Error ejecutando swap: {e}")
            return None

    async def verificar_tx(self, tx_hash: str, max_intentos: int = 5, espera: float = 4.0) -> bool:
        """
        Verifica si una TX realmente se confirmó en la blockchain sin error.
        Reintenta hasta max_intentos veces con espera entre intentos.
        Devuelve False si no puede confirmar — NUNCA asume éxito.
        """
        session = await self._get_session()
        payload = {
            "jsonrpc": "2.0", "id": 1,
            "method":  "getTransaction",
            "params":  [tx_hash, {"encoding": "json", "maxSupportedTransactionVersion": 0}]
        }
        for intento in range(max_intentos):
            for rpc_url in SOLANA_RPC_URLS:
                try:
                    async with session.post(rpc_url, json=payload,
                                            timeout=aiohttp.ClientTimeout(total=15)) as r:
                        if r.status == 200:
                            data   = await r.json()
                            result = data.get("result")
                            if result:
                                err = result.get("meta", {}).get("err")
                                if err is None:
                                    log.info(f"✅ TX {tx_hash[:16]} confirmada on-chain (intento {intento+1})")
                                    return True
                                else:
                                    # Error definitivo on-chain (ej: error 6014 de Jupiter/Pump.fun)
                                    log.error(f"❌ TX {tx_hash[:16]} falló on-chain con error: {err}")
                                    return False
                            # result es None → TX aún pendiente, reintentar
                except Exception as e:
                    log.warning(f"Error verificando TX via {rpc_url[:35]}: {e}")

            if intento < max_intentos - 1:
                log.info(f"⏳ TX {tx_hash[:16]} aún pendiente, reintentando en {espera}s ({intento+1}/{max_intentos})...")
                await asyncio.sleep(espera)

        # Tras todos los intentos no se pudo leer → asumir fallida para no operar en falso
        log.error(f"❌ No se pudo confirmar TX {tx_hash[:16]} tras {max_intentos} intentos — abortando posición")
        return False

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

            # 1500 bps = 15% slippage para tokens Pump.fun (extremadamente volátiles)
            quote_entrada = await self.obtener_cotizacion(
                input_mint, output_mint, lamports, slippage_bps=1500
            )
            if not quote_entrada:
                resultado["estado"] = "sin_cotizacion"
                log.warning(f"Sin cotización para {token_mint[:8]}")
                return resultado

            tx_entrada = await self.ejecutar_swap(quote_entrada)
            if not tx_entrada:
                resultado["estado"] = "swap_fallido"
                return resultado

            # Esperar confirmación — Solana confirma en ~0.4s pero los RPCs públicos tardan más
            log.info(f"⏳ Esperando confirmación de TX {tx_entrada[:16]}...")
            await asyncio.sleep(12)
            tx_ok = await self.verificar_tx(tx_entrada, max_intentos=6, espera=5.0)

            if not tx_ok:
                log.warning(f"❌ TX {tx_entrada[:16]} falló on-chain — abortando")
                resultado["estado"]  = "tx_fallida_onchain"
                resultado["tx_hash"] = tx_entrada
                return resultado

            resultado["tx_hash"] = tx_entrada

            # Usar outAmount de la cotización como fallback, pero intentar leer el balance real
            tokens_obtenidos = int(quote_entrada.get("outAmount", 0))
            if accion == "compra" and tokens_obtenidos <= 0:
                log.error(f"❌ outAmount=0 en cotización para {token_mint[:8]} — abortando posición")
                resultado["estado"] = "sin_tokens_recibidos"
                return resultado

            log.info(f"✅ Posición abierta y confirmada | TX: {tx_entrada[:20]} | Tokens: {tokens_obtenidos}")

            # Monitorear posición
            max_segundos = max_minutos * 60
            sl_factor    = 1 - (stop_loss / 100)
            tp_factor    = 1 + (take_profit / 100)
            pnl          = 0.0

            while True:
                elapsed = (time.time() - inicio) / 60

                if int(elapsed) % 5 == 0 and elapsed > 0:
                    precio_sol = await self.obtener_precio_sol()

                quote_actual = await self.obtener_cotizacion(
                    token_mint, SOL_MINT, tokens_obtenidos, slippage_bps=1500
                )
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
                    log.warning("⚠️ Sin cotización al monitorear — reintentando en 30s")

                if (time.time() - inicio) >= max_segundos:
                    log.info(f"⏱️ Timeout {max_minutos}min alcanzado")
                    break

                await asyncio.sleep(30)

            # Cerrar posición con reintentos
            if accion == "compra" and tokens_obtenidos > 0:
                for intento_cierre in range(3):
                    quote_salida = await self.obtener_cotizacion(
                        token_mint, SOL_MINT, tokens_obtenidos, slippage_bps=1500
                    )
                    if quote_salida:
                        tx_salida = await self.ejecutar_swap(quote_salida)
                        if tx_salida:
                            await asyncio.sleep(12)
                            cierre_ok = await self.verificar_tx(tx_salida, max_intentos=6, espera=5.0)
                            if cierre_ok:
                                sol_final   = int(quote_salida.get("outAmount", 0)) / 1_000_000_000
                                valor_final = sol_final * precio_sol
                                pnl         = valor_final - monto_usd
                                log.info(f"{'✅' if pnl>=0 else '❌'} Posición cerrada | PnL: {'+' if pnl>=0 else ''}${pnl:.2f}")
                                break
                            else:
                                log.warning(f"TX cierre falló on-chain, reintentando {intento_cierre+1}/3...")
                    await asyncio.sleep(3)

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
