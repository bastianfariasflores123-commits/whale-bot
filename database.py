"""
database.py — Almacenamiento local con SQLite (sin servidor, sin costo)
Guarda: wallets seguidas, trades ejecutados, configuración del bot
"""

import sqlite3
import logging
from datetime import datetime
from typing import Optional

log = logging.getLogger(__name__)

DB_PATH = "whale_bot.db"


class Database:
    def __init__(self, path: str = DB_PATH):
        self.path = path
        self._inicializar()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _inicializar(self):
        """Crea las tablas si no existen."""
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

            # Configuración por defecto
            defaults = {
                "monto_usd":       "10",
                "stop_loss_pct":   "10",
                "take_profit_pct": "20",
                "max_minutos":     "60",
            }
            for clave, valor in defaults.items():
                conn.execute(
                    "INSERT OR IGNORE INTO config (clave, valor) VALUES (?, ?)",
                    (clave, valor)
                )
        log.info("Base de datos inicializada")

    # ── WALLETS ──────────────────────────────────────────────────────────────

    def agregar_wallet(self, address: str):
        with self._conn() as conn:
            conn.execute("INSERT OR IGNORE INTO wallets (address) VALUES (?)", (address,))

    def quitar_wallet(self, address: str) -> bool:
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM wallets WHERE address = ?", (address,))
            return cur.rowcount > 0

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

    # ── TRANSACCIONES PROCESADAS ─────────────────────────────────────────────

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

    # ── TRADES ───────────────────────────────────────────────────────────────

    def registrar_trade(self, resultado: dict):
        with self._conn() as conn:
            conn.execute("""
                INSERT INTO trades (token, token_mint, accion, invertido, pnl_usd, duracion, estado, tx_hash)
                VALUES (:token, :token_mint, :accion, :invertido, :pnl_usd, :duracion_min, :estado, :tx_hash)
            """, resultado)

    def obtener_estadisticas(self) -> dict:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT pnl_usd FROM trades WHERE estado = 'cerrado'"
            ).fetchall()

            pnls = [r["pnl_usd"] for r in rows]

            if not pnls:
                return {
                    "total_trades": 0, "ganados": 0, "perdidos": 0,
                    "win_rate": 0.0, "pnl_total": 0.0,
                    "mejor_trade": 0.0, "peor_trade": 0.0,
                }

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
        """Obtiene estadísticas de los últimos N días."""
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
                "total_trades":  len(pnls),
                "ganados":       ganados,
                "perdidos":      perdidos,
                "win_rate":      round((ganados / len(pnls)) * 100, 1) if pnls else 0,
                "pnl_total":     round(sum(pnls), 2),
                "mejor_trade":   round(max(pnls), 2),
                "peor_trade":    round(min(pnls), 2),
                "promedio_trade": round(sum(pnls) / len(pnls), 2),
                "trades":        [dict(r) for r in rows],
            }

    def obtener_resumen_semanal(self) -> dict:
        """Resumen detallado de la semana actual y comparación con la anterior."""
        semana_actual   = self.obtener_estadisticas_periodo(7)
        semana_anterior = self.obtener_estadisticas_periodo(14)

        # PnL de la semana anterior solamente
        pnl_anterior = semana_anterior["pnl_total"] - semana_actual["pnl_total"]

        # Variación porcentual
        if pnl_anterior != 0:
            variacion = ((semana_actual["pnl_total"] - pnl_anterior) / abs(pnl_anterior)) * 100
        else:
            variacion = 100.0 if semana_actual["pnl_total"] > 0 else 0.0

        # Mejor día de la semana
        trades_semana = semana_actual.get("trades", [])
        ganancias_por_dia = {}
        for t in trades_semana:
            fecha = t["fecha"][:10]  # solo YYYY-MM-DD
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
        """Resumen del mes actual con proyección al cierre."""
        mes_actual = self.obtener_estadisticas_periodo(30)

        # Días transcurridos del mes (aproximado)
        with self._conn() as conn:
            primer_trade = conn.execute(
                "SELECT MIN(fecha) as primera FROM trades WHERE estado = 'cerrado'"
            ).fetchone()

        if primer_trade and primer_trade["primera"]:
            from datetime import datetime
            primera_fecha = datetime.fromisoformat(primer_trade["primera"])
            dias_activo   = max((datetime.now() - primera_fecha).days, 1)
            dias_activo   = min(dias_activo, 30)
        else:
            dias_activo = 1

        promedio_diario   = mes_actual["pnl_total"] / dias_activo if dias_activo else 0
        proyeccion_mes    = promedio_diario * 30
        dias_para_meta    = 100 / promedio_diario if promedio_diario > 0 else 0

        return {
            **mes_actual,
            "dias_activo":      dias_activo,
            "promedio_diario":  round(promedio_diario, 2),
            "proyeccion_mes":   round(proyeccion_mes, 2),
            "dias_para_meta":   round(dias_para_meta, 1),
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

    def _stats_vacio(self) -> dict:
        return {
            "total_trades": 0, "ganados": 0, "perdidos": 0,
            "win_rate": 0.0, "pnl_total": 0.0,
            "mejor_trade": 0.0, "peor_trade": 0.0,
            "promedio_trade": 0.0, "trades": [],
        }

    # ── CONFIGURACIÓN ────────────────────────────────────────────────────────

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
