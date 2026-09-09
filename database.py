# database.py
"""
SQLite persistence layer for trading bot state.
All state survives restarts. Provides CRUD for positions, orders, trades,
daily metrics, and incidents.
"""
import sqlite3
import json
import logging
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional
from decimal import Decimal
from contextlib import contextmanager

logger = logging.getLogger(__name__)


class Database:
    """SQLite database for persistent bot state."""

    def __init__(self, db_path: str = 'trading_bot.db'):
        self.db_path = db_path
        self._init_db()

    @contextmanager
    def _get_conn(self):
        """Thread-safe connection context manager."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self):
        """Create all tables if they don't exist."""
        with self._get_conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS positions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    entry_price TEXT NOT NULL,
                    quantity TEXT NOT NULL,
                    entry_time TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'OPEN',
                    exit_price TEXT,
                    exit_time TEXT,
                    pnl TEXT,
                    oco_order_list_id TEXT,
                    stop_loss TEXT,
                    take_profit TEXT,
                    regime TEXT,
                    confidence REAL,
                    reasons TEXT,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    position_id INTEGER,
                    order_id TEXT NOT NULL,
                    client_order_id TEXT,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    order_type TEXT NOT NULL,
                    quantity TEXT NOT NULL,
                    price TEXT,
                    status TEXT NOT NULL,
                    filled_qty TEXT DEFAULT '0',
                    avg_price TEXT DEFAULT '0',
                    commission TEXT DEFAULT '0',
                    raw_response TEXT,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                    FOREIGN KEY (position_id) REFERENCES positions(id)
                );

                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    position_id INTEGER,
                    order_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    price TEXT NOT NULL,
                    quantity TEXT NOT NULL,
                    commission TEXT DEFAULT '0',
                    commission_asset TEXT DEFAULT '',
                    realized_pnl TEXT DEFAULT '0',
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    FOREIGN KEY (position_id) REFERENCES positions(id)
                );

                CREATE TABLE IF NOT EXISTS daily_metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL UNIQUE,
                    starting_balance TEXT NOT NULL,
                    ending_balance TEXT,
                    trade_count INTEGER DEFAULT 0,
                    win_count INTEGER DEFAULT 0,
                    loss_count INTEGER DEFAULT 0,
                    total_pnl TEXT DEFAULT '0',
                    max_drawdown TEXT DEFAULT '0',
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS incidents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    severity TEXT NOT NULL,
                    category TEXT NOT NULL,
                    message TEXT NOT NULL,
                    details TEXT,
                    resolved INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                );

                CREATE INDEX IF NOT EXISTS idx_positions_status
                    ON positions(status);
                CREATE INDEX IF NOT EXISTS idx_positions_symbol
                    ON positions(symbol);
                CREATE INDEX IF NOT EXISTS idx_orders_position_id
                    ON orders(position_id);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_orders_client_order_id
                    ON orders(client_order_id)
                    WHERE client_order_id IS NOT NULL;
                CREATE UNIQUE INDEX IF NOT EXISTS idx_trades_order_fill
                    ON trades(order_id, price, quantity, created_at);
                CREATE INDEX IF NOT EXISTS idx_daily_metrics_date
                    ON daily_metrics(date);
                CREATE INDEX IF NOT EXISTS idx_incidents_severity
                    ON incidents(severity, resolved);
            """)
        logger.info("[DB] Database initialized successfully")

    # =========================================================================
    # Positions
    # =========================================================================
    def open_position(self, symbol: str, side: str, entry_price: Decimal,
                      quantity: Decimal, stop_loss: Decimal,
                      take_profit: Decimal, regime: str = '',
                      confidence: float = 0.0, reasons: list = None,
                      oco_order_list_id: str = None) -> int:
        """Create a new open position. Returns position ID."""
        with self._get_conn() as conn:
            cursor = conn.execute("""
                INSERT INTO positions
                    (symbol, side, entry_price, quantity, entry_time, status,
                     stop_loss, take_profit, regime, confidence, reasons,
                     oco_order_list_id)
                VALUES (?, ?, ?, ?, ?, 'OPEN', ?, ?, ?, ?, ?, ?)
            """, (
                symbol, side, str(entry_price), str(quantity),
                datetime.utcnow().isoformat(), str(stop_loss),
                str(take_profit), regime, confidence,
                json.dumps(reasons or []),
                oco_order_list_id
            ))
            pos_id = cursor.lastrowid
            logger.info(f"[DB] Position opened: id={pos_id}, {side} {quantity} {symbol} @ {entry_price}")
            return pos_id

    def close_position(self, position_id: int, exit_price: Decimal,
                       pnl: Decimal) -> None:
        """Close a position with exit price and PnL."""
        with self._get_conn() as conn:
            conn.execute("""
                UPDATE positions
                SET status='CLOSED', exit_price=?, exit_time=?, pnl=?,
                    updated_at=datetime('now')
                WHERE id=?
            """, (str(exit_price), datetime.utcnow().isoformat(),
                  str(pnl), position_id))
        logger.info(f"[DB] Position closed: id={position_id}, pnl={pnl}")

    def get_open_position(self, symbol: str) -> Optional[Dict]:
        """Get the current open position for a symbol, if any."""
        with self._get_conn() as conn:
            row = conn.execute("""
                SELECT * FROM positions
                WHERE symbol=? AND status='OPEN'
                ORDER BY created_at DESC LIMIT 1
            """, (symbol,)).fetchone()
            return dict(row) if row else None

    def update_position_oco(self, position_id: int,
                            oco_order_list_id: str) -> None:
        """Update OCO order list ID on a position."""
        with self._get_conn() as conn:
            conn.execute("""
                UPDATE positions SET oco_order_list_id=?, updated_at=datetime('now')
                WHERE id=?
            """, (oco_order_list_id, position_id))

    def upsert_reconciled_position(self, symbol: str, side: str,
                                   entry_price: Decimal,
                                   quantity: Decimal) -> int:
        """Create or refresh a position found on Binance during reconciliation."""
        current = self.get_open_position(symbol)
        if current:
            with self._get_conn() as conn:
                conn.execute("""
                    UPDATE positions
                    SET side=?, entry_price=?, quantity=?, updated_at=datetime('now')
                    WHERE id=?
                """, (side, str(entry_price), str(quantity), current['id']))
            return int(current['id'])
        return self.open_position(
            symbol=symbol,
            side=side,
            entry_price=entry_price,
            quantity=quantity,
            stop_loss=Decimal('0'),
            take_profit=Decimal('0'),
            regime='reconciled',
            confidence=0.0,
            reasons=['Recovered from Binance balance'],
        )

    # =========================================================================
    # Orders
    # =========================================================================
    def save_order(self, position_id: Optional[int], order_id: str,
                   symbol: str, side: str, order_type: str,
                   quantity: Decimal, price: Decimal = None,
                   status: str = '', filled_qty: Decimal = None,
                   avg_price: Decimal = None, commission: Decimal = None,
                   raw_response: dict = None,
                   client_order_id: Optional[str] = None) -> int:
        """Save an order record. Returns internal order row ID."""
        with self._get_conn() as conn:
            cursor = conn.execute("""
                INSERT INTO orders
                    (position_id, order_id, client_order_id, symbol, side, order_type,
                     quantity, price, status, filled_qty, avg_price,
                     commission, raw_response)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                position_id, str(order_id), client_order_id, symbol, side, order_type,
                str(quantity),
                str(price) if price is not None else None,
                status,
                str(filled_qty) if filled_qty is not None else '0',
                str(avg_price) if avg_price is not None else '0',
                str(commission) if commission is not None else '0',
                json.dumps(raw_response) if raw_response else None
            ))
            return cursor.lastrowid

    def upsert_order(self, position_id: Optional[int], order_id: str,
                     symbol: str, side: str, order_type: str,
                     quantity: Decimal, price: Decimal = None,
                     status: str = '', filled_qty: Decimal = None,
                     avg_price: Decimal = None, commission: Decimal = None,
                     raw_response: dict = None,
                     client_order_id: Optional[str] = None) -> int:
        """Idempotently insert/update an order by client order ID or order ID."""
        raw = json.dumps(raw_response) if raw_response else None
        with self._get_conn() as conn:
            row = None
            if client_order_id:
                row = conn.execute(
                    "SELECT id FROM orders WHERE client_order_id=?",
                    (client_order_id,),
                ).fetchone()
            if row is None:
                row = conn.execute(
                    "SELECT id FROM orders WHERE order_id=? AND symbol=?",
                    (str(order_id), symbol),
                ).fetchone()
            if row:
                conn.execute("""
                    UPDATE orders
                    SET position_id=COALESCE(?, position_id), order_id=?,
                        symbol=?, side=?, order_type=?, quantity=?, price=?,
                        status=?, filled_qty=?, avg_price=?, commission=?,
                        raw_response=COALESCE(?, raw_response),
                        updated_at=datetime('now')
                    WHERE id=?
                """, (
                    position_id, str(order_id), symbol, side, order_type,
                    str(quantity), str(price) if price is not None else None,
                    status, str(filled_qty if filled_qty is not None else '0'),
                    str(avg_price if avg_price is not None else '0'),
                    str(commission if commission is not None else '0'),
                    raw, row['id'],
                ))
                return int(row['id'])
            return self.save_order(
                position_id, order_id, symbol, side, order_type, quantity,
                price, status, filled_qty, avg_price, commission,
                raw_response, client_order_id,
            )

    def update_order_status(self, order_id: str, status: str,
                            filled_qty: Decimal = None,
                            avg_price: Decimal = None) -> None:
        updates = ["status=?", "updated_at=datetime('now')"]
        params = [status]
        if filled_qty is not None:
            updates.append("filled_qty=?")
            params.append(str(filled_qty))
        if avg_price is not None:
            updates.append("avg_price=?")
            params.append(str(avg_price))
        params.append(str(order_id))
        with self._get_conn() as conn:
            conn.execute(
                f"UPDATE orders SET {', '.join(updates)} WHERE order_id=?",
                params,
            )

    def get_pending_orders(self, symbol: str) -> List[Dict]:
        """Get all non-filled orders for a symbol."""
        with self._get_conn() as conn:
            rows = conn.execute("""
                SELECT * FROM orders
                WHERE symbol=? AND status NOT IN ('FILLED', 'CANCELED', 'EXPIRED', 'REJECTED')
                ORDER BY created_at DESC
            """, (symbol,)).fetchall()
            return [dict(r) for r in rows]

    # =========================================================================
    # Trades (fills)
    # =========================================================================
    def save_trade(self, position_id: Optional[int], order_id: str,
                   symbol: str, side: str, price: Decimal,
                   quantity: Decimal, commission: Decimal = Decimal('0'),
                   commission_asset: str = '',
                   realized_pnl: Decimal = Decimal('0')) -> int:
        """Save a trade fill."""
        with self._get_conn() as conn:
            cursor = conn.execute("""
                INSERT INTO trades
                    (position_id, order_id, symbol, side, price, quantity,
                     commission, commission_asset, realized_pnl)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                position_id, str(order_id), symbol, side,
                str(price), str(quantity), str(commission),
                commission_asset, str(realized_pnl)
            ))
            return cursor.lastrowid

    # =========================================================================
    # Daily Metrics
    # =========================================================================
    def get_or_create_daily_metrics(self, today: str,
                                    starting_balance: Decimal) -> Dict:
        """Get or create daily metrics row for today."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM daily_metrics WHERE date=?", (today,)
            ).fetchone()
            if row:
                return dict(row)
            conn.execute("""
                INSERT INTO daily_metrics (date, starting_balance)
                VALUES (?, ?)
            """, (today, str(starting_balance)))
            row = conn.execute(
                "SELECT * FROM daily_metrics WHERE date=?", (today,)
            ).fetchone()
            return dict(row)

    def update_daily_metrics(self, today: str, trade_count: int = None,
                             win_count: int = None, loss_count: int = None,
                             total_pnl: Decimal = None,
                             ending_balance: Decimal = None,
                             max_drawdown: Decimal = None) -> None:
        """Update daily metrics incrementally."""
        updates = []
        params = []
        if trade_count is not None:
            updates.append("trade_count=?")
            params.append(trade_count)
        if win_count is not None:
            updates.append("win_count=?")
            params.append(win_count)
        if loss_count is not None:
            updates.append("loss_count=?")
            params.append(loss_count)
        if total_pnl is not None:
            updates.append("total_pnl=?")
            params.append(str(total_pnl))
        if ending_balance is not None:
            updates.append("ending_balance=?")
            params.append(str(ending_balance))
        if max_drawdown is not None:
            updates.append("max_drawdown=?")
            params.append(str(max_drawdown))
        if not updates:
            return
        updates.append("updated_at=datetime('now')")
        params.append(today)
        with self._get_conn() as conn:
            conn.execute(
                f"UPDATE daily_metrics SET {', '.join(updates)} WHERE date=?",
                params
            )

    def get_period_pnl(self, days: int) -> Decimal:
        """Get total PnL for the last N days."""
        since = (date.today() - timedelta(days=days)).isoformat()
        with self._get_conn() as conn:
            row = conn.execute("""
                SELECT COALESCE(SUM(CAST(total_pnl AS REAL)), 0) as total
                FROM daily_metrics WHERE date >= ?
            """, (since,)).fetchone()
            return Decimal(str(row['total']))

    def get_daily_trade_count(self, today: str) -> int:
        """Get trade count for today."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT trade_count FROM daily_metrics WHERE date=?", (today,)
            ).fetchone()
            return row['trade_count'] if row else 0

    def get_peak_balance(self) -> Decimal:
        """Get the highest ending balance ever recorded."""
        with self._get_conn() as conn:
            row = conn.execute("""
                SELECT MAX(CAST(ending_balance AS REAL)) as peak
                FROM daily_metrics WHERE ending_balance IS NOT NULL
            """).fetchone()
            val = row['peak'] if row and row['peak'] is not None else 0
            return Decimal(str(val))

    def get_period_trade_count(self, days: int) -> int:
        since = (date.today() - timedelta(days=days)).isoformat()
        with self._get_conn() as conn:
            row = conn.execute("""
                SELECT COALESCE(SUM(trade_count), 0) as total
                FROM daily_metrics WHERE date >= ?
            """, (since,)).fetchone()
            return int(row['total'] or 0)

    def get_open_positions(self) -> List[Dict]:
        with self._get_conn() as conn:
            rows = conn.execute("""
                SELECT * FROM positions
                WHERE status='OPEN'
                ORDER BY created_at DESC
            """).fetchall()
            return [dict(r) for r in rows]

    def get_last_trade_time(self, symbol: str) -> Optional[datetime]:
        """Get the timestamp of the last trade for a symbol."""
        with self._get_conn() as conn:
            row = conn.execute("""
                SELECT created_at FROM trades
                WHERE symbol=?
                ORDER BY created_at DESC LIMIT 1
            """, (symbol,)).fetchone()
            if row:
                return datetime.fromisoformat(row['created_at'])
            return None

    # =========================================================================
    # Incidents
    # =========================================================================
    def log_incident(self, severity: str, category: str,
                     message: str, details: str = None) -> int:
        """Log a critical incident."""
        with self._get_conn() as conn:
            cursor = conn.execute("""
                INSERT INTO incidents (severity, category, message, details)
                VALUES (?, ?, ?, ?)
            """, (severity, category, message, details))
            incident_id = cursor.lastrowid
            logger.warning(
                f"[INCIDENT] {severity} | {category} | {message}")
            return incident_id

    def get_unresolved_incidents(self) -> List[Dict]:
        """Get all unresolved incidents."""
        with self._get_conn() as conn:
            rows = conn.execute("""
                SELECT * FROM incidents WHERE resolved=0
                ORDER BY created_at DESC
            """).fetchall()
            return [dict(r) for r in rows]
