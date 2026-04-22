"""
database.py — Almacenamiento local con SQLite (sin servidor, sin costo)
Guarda: wallets seguidas, trades ejecutados, configuración del bot
Las wallets Y las TXs procesadas se respaldan en variables de entorno
para sobrevivir los reinicios de Railway (la DB en /tmp se borra)
"""

import sqlite3
import logging
import os
import json
from datetime import datetime
from typing import Optional

log = logging.getLogger(__name__)

DB_PATH = os.getenv("DB_PATH", "/tmp/whale_bot.db")


class Database:
    def __init__(self, path: str = DB_PATH):
        self.path = path
        self._inicializar()
        self._restaurar_wallets_desde_env()
        self._restaurar_txs_desde_env()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _inicializar(self):
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS wallets (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    address   TEXT    UNIQUE NOT NULL,
                    activa    INTEGER DEFAULT 1,
                    creada_en TEXT    DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS trades (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    token       TEXT,
                    token_mint  TEXT,
                    accion      TEXT,
                    invertido   REAL,
                    pnl_usd     REAL,
                    duracion    REAL,
                    estado      TEXT,
                    tx_hash     TEXT,
                    fecha       TEXT DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS txs_procesadas (
                    signature TEXT PRIMARY KEY,
                    fecha     TEXT DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS config (
                    clave TEXT PRIMARY KEY,
                    valor TEXT NOT NULL
                );
            """)

            defaults = {
                "monto_usd":       "5",
                "stop_loss_pct":   "8",
                "take_profit_pct": "25",
                "max_minutos":     "45",
            }
            for clave, valor in defaults.items():
                conn.execute(
                    "INSERT OR IGNORE INTO config (clave, valor) VALUES (?, ?)",
                    (clave, valor)
                )
        log.info(f"Base de datos inicializada en {self.path}")

    # ── RESPALDO DE WALLETS ───────────────────────────────────────────────────

    def _restaurar_wallets_desde_env(self):
        if self.obtener_wallets():
            return
        backup = os.getenv("WALLETS_BACKUP", "")
        if not backup:
            return
        try:
            wallets = json.loads(backup)
            for address in wallets:
                self.agregar_wallet(address)
            log.info(f"✅ {len(wallets)} wallets restauradas desde WALLETS_BACKUP")
        except Exception as e:
            log.warning(f"No se pudo restaurar wallets desde env: {e}")

    def _guardar_wallets_en_env(self):
        try:
            wallets = [w["address"] for w in self.obtener_wallets()]
            os.environ["WALLETS_BACKUP"] = json.dumps(wallets)
            log.info(f"Wallets respaldadas en memoria: {len(wallets)}")
        except Exception as e:
            log.warning(f"Error respaldando wallets: {e}")

    # ── RESPALDO DE TXS PROCESADAS ────────────────────────────────────────────

    def _restaurar_txs_desde_env(self):
        """
        Restaura las últimas TXs procesadas desde TXS_BACKUP.
        Esto evita reprocesar la misma TX tras un reinicio de Railway.
        Solo guardamos las últimas 200 para no crecer indefinidamente.
        """
        backup = os.getenv("TXS_BACKUP", "")
        if not backup:
            return
        try:
            sigs = json.loads(backup)
            with self._conn() as conn:
                for sig in sigs:
                    conn.execute(
                        "INSERT OR IGNORE INTO txs_procesadas (signature) VALUES (?)", (sig,)
                    )
            log.info(f"✅ {len(sigs)} TXs procesadas restauradas desde TXS_BACKUP")
        except Exception as e:
            log.warning(f"No se pudo restaurar TXs desde env: {e}")

    def _guardar_txs_en_env(self):
        """Guarda las últimas 200 TXs procesadas en memoria."""
        try:
            with self._conn() as conn:
                rows = conn.execute(
                    "SELECT signature FROM txs_procesadas ORDER BY fecha DESC LIMIT 200"
                ).fetchall()
            sigs = [r["signature"] for r in rows]
            os.environ["TXS_BACKUP"] = json.dumps(sigs)
        except Exception as e:
            log.warning(f"Error respaldando TXs: {e}")

    # ── WALLETS ───────────────────────────────────────────────────────────────

    def agregar_wallet(self, address: str):
        with self._conn() as conn:
            conn.execute("INSERT OR IGNORE INTO wallets (address) VALUES (?)", (address,))
        self._guardar_wallets_en_env()

    def quitar_wallet(self, address: str) -> bool:
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM wallets WHERE address = ?", (address,))
            deleted = cur.rowcount > 0
        if deleted:
            self._guardar_wallets_en_env()
        return deleted

    def wallet_existe(self, address: str) -> bool:
        with self._conn() as conn:
            row = conn.execute("SELECT id FROM wallets WHERE address = ?", (address,)).fetchone()
            return row is not None

    def obtener_wallets(self, solo_activas: bool = False) -> list:
        with self._conn() as conn:
            query = "SELECT * FROM wallets"
            if solo_activas:
                query += " WHERE activa = 1"
            rows = conn.execute(query).fetchall()
            return [dict(r) for r in rows]

    # ── TRANSACCIONES PROCESADAS ──────────────────────────────────────────────

    def tx_procesada(self, signature: str) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT signature FROM txs_procesadas WHERE signature = ?", (signature,)
            ).fetchone()
            return row is not None

    def marcar_tx(self, signature: str):
        with self._conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO txs_procesadas (signature) VALUES (?)", (signature,)
            )
        # Guardar en env para que sobreviva reinicios
        self._guardar_txs_en_env()

    # ── TRADES ────────────────────────────────────────────────────────────────

    def registrar_trade(self, resultado: dict):
        with self._conn() as conn:
            conn.execute("""
                INSERT INTO trades (token, token_mint, accion, invertido, pnl_usd, duracion, estado, tx_hash)
                VALUES (:token, :token_mint, :accion, :invertido, :pnl_usd, :duracion_min, :estado, :tx_hash)
            """, resultado)

    def _stats_vacio(self) -> dict:
        return {
            "total_trades": 0, "ganados": 0, "perdidos": 0,
            "win_rate": 0.0, "pnl_total": 0.0,
            "mejor_trade": 0.0, "peor_trade": 0.0,
            "promedio_trade": 0.0, "trades": [],
        }

    def obtener_estadisticas(self) -> dict:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT pnl_usd FROM trades WHERE estado = 'cerrado'"
            ).fetchall()
            pnls = [r["pnl_usd"] for r in rows]
            if not pnls:
                return self._stats_vacio()
            ganados  = sum(1 for p in pnls if p > 0)
            perdidos = sum(1 for p in pnls if p <= 0)
            return {
                "total_trades": len(pnls),
                "ganados":      ganados,
                "perdidos":     perdidos,
                "win_rate":     (ganados / len(pnls)) * 100,
                "pnl_total":    round(sum(pnls), 4),
                "mejor_trade":  round(max(pnls), 4),
                "peor_trade":   round(min(pnls), 4),
            }

    def obtener_estadisticas_periodo(self, dias: int) -> dict:
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT pnl_usd, fecha, token, accion, invertido
                FROM trades
                WHERE estado = 'cerrado'
                AND fecha >= datetime('now', ?)
                ORDER BY fecha DESC
            """, (f'-{dias} days',)).fetchall()

            if not rows:
                return self._stats_vacio()

            pnls     = [r["pnl_usd"] for r in rows]
            ganados  = sum(1 for p in pnls if p > 0)
            perdidos = sum(1 for p in pnls if p <= 0)

            return {
                "total_trades":   len(pnls),
                "ganados":        ganados,
                "perdidos":       perdidos,
                "win_rate":       round((ganados / len(pnls)) * 100, 1),
                "pnl_total":      round(sum(pnls), 2),
                "mejor_trade":    round(max(pnls), 2),
                "peor_trade":     round(min(pnls), 2),
                "promedio_trade": round(sum(pnls) / len(pnls), 2),
                "trades":         [dict(r) for r in rows],
            }

    def obtener_resumen_semanal(self) -> dict:
        semana_actual   = self.obtener_estadisticas_periodo(7)
        semana_anterior = self.obtener_estadisticas_periodo(14)
        pnl_anterior    = semana_anterior["pnl_total"] - semana_actual["pnl_total"]

        if pnl_anterior != 0:
            variacion = ((semana_actual["pnl_total"] - pnl_anterior) / abs(pnl_anterior)) * 100
        else:
            variacion = 100.0 if semana_actual["pnl_total"] > 0 else 0.0

        trades_semana    = semana_actual.get("trades", [])
        ganancias_por_dia = {}
        for t in trades_semana:
            fecha = t["fecha"][:10]
            ganancias_por_dia[fecha] = ganancias_por_dia.get(fecha, 0) + t["pnl_usd"]

        mejor_dia = max(ganancias_por_dia.items(), key=lambda x: x[1]) if ganancias_por_dia else (None, 0)
        peor_dia  = min(ganancias_por_dia.items(), key=lambda x: x[1]) if ganancias_por_dia else (None, 0)

        return {
            **semana_actual,
            "pnl_semana_anterior": round(pnl_anterior, 2),
            "variacion_pct":       round(variacion, 1),
            "mejor_dia":           mejor_dia,
            "peor_dia":            peor_dia,
            "ganancias_por_dia":   ganancias_por_dia,
            "promedio_diario":     round(semana_actual["pnl_total"] / 7, 2),
        }

    def obtener_resumen_mensual(self) -> dict:
        mes_actual = self.obtener_estadisticas_periodo(30)
        with self._conn() as conn:
            primer_trade = conn.execute(
                "SELECT MIN(fecha) as primera FROM trades WHERE estado = 'cerrado'"
            ).fetchone()

        if primer_trade and primer_trade["primera"]:
            primera_fecha = datetime.fromisoformat(primer_trade["primera"])
            dias_activo   = max((datetime.now() - primera_fecha).days, 1)
            dias_activo   = min(dias_activo, 30)
        else:
            dias_activo = 1

        promedio_diario = mes_actual["pnl_total"] / dias_activo if dias_activo else 0
        proyeccion_mes  = promedio_diario * 30
        dias_para_meta  = 100 / promedio_diario if promedio_diario > 0 else 0

        return {
            **mes_actual,
            "dias_activo":     dias_activo,
            "promedio_diario": round(promedio_diario, 2),
            "proyeccion_mes":  round(proyeccion_mes, 2),
            "dias_para_meta":  round(dias_para_meta, 1),
        }

    # ── CONFIGURACIÓN ─────────────────────────────────────────────────────────

    def obtener_config(self) -> dict:
        with self._conn() as conn:
            rows = conn.execute("SELECT clave, valor FROM config").fetchall()
            return {r["clave"]: float(r["valor"]) for r in rows}

    def actualizar_config(self, clave: str, valor: float):
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO config (clave, valor) VALUES (?, ?)",
                (clave, str(valor))
            )
