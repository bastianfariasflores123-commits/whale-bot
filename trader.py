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

    async def _verificar_bonding_curve(self, token_mint: str) -> bool:
        """
        Verifica si un token de Pump.fun aún está en bonding curve.
        Los tokens en bonding curve no se pueden comprar via Jupiter → error 6014.
        Retorna True si está en bonding curve (no comprar), False si ya salió.
        """
        try:
            session = await self._get_session()
            # Intentar obtener cotización pequeña — si Jupiter no tiene ruta, está en bonding curve
            params = {
                "inputMint":    SOL_MINT,
                "outputMint":   token_mint,
                "amount":       "1000000",  # 0.001 SOL
                "slippageBps":  "9900",
            }
            async with session.get(
                "https://public.jupiterapi.com/quote",
                params=params,
                timeout=aiohttp.ClientTimeout(total=5)
            ) as r:
                if r.status == 200:
                    data = await r.json()
                    if data and "outAmount" in data and int(data.get("outAmount", 0)) > 0:
                        return False  # Tiene ruta → ya salió de bonding curve
                # Sin ruta o error → probablemente en bonding curve
                return True
        except Exception as e:
            log.warning(f"No se pudo verificar bonding curve para {token_mint[:8]}: {e}")
            return False  # En caso de duda, intentar el swap

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
            "asLegacyTransaction": "false",
        }

        for quote_url in JUPITER_QUOTE_URLS:
            for intento in range(2):
                try:
                    async with session.get(
                        quote_url, params=params,
                        timeout=aiohttp.ClientTimeout(total=8)
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
                            timeout=aiohttp.ClientTimeout(total=10)
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

                if swap_data and "swapTransaction" in swap_data:
                    break

            if not swap_data or "swapTransaction" not in swap_data:
                log.error("❌ No se pudo obtener swapTransaction")
                return None

            tx_bytes  = base64.b64decode(swap_data["swapTransaction"])
            tx        = VersionedTransaction.from_bytes(tx_bytes)
            signed_tx = VersionedTransaction(tx.message, [self.keypair])

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

    async def verificar_tx(self, tx_hash: str, max_intentos: int = 6, espera: float = 5.0) -> bool:
        """
        Verifica si una TX realmente se confirmó en la blockchain sin error.
        Reintenta hasta max_intentos veces. NUNCA asume éxito si no puede confirmar.
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
                                    log.error(f"❌ TX {tx_hash[:16]} falló on-chain: {err}")
                                    return False
                            # result=None → TX aún pendiente, reintentar
                except Exception as e:
                    log.warning(f"Error verificando TX via {rpc_url[:35]}: {e}")

            if intento < max_intentos - 1:
                log.info(f"⏳ TX {tx_hash[:16]} pendiente, reintentando en {espera}s ({intento+1}/{max_intentos})...")
                await asyncio.sleep(espera)

        log.error(f"❌ No se pudo confirmar TX {tx_hash[:16]} tras {max_intentos} intentos — abortando")
        return False

    async def copiar_trade(self, token_mint: str, accion: str, monto_usd: float,
                           stop_loss: float, take_profit: float, max_minutos: float,
                           dex: str = "") -> dict:

        precio_sol = await self.obtener_precio_sol()
        sol_amount = monto_usd / precio_sol
        lamports   = int(sol_amount * 1_000_000_000)

        # Pump.fun: verificar si el token ya salió de bonding curve
        es_pump_fun = "pump" in dex.lower()
        if es_pump_fun:
            en_bonding = await self._verificar_bonding_curve(token_mint)
            if en_bonding:
                log.warning(f"⏭️ Token {token_mint[:8]} aún en bonding curve — saltando")
                resultado["estado"] = "bonding_curve"
                return resultado

        # Slippage progresivo: 50% → 75% → 99%
        slippages_a_intentar = [5000, 7500, 9900] if es_pump_fun else [1500, 3000, 5000]
        slippage_entrada = slippages_a_intentar[0]
        log.info(f"{'🟢' if accion == 'compra' else '🔴'} Copiando {accion} | Token: {token_mint[:8]} | ${monto_usd} | Slippage inicial: {slippage_entrada//100}%")

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

            # Reintentar con slippage progresivo si falla por error 6014
            tx_entrada   = None
            quote_entrada = None

            for slippage_intento in slippages_a_intentar:
                quote_entrada = await self.obtener_cotizacion(
                    input_mint, output_mint, lamports, slippage_bps=slippage_intento
                )
                if not quote_entrada:
                    continue

                tx_entrada = await self.ejecutar_swap(quote_entrada)
                if not tx_entrada:
                    continue

                log.info(f"⏳ Esperando confirmación TX {tx_entrada[:16]}... (slippage {slippage_intento//100}%)")
                await asyncio.sleep(12)
                tx_ok = await self.verificar_tx(tx_entrada)

                if tx_ok:
                    log.info(f"✅ TX confirmada con slippage {slippage_intento//100}%")
                    break
                else:
                    log.warning(f"❌ TX falló con slippage {slippage_intento//100}% — reintentando con más slippage...")
                    tx_entrada = None
                    await asyncio.sleep(2)

            if not tx_entrada:
                resultado["estado"]  = "tx_fallida_onchain"
                return resultado

            resultado["tx_hash"] = tx_entrada
            tokens_obtenidos     = int(quote_entrada.get("outAmount", 0))

            if tokens_obtenidos <= 0:
                log.error(f"❌ outAmount=0 para {token_mint[:8]} — abortando")
                resultado["estado"] = "sin_tokens_recibidos"
                return resultado

            log.info(f"✅ Posición abierta | TX: {tx_entrada[:20]} | Tokens: {tokens_obtenidos}")

            # ── Timer empieza AQUÍ, cuando la posición está realmente abierta ──
            inicio        = time.time()
            max_segundos  = max_minutos * 60
            sl_factor     = 1 - (stop_loss / 100)
            tp_factor     = 1 + (take_profit / 100)
            pnl           = 0.0
            razon_cierre  = "timeout"

            while True:
                # Chequear timeout AL INICIO del loop
                elapsed_seg = time.time() - inicio
                if elapsed_seg >= max_segundos:
                    log.info(f"⏱️ Timeout {max_minutos}min alcanzado")
                    razon_cierre = "timeout"
                    break

                elapsed_min = elapsed_seg / 60
                if elapsed_min > 0 and int(elapsed_min) % 5 == 0:
                    precio_sol = await self.obtener_precio_sol()

                quote_actual = await self.obtener_cotizacion(
                    token_mint, SOL_MINT, tokens_obtenidos, slippage_bps=slippage_entrada
                )
                if quote_actual:
                    valor_sol = int(quote_actual.get("outAmount", 0)) / 1_000_000_000
                    valor_usd = valor_sol * precio_sol
                    pnl       = valor_usd - monto_usd
                    cambio    = valor_usd / monto_usd if monto_usd else 1

                    log.info(f"📊 Posición: ${valor_usd:.2f} | PnL: {'+' if pnl>=0 else ''}{pnl:.2f} | {elapsed_min:.1f}min")

                    if cambio >= tp_factor:
                        log.info(f"🎯 Take Profit {take_profit}% alcanzado")
                        razon_cierre = "take_profit"
                        break
                    if cambio <= sl_factor:
                        log.info(f"🛑 Stop Loss {stop_loss}% activado")
                        razon_cierre = "stop_loss"
                        break
                else:
                    log.warning("⚠️ Sin cotización al monitorear — reintentando en 30s")

                await asyncio.sleep(30)

            # ── Cerrar posición con reintentos ──
            pnl_real = pnl
            if accion == "compra" and tokens_obtenidos > 0:
                for intento_cierre in range(3):
                    quote_salida = await self.obtener_cotizacion(
                        token_mint, SOL_MINT, tokens_obtenidos, slippage_bps=slippage_entrada
                    )
                    if quote_salida:
                        tx_salida = await self.ejecutar_swap(quote_salida)
                        if tx_salida:
                            await asyncio.sleep(12)
                            cierre_ok = await self.verificar_tx(tx_salida)
                            if cierre_ok:
                                sol_final   = int(quote_salida.get("outAmount", 0)) / 1_000_000_000
                                precio_sol  = await self.obtener_precio_sol()
                                valor_final = sol_final * precio_sol
                                pnl_real    = valor_final - monto_usd
                                log.info(f"{'✅' if pnl_real>=0 else '❌'} Posición cerrada ({razon_cierre}) | PnL real: {'+' if pnl_real>=0 else ''}${pnl_real:.2f}")
                                break
                            else:
                                log.warning(f"TX cierre falló on-chain, reintentando {intento_cierre+1}/3...")
                    await asyncio.sleep(3)

            duracion = round((time.time() - inicio) / 60, 1)
            resultado.update({
                "pnl_usd":      round(pnl_real, 4),
                "duracion_min": duracion,
                "estado":       "cerrado",
                "razon_cierre": razon_cierre,
            })

        except Exception as e:
            log.error(f"Error en copiar_trade: {e}")
            resultado["estado"] = f"error: {str(e)[:80]}"

        return resultado

    async def cerrar(self):
        if self.session and not self.session.closed:
            await self.session.close()
