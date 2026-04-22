"""
trader.py — Ejecuta swaps REALES en Solana
- Tokens Pump.fun → API nativa de Pump.fun (evita error 6014)
- Otros tokens → Jupiter Aggregator
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
]
JUPITER_SWAP_URLS = [
    "https://public.jupiterapi.com/swap",
    "https://quote-api.jup.ag/v6/swap",
]
SOLANA_RPC_URLS = [
    "https://api.mainnet-beta.solana.com",
    "https://endpoints.omniatech.io/v1/sol/mainnet/public",
    "https://rpc.ankr.com/solana",
]

# Pump.fun API
PUMP_FUN_API    = "https://pumpportal.fun/api/trade-local"
PUMP_FUN_PORTAL = "https://frontend-api.pump.fun"

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
            elif len(key_bytes) == 32:
                self.keypair    = Keypair.from_seed(key_bytes)
            else:
                raise ValueError(f"Longitud inválida: {len(key_bytes)}")
            self.pubkey_str = str(self.keypair.pubkey())
            log.info(f"✅ Wallet cargada: {self.pubkey_str[:12]}...")
        except Exception as e:
            log.error(f"❌ No se pudo cargar keypair: {e}")
            self.keypair = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session

    def esta_listo(self) -> bool:
        return self.keypair is not None

    # ── PRECIO SOL ────────────────────────────────────────────────────────────

    async def obtener_precio_sol(self) -> float:
        session = await self._get_session()
        for url, key in [
            ("https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd",
             lambda d: d.get("solana", {}).get("usd", 0)),
            ("https://api.binance.com/api/v3/ticker/price?symbol=SOLUSDT",
             lambda d: float(d.get("price", 0))),
        ]:
            try:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as r:
                    if r.status == 200:
                        p = key(await r.json())
                        if p > 0:
                            log.info(f"💲 Precio SOL: ${p}")
                            return float(p)
            except Exception:
                pass
        return SOL_PRECIO_USD

    # ── PUMP.FUN NATIVO ───────────────────────────────────────────────────────

    async def _swap_pump_fun(self, token_mint: str, accion: str,
                              monto_sol: float) -> Optional[str]:
        """
        Usa la API nativa de Pump.fun para comprar/vender tokens en bonding curve.
        Esto evita completamente el error 6014 de Jupiter.
        """
        if not self.keypair:
            return None

        session = await self._get_session()

        try:
            from solders.transaction import VersionedTransaction

            # 1. Obtener TX de Pump.fun
            payload = {
                "publicKey":  self.pubkey_str,
                "action":     "buy" if accion == "compra" else "sell",
                "mint":       token_mint,
                "amount":     monto_sol if accion == "compra" else "100%",
                "denominatedInSol": "true" if accion == "compra" else "false",
                "slippage":   50,
                "priorityFee": 0.005,
                "pool":       "pump",
            }

            log.info(f"🎯 Usando Pump.fun API nativa para {accion} de {token_mint[:8]}")

            async with session.post(
                PUMP_FUN_API, data=payload,
                timeout=aiohttp.ClientTimeout(total=15)
            ) as r:
                if r.status != 200:
                    log.warning(f"Pump.fun API status {r.status} — fallback a Jupiter")
                    return None
                tx_bytes = await r.read()

            if not tx_bytes or len(tx_bytes) < 100:
                log.warning("Pump.fun retornó TX vacía — fallback a Jupiter")
                return None

            # 2. Firmar y enviar
            tx        = VersionedTransaction.from_bytes(tx_bytes)
            signed_tx = VersionedTransaction(tx.message, [self.keypair])

            for rpc_url in SOLANA_RPC_URLS:
                try:
                    rpc_payload = {
                        "jsonrpc": "2.0", "id": 1,
                        "method":  "sendTransaction",
                        "params":  [
                            base64.b64encode(bytes(signed_tx)).decode("utf-8"),
                            {"encoding": "base64", "skipPreflight": False,
                             "preflightCommitment": "confirmed"}
                        ]
                    }
                    async with session.post(
                        rpc_url, json=rpc_payload,
                        timeout=aiohttp.ClientTimeout(total=15)
                    ) as r2:
                        if r2.status == 200:
                            data = await r2.json()
                            tx_hash = data.get("result")
                            if tx_hash:
                                log.info(f"✅ Pump.fun TX enviada: {tx_hash[:20]}...")
                                return tx_hash
                            err = data.get("error", {})
                            log.warning(f"RPC rechazó TX: {err}")
                except Exception as e:
                    log.warning(f"RPC {rpc_url[:30]} error: {e}")

        except Exception as e:
            log.error(f"Error en Pump.fun swap: {e}")

        return None

    # ── JUPITER ───────────────────────────────────────────────────────────────

    async def obtener_cotizacion(self, input_mint: str, output_mint: str,
                                  monto_lamports: int, slippage_bps: int = 1500) -> Optional[dict]:
        session = await self._get_session()
        params  = {
            "inputMint": input_mint, "outputMint": output_mint,
            "amount": str(monto_lamports), "slippageBps": str(slippage_bps),
            "onlyDirectRoutes": "false",
        }
        for url in JUPITER_QUOTE_URLS:
            try:
                async with session.get(url, params=params,
                                       timeout=aiohttp.ClientTimeout(total=8)) as r:
                    if r.status == 200:
                        data = await r.json()
                        if data and "outAmount" in data:
                            log.info(f"✅ Cotización Jupiter: {url[:35]}")
                            return data
            except Exception as e:
                log.warning(f"Jupiter quote {url[:35]}: {e}")
        return None

    async def ejecutar_swap_jupiter(self, quote_response: dict) -> Optional[str]:
        if not self.keypair:
            return None
        try:
            from solders.transaction import VersionedTransaction
            session = await self._get_session()
            payload = {
                "quoteResponse": quote_response,
                "userPublicKey": self.pubkey_str,
                "wrapAndUnwrapSol": True,
                "dynamicComputeUnitLimit": True,
                "prioritizationFeeLamports": 50000,
            }
            swap_data = None
            for url in JUPITER_SWAP_URLS:
                try:
                    async with session.post(url, json=payload,
                                            timeout=aiohttp.ClientTimeout(total=10)) as r:
                        if r.status == 200:
                            d = await r.json()
                            if "swapTransaction" in d:
                                swap_data = d
                                log.info(f"✅ SwapTX Jupiter: {url[:35]}")
                                break
                except Exception as e:
                    log.warning(f"Jupiter swap {url[:35]}: {e}")

            if not swap_data:
                return None

            tx_bytes  = base64.b64decode(swap_data["swapTransaction"])
            tx        = VersionedTransaction.from_bytes(tx_bytes)
            signed_tx = VersionedTransaction(tx.message, [self.keypair])

            for rpc_url in SOLANA_RPC_URLS:
                try:
                    async with session.post(
                        rpc_url,
                        json={
                            "jsonrpc": "2.0", "id": 1,
                            "method": "sendTransaction",
                            "params": [
                                base64.b64encode(bytes(signed_tx)).decode("utf-8"),
                                {"encoding": "base64", "skipPreflight": False,
                                 "preflightCommitment": "confirmed"}
                            ]
                        },
                        timeout=aiohttp.ClientTimeout(total=15)
                    ) as r:
                        if r.status == 200:
                            data    = await r.json()
                            tx_hash = data.get("result")
                            if tx_hash:
                                log.info(f"✅ Jupiter TX enviada: {tx_hash[:20]}...")
                                return tx_hash
                except Exception as e:
                    log.warning(f"RPC {rpc_url[:30]}: {e}")
        except Exception as e:
            log.error(f"Error Jupiter swap: {e}")
        return None

    # ── VERIFICAR TX ──────────────────────────────────────────────────────────

    async def verificar_tx(self, tx_hash: str, max_intentos: int = 8,
                            espera: float = 4.0) -> bool:
        session = await self._get_session()
        payload = {
            "jsonrpc": "2.0", "id": 1,
            "method":  "getTransaction",
            "params":  [tx_hash, {"encoding": "json",
                                   "maxSupportedTransactionVersion": 0}]
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
                                    log.info(f"✅ TX confirmada: {tx_hash[:16]}")
                                    return True
                                log.error(f"❌ TX falló on-chain: {err}")
                                return False
                except Exception as e:
                    log.warning(f"Verificar TX {rpc_url[:30]}: {e}")

            if intento < max_intentos - 1:
                log.info(f"⏳ TX pendiente, esperando {espera}s ({intento+1}/{max_intentos})...")
                await asyncio.sleep(espera)

        log.error(f"❌ TX no confirmada tras {max_intentos} intentos")
        return False

    # ── COPIAR TRADE ──────────────────────────────────────────────────────────

    async def copiar_trade(self, token_mint: str, accion: str, monto_usd: float,
                           stop_loss: float, take_profit: float, max_minutos: float,
                           dex: str = "") -> dict:

        precio_sol = await self.obtener_precio_sol()
        sol_amount = monto_usd / precio_sol
        lamports   = int(sol_amount * 1_000_000_000)
        es_pump    = "pump" in dex.lower()

        log.info(f"{'🟢' if accion == 'compra' else '🔴'} {accion.upper()} | "
                 f"Token: {token_mint[:8]} | ${monto_usd} | DEX: {dex}")

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
            tx_entrada      = None
            quote_entrada   = None
            tokens_obtenidos = 0

            # ── Intentar compra ───────────────────────────────────────────────
            if es_pump:
                # Pump.fun: API nativa primero, Jupiter como fallback
                tx_entrada = await self._swap_pump_fun(token_mint, accion, sol_amount)

                if tx_entrada:
                    await asyncio.sleep(8)
                    tx_ok = await self.verificar_tx(tx_entrada)
                    if not tx_ok:
                        log.warning("Pump.fun TX falló — intentando Jupiter")
                        tx_entrada = None

                if not tx_entrada:
                    # Fallback: Jupiter con slippage alto
                    for slippage in [5000, 7500, 9900]:
                        input_m  = SOL_MINT   if accion == "compra" else token_mint
                        output_m = token_mint if accion == "compra" else SOL_MINT
                        quote_entrada = await self.obtener_cotizacion(
                            input_m, output_m, lamports, slippage_bps=slippage
                        )
                        if not quote_entrada:
                            continue
                        tx_entrada = await self.ejecutar_swap_jupiter(quote_entrada)
                        if not tx_entrada:
                            continue
                        await asyncio.sleep(8)
                        if await self.verificar_tx(tx_entrada):
                            log.info(f"✅ Jupiter fallback exitoso (slippage {slippage//100}%)")
                            tokens_obtenidos = int(quote_entrada.get("outAmount", 0))
                            break
                        log.warning(f"Jupiter slippage {slippage//100}% falló — siguiente...")
                        tx_entrada = None
                        await asyncio.sleep(2)
            else:
                # Raydium/Orca/Jupiter: directo
                input_m  = SOL_MINT   if accion == "compra" else token_mint
                output_m = token_mint if accion == "compra" else SOL_MINT
                for slippage in [1500, 3000, 5000]:
                    quote_entrada = await self.obtener_cotizacion(
                        input_m, output_m, lamports, slippage_bps=slippage
                    )
                    if not quote_entrada:
                        continue
                    tx_entrada = await self.ejecutar_swap_jupiter(quote_entrada)
                    if not tx_entrada:
                        continue
                    await asyncio.sleep(8)
                    if await self.verificar_tx(tx_entrada):
                        tokens_obtenidos = int(quote_entrada.get("outAmount", 0))
                        break
                    tx_entrada = None
                    await asyncio.sleep(2)

            if not tx_entrada:
                resultado["estado"] = "tx_fallida_onchain"
                return resultado

            resultado["tx_hash"] = tx_entrada

            # Para Pump.fun sin cotización de Jupiter, estimar tokens basado en SOL
            # Usamos lamports directamente como cantidad mínima para las cotizaciones
            if es_pump and tokens_obtenidos == 0:
                # No estimamos tokens — usaremos un query de "sell 100%" vía Pump.fun
                # Seteamos un valor alto para que Jupiter intente cotizar
                tokens_obtenidos = lamports * 100  # estimación conservadora

            log.info(f"✅ Posición abierta | TX: {tx_entrada[:20]}")

            # ── Monitorear posición ───────────────────────────────────────────
            inicio        = time.time()
            max_segundos  = max_minutos * 60
            sl_factor     = 1 - (stop_loss / 100)
            tp_factor     = 1 + (take_profit / 100)
            pnl           = 0.0
            razon_cierre  = "timeout"
            fallos_cotizacion = 0  # contador de fallos consecutivos
            MIN_HOLD_SEGUNDOS = 120  # esperar al menos 2 min antes de permitir stop loss

            while (time.time() - inicio) < max_segundos:
                elapsed_min = (time.time() - inicio) / 60

                # Actualizar precio SOL cada 5 min
                if int(elapsed_min) % 5 == 0 and elapsed_min > 0:
                    precio_sol = await self.obtener_precio_sol()

                quote_actual = await self.obtener_cotizacion(
                    token_mint, SOL_MINT,
                    max(tokens_obtenidos, 1000),
                    slippage_bps=9900
                )
                if quote_actual:
                    valor_sol = int(quote_actual.get("outAmount", 0)) / 1_000_000_000
                    valor_usd = valor_sol * precio_sol

                    # PROTECCIÓN: si la cotización devuelve 0 o un valor absurdo,
                    # ignorar esta iteración — no cerrar por datos erróneos de la API
                    if valor_usd < monto_usd * 0.01:
                        fallos_cotizacion += 1
                        log.warning(f"⚠️ Cotización sospechosa (${valor_usd:.4f}), fallo #{fallos_cotizacion}, ignorando...")
                        # Si falla 5 veces seguidas, cerrar por seguridad
                        if fallos_cotizacion >= 5:
                            razon_cierre = "error_cotizacion"
                            log.error("❌ 5 fallos consecutivos de cotización — cerrando posición")
                            break
                        await asyncio.sleep(30)
                        continue

                    fallos_cotizacion = 0  # resetear contador en cotización válida
                    pnl    = valor_usd - monto_usd
                    cambio = valor_usd / monto_usd
                    elapsed_seg = time.time() - inicio

                    log.info(f"📊 ${valor_usd:.2f} | PnL: {'+' if pnl>=0 else ''}{pnl:.2f} | {elapsed_min:.1f}min")

                    if cambio >= tp_factor:
                        razon_cierre = "take_profit"
                        log.info(f"🎯 Take Profit {take_profit}%!")
                        break
                    # Stop loss solo se activa tras el tiempo mínimo de hold
                    if cambio <= sl_factor and elapsed_seg >= MIN_HOLD_SEGUNDOS:
                        razon_cierre = "stop_loss"
                        log.info(f"🛑 Stop Loss {stop_loss}%!")
                        break
                    elif cambio <= sl_factor:
                        log.info(f"⏳ En stop loss pero esperando min hold ({elapsed_seg:.0f}s/{MIN_HOLD_SEGUNDOS}s)...")
                else:
                    # API no respondió — esperar sin tomar decisión
                    fallos_cotizacion += 1
                    log.warning(f"⚠️ Sin cotización en este ciclo (fallo #{fallos_cotizacion}), esperando...")
                    if fallos_cotizacion >= 5:
                        razon_cierre = "error_cotizacion"
                        log.error("❌ 5 fallos consecutivos de cotización — cerrando posición")
                        break

                await asyncio.sleep(30)

            # ── Cerrar posición ───────────────────────────────────────────────
            pnl_real = pnl
            if accion == "compra":
                tx_cierre = None

                if es_pump:
                    tx_cierre = await self._swap_pump_fun(token_mint, "venta", sol_amount)
                    if tx_cierre:
                        await asyncio.sleep(8)
                        if not await self.verificar_tx(tx_cierre):
                            tx_cierre = None

                if not tx_cierre:
                    for slippage in [5000, 7500, 9900]:
                        q = await self.obtener_cotizacion(
                            token_mint, SOL_MINT,
                            max(tokens_obtenidos, 1000),
                            slippage_bps=slippage
                        )
                        if not q:
                            continue
                        tx_cierre = await self.ejecutar_swap_jupiter(q)
                        if not tx_cierre:
                            continue
                        await asyncio.sleep(8)
                        if await self.verificar_tx(tx_cierre):
                            sol_final  = int(q.get("outAmount", 0)) / 1_000_000_000
                            pnl_real   = (sol_final * precio_sol) - monto_usd
                            log.info(f"{'✅' if pnl_real>=0 else '❌'} Cerrado ({razon_cierre}) | PnL: {'+' if pnl_real>=0 else ''}${pnl_real:.2f}")
                            break
                        tx_cierre = None
                        await asyncio.sleep(2)

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
