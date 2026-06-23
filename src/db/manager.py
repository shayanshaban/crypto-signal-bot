"""
src/db/manager.py — SQLite persistence layer.

Handles all database I/O.  No business logic lives here.

Public API:
  init_db()                          — create/migrate tables on startup
  save_signal(raw, parsed)           — log every raw AI response + parsed fields
  open_position(signal)              — insert an OPEN position
  close_position(symbol, exit_price) — mark CLOSED, compute PnL
  cancel_position(symbol)            — mark CANCELLED
  has_open_position(symbol?)         — bool check
  get_open(symbol?)                  — fetch open row
  get_stats(symbol?)                 — aggregated performance dict
  get_history(limit, symbol?)        — last N closed positions
  print_summary()                    — pretty-print to stdout
"""

import sqlite3
from contextlib import contextmanager
from pathlib import Path
import time
import json           # NEW
import pandas as pd   # NEW
import config


# ── Connection ────────────────────────────────────────────────────────────────

@contextmanager
def _db():
    """Yield a cursor; auto-commit on success, rollback on error."""
    Path(config.DB_FILE).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_FILE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn.cursor()
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ── Schema ────────────────────────────────────────────────────────────────────

def init_db() -> None:
    """Create tables if they don't exist. Safe to call on every startup."""
    with _db() as cur:

        # Every raw AI response (signal or otherwise)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS signals (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                raw         TEXT,
                symbol      TEXT,
                position    TEXT,
                confidence  INTEGER,
                entry       REAL,
                stop_loss   REAL,
                take_profit REAL,
                risk_reward REAL,
                reason      TEXT,
                created_at  TEXT DEFAULT (datetime('now'))
            )
        """)

        # Opened / closed / cancelled trades
        cur.execute("""
            CREATE TABLE IF NOT EXISTS positions (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                signal_id    INTEGER REFERENCES signals(id),
                symbol       TEXT    NOT NULL,
                position    TEXT    NOT NULL,   -- LONG / SHORT
                status       TEXT    NOT NULL DEFAULT 'OPEN',
                confidence   INTEGER,
                entry        REAL    NOT NULL,
                stop_loss    REAL    NOT NULL,
                take_profit  REAL    NOT NULL,
                risk_reward  REAL,
                exit_price   REAL,
                pnl_pct      REAL,
                reason       TEXT,
                opened_at    TEXT    DEFAULT (datetime('now', 'localtime')),
                closed_at    TEXT
            )
        """)

        # back test table (UPDATED with two new columns)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS back_test_signals (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                thread_index INTEGER,    
                raw          TEXT,
                symbol       TEXT,
                position     TEXT,
                confidence   INTEGER,
                entry        REAL,
                stop_loss    REAL,
                take_profit  REAL,
                risk_reward  REAL,
                reason       TEXT,
                chat_link    TEXT,
                created_at   TEXT DEFAULT (datetime('now', 'localtime'))
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS back_test_position (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                signal_id        INTEGER REFERENCES back_test_signals(id),
                thread_index     INTEGER,
                symbol           TEXT    NOT NULL,
                timeframe        TEXT,
                position         TEXT    NOT NULL,
                status           TEXT    NOT NULL DEFAULT 'OPEN',
                confidence       INTEGER,
                entry            REAL    NOT NULL,
                stop_loss        REAL    NOT NULL,
                take_profit      REAL    NOT NULL,
                risk_reward      REAL,
                exit_price       REAL,
                pnl_pct          REAL,
                reason           TEXT,
                entry_timestamp  INTEGER,
                exit_timestamp   INTEGER,
                opened_at        TEXT    DEFAULT (datetime('now', 'localtime')),
                closed_at        TEXT,
                -- NEW columns for ML pipeline
                setup_type       TEXT,           -- e.g., 'trend_pullback'
                features_json    TEXT            -- JSON dictionary of all features
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS historical_candels (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                Timestamp   INTEGER,
                Open        REAL,
                High        REAL,
                Low         REAL,
                Close       REAL,
                Volume      REAL,
                Timeframe   TEXT              
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS back_test_candels_base_line (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                Timestamp   INTEGER,
                Open        REAL,
                High        REAL,
                Low         REAL,
                Close       REAL,
                Volume      REAL,
                Timeframe   TEXT,
                IsChecked   Boolean   DEFAULT FALSE
            )
        """)

        # --- MIGRATION: add new columns if they don't exist (for existing databases) ---
        # This ensures we don't break existing installations.
        try:
            cur.execute("ALTER TABLE back_test_position ADD COLUMN setup_type TEXT")
        except sqlite3.OperationalError:
            pass  # column already exists
        try:
            cur.execute("ALTER TABLE back_test_position ADD COLUMN features_json TEXT")
        except sqlite3.OperationalError:
            pass


# ── BackTest (existing functions) ──────────────────────────────────────────

def get_candles_for_trigger(timestamp: int, timeframe: str, count: int = 100) -> list:
    """
    Return the last `count` candles up to `timestamp` from historical_candels,
    in [[ts, o, h, l, c, v]] format — same as LBank raw output.
    Used to feed baker.should_ask_ai() without going through the full fetcher.
    """
    with _db() as cur:
        rows = cur.execute("""
            SELECT Timestamp, Open, High, Low, Close, Volume
            FROM historical_candels
            WHERE Timeframe = ? AND Timestamp <= ?
            ORDER BY Timestamp DESC
            LIMIT ?
        """, (timeframe, timestamp, count)).fetchall()
    return [list(r) for r in reversed(rows)]


def get_current_price_from_db(timestamp: int) -> dict:
    """
    Return the latest known price at/before the given timestamp,
    using historical_candels as a stand-in for LBank's ticker endpoint.
    Used to simulate 'current price' during backtesting without leaking
    future data.

    Output shape matches _get_current_price():
        {"data": [{"price": <close>}], "ts": <timestamp>}
    """
    with _db() as cur:
        row = cur.execute("""
            SELECT Timestamp, Close
            FROM historical_candels
            WHERE Timeframe = ? AND Timestamp <= ?
            ORDER BY Timestamp DESC
            LIMIT 1
        """, (config.TRADING_TIME_FRAME, timestamp)).fetchone()
    if row is None:
        return {"data": [], "ts": timestamp}
    ts, close = row
    return {"data": [{"price": close}], "ts": ts}


def get_candles_from_db(timeframe: str, tf_minutes: int, count: int, to_time: int) -> dict:
    """
    Return candles from historical_candels in the same shape as the
    LBank kline API response: {"data": [[Timestamp, Open, High, Low, Close, Volume], ...]}.
    Used to feed the backtester from local data instead of calling the exchange.
    """
    from_time = to_time - (count * tf_minutes * 60)
    with _db() as cur:
        rows = cur.execute("""
            SELECT Timestamp, Open, High, Low, Close, Volume
            FROM historical_candels
            WHERE Timeframe = ? AND Timestamp >= ? AND Timestamp <= ?
            ORDER BY Timestamp ASC
            LIMIT ?
        """, (timeframe, from_time, to_time, count)).fetchall()
    return {"data": [list(row) for row in rows]}


def reset_back_test_db(include_historical: bool = False) -> None:
    """
    Wipe all back test tables to start a completely fresh run.

    include_historical: if True, also clears historical_candels
    (the raw fetched data). Usually you want to keep this and
    only reset signals/positions/baseline, since re-fetching
    historical data from the exchange/API is expensive.
    """
    with _db() as cur:
        cur.execute("DELETE FROM back_test_signals")
        cur.execute("DELETE FROM back_test_position")
        cur.execute("DELETE FROM back_test_candels_base_line")
        if include_historical:
            cur.execute("DELETE FROM historical_candels")
        tables = ["back_test_signals", "back_test_position", "back_test_candels_base_line"]
        if include_historical:
            tables.append("historical_candels")
        cur.execute(
            f"DELETE FROM sqlite_sequence WHERE name IN ({','.join('?' * len(tables))})",
            tables
        )


def rebuild_baseline_from_historical(base_timeframe: str) -> None:
    """
    Wipe and refill back_test_candels_base_line from historical_candels,
    using only the given base timeframe. This is the timeframe the
    backtest loop steps through candle-by-candle.
    """
    with _db() as cur:
        cur.execute("""
            INSERT INTO back_test_candels_base_line
                (Timestamp, Open, High, Low, Close, Volume, Timeframe)
            SELECT Timestamp, Open, High, Low, Close, Volume, Timeframe
            FROM historical_candels
            WHERE Timeframe = ?
        """, (base_timeframe,))


def save_back_test_signal(raw: str, parsed: dict, chat_link: str | None = None,
                            thread_index: int | None = None) -> int:
    with _db() as cur:
        cur.execute("""
            INSERT INTO back_test_signals
                (raw, symbol, position, confidence, entry,
                 stop_loss, take_profit, risk_reward, reason, chat_link, thread_index)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            raw, parsed.get("symbol"), parsed.get("position"), parsed.get("confidence"),
            parsed.get("entry"), parsed.get("stop_loss"), parsed.get("take_profit"),
            parsed.get("risk_reward"), parsed.get("reason"), chat_link, thread_index,
        ))
        return cur.lastrowid


def save_historical_candel(candels, timeframe: str) -> None:
    """
    Save historical candels for feeding the back tester.
    candels: list of [Timestamp, Open, High, Low, Close, Volume]
    """
    with _db() as cur:
        cur.executemany("""
            INSERT INTO historical_candels
                (Timestamp, Open, High, Low, Close, Volume, Timeframe)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, [
            (c[0], c[1], c[2], c[3], c[4], c[5], timeframe)
            for c in candels
        ])


def open_back_test_position(signal: dict, signal_id: int | None = None,
                              timeframe: str | None = None,
                              entry_timestamp: int | None = None,
                              thread_index: int | None = None,
                              setup_type: str | None = None,
                              features: dict | None = None) -> int:
    """
    Insert a new backtest position, optionally storing setup_type and features.

    Args:
        signal: dict with keys like symbol, position, entry, stop_loss, take_profit, etc.
        signal_id: optional reference to back_test_signals row.
        timeframe: e.g., '1m', '5m'.
        entry_timestamp: unix timestamp when the position was opened.
        thread_index: which backtest thread owns this position.
        setup_type: string identifying the rule that triggered this trade (e.g., 'trend_pullback').
        features: dict of all features extracted for ML (will be stored as JSON).

    Returns:
        new position row id.
    """
    if signal.get("position") == "NO_TRADE":
        raise ValueError("Cannot open a NO_TRADE signal.")

    features_json = json.dumps(features) if features else None

    with _db() as cur:
        cur.execute("""
            INSERT INTO back_test_position
                (signal_id, symbol, timeframe, position, confidence,
                 entry, stop_loss, take_profit, risk_reward, reason,
                 entry_timestamp, thread_index, setup_type, features_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            signal_id, signal["symbol"], timeframe, signal["position"], signal.get("confidence"),
            signal["entry"], signal["stop_loss"], signal["take_profit"], signal.get("risk_reward"),
            signal.get("reason"), entry_timestamp, thread_index, setup_type, features_json
        ))
        return cur.lastrowid


def close_back_test_position(position_id: int, exit_price: float,
                               exit_timestamp: int | None = None,
                               status: str = "CLOSED") -> None:
    """
    Close a backtest position, compute PnL, and update timestamps.

    Args:
        position_id: row id of the position.
        exit_price: price at which the position was closed.
        exit_timestamp: unix timestamp of exit (optional).
        status: e.g., 'CLOSED', 'TP', 'SL'.
    """
    with _db() as cur:
        row = cur.execute(
            "SELECT entry, position FROM back_test_position WHERE id = ?",
            (position_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"Position {position_id} not found.")
        entry, side = row[0], row[1]
        pnl_pct = ((exit_price - entry) / entry * 100 if side == "LONG"
                   else (entry - exit_price) / entry * 100)
        cur.execute("""
            UPDATE back_test_position
            SET exit_price = ?, exit_timestamp = ?, pnl_pct = ?, status = ?,
                closed_at = datetime('now', 'localtime')
            WHERE id = ?
        """, (exit_price, exit_timestamp, pnl_pct, status, position_id))


def get_chart_data(symbol: str, timeframe: str):
    """
    Returns candles + positions for charting, aligned by timestamp.
    """
    with _db() as cur:
        candles = cur.execute("""
            SELECT Timestamp, Open, High, Low, Close, Volume
            FROM historical_candels
            WHERE Timeframe = ?
            ORDER BY Timestamp ASC
        """, (timeframe,)).fetchall()
        positions = cur.execute("""
            SELECT id, position, entry, stop_loss, take_profit, exit_price,
                   entry_timestamp, exit_timestamp, status, pnl_pct
            FROM back_test_position
            WHERE symbol = ? AND timeframe = ?
            ORDER BY entry_timestamp ASC
        """, (symbol, timeframe)).fetchall()
    return {"candles": candles, "positions": positions}


def save_back_test_candels_base_line(candels, timeframe: str) -> None:
    """
    Load the baseline candle sequence the back tester will walk through.
    """
    with _db() as cur:
        cur.executemany("""
            INSERT INTO back_test_candels_base_line
                (Timestamp, Open, High, Low, Close, Volume, Timeframe)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, [
            (c[0], c[1], c[2], c[3], c[4], c[5], timeframe)
            for c in candels
        ])


def get_next_baseline_candle(timeframe: str) -> dict | None:
    """
    Return the next unchecked candle (oldest first) for the given timeframe,
    without marking it as checked.
    """
    with _db() as cur:
        row = cur.execute("""
            SELECT id, Timestamp, Open, High, Low, Close, Volume
            FROM back_test_candels_base_line
            WHERE Timeframe = ? AND IsChecked = FALSE
            ORDER BY Timestamp ASC
            LIMIT 1
        """, (timeframe,)).fetchone()
        if row is None:
            return None
        return {
            "id": row[0], "Timestamp": row[1], "Open": row[2],
            "High": row[3], "Low": row[4], "Close": row[5], "Volume": row[6],
        }


def mark_baseline_candle_checked(candle_id: int) -> None:
    with _db() as cur:
        cur.execute(
            "UPDATE back_test_candels_base_line SET IsChecked = TRUE WHERE id = ?",
            (candle_id,)
        )


def reset_baseline_progress(timeframe: str | None = None) -> None:
    """
    Reset IsChecked to start a fresh back test run.
    """
    with _db() as cur:
        if timeframe:
            cur.execute(
                "UPDATE back_test_candels_base_line SET IsChecked = FALSE WHERE Timeframe = ?",
                (timeframe,)
            )
        else:
            cur.execute("UPDATE back_test_candels_base_line SET IsChecked = FALSE")


def get_baseline_ids(trim: int = 0) -> list[int]:
    """
    Return all baseline candle ids in chronological order,
    dropping the first `trim` rows so AI always has enough
    historical lookback when querying historical_candels.
    """
    with _db() as cur:
        rows = cur.execute("""
            SELECT id FROM back_test_candels_base_line
            ORDER BY Timestamp ASC
        """).fetchall()
    ids = [r[0] for r in rows]
    return ids[trim:]


def get_next_baseline_candle_in_range(start_id: int, end_id: int) -> dict | None:
    """
    Return the next unchecked candle (oldest first) within [start_id, end_id],
    scoped to a single thread's slice of the baseline.
    """
    with _db() as cur:
        row = cur.execute("""
            SELECT id, Timestamp, Open, High, Low, Close, Volume, Timeframe
            FROM back_test_candels_base_line
            WHERE id BETWEEN ? AND ? AND IsChecked = FALSE
            ORDER BY Timestamp ASC
            LIMIT 1
        """, (start_id, end_id)).fetchone()
        if row is None:
            return None
        return {
            "id": row[0], "Timestamp": row[1], "Open": row[2],
            "High": row[3], "Low": row[4], "Close": row[5],
            "Volume": row[6], "Timeframe": row[7],
        }


def get_open_position_for_thread(thread_index: int) -> dict | None:
    """Return the single open position for this thread, if any."""
    with _db() as cur:
        row = cur.execute("""
            SELECT id, position, entry, stop_loss, take_profit
            FROM back_test_position
            WHERE thread_index = ? AND status = 'OPEN'
            LIMIT 1
        """, (thread_index,)).fetchone()
    if row is None:
        return None
    return {"id": row[0], "position": row[1], "entry": row[2],
            "stop_loss": row[3], "take_profit": row[4]}


def check_position_tp_sl(position_id: int, candle: dict) -> bool:
    """
    Check if this candle's High/Low hit TP or SL for the given position.
    Closes the position if so. Returns True if closed.
    """
    with _db() as cur:
        row = cur.execute(
            "SELECT position, stop_loss, take_profit FROM back_test_position WHERE id = ?",
            (position_id,)
        ).fetchone()
    if row is None:
        return False
    side, sl, tp = row
    high, low, ts = candle["High"], candle["Low"], candle["Timestamp"]
    if side == "LONG":
        if low <= sl:
            close_back_test_position(position_id, sl, exit_timestamp=ts, status="SL")
            return True
        if high >= tp:
            close_back_test_position(position_id, tp, exit_timestamp=ts, status="TP")
            return True
    else:  # SHORT
        if high >= sl:
            close_back_test_position(position_id, sl, exit_timestamp=ts, status="SL")
            return True
        if low <= tp:
            close_back_test_position(position_id, tp, exit_timestamp=ts, status="TP")
            return True
    return False


def get_baseline_progress() -> tuple[int, int]:
    """Return (checked_count, total_count) for the progress bar."""
    with _db() as cur:
        total   = cur.execute("SELECT COUNT(*) FROM back_test_candels_base_line").fetchone()[0]
        checked = cur.execute("SELECT COUNT(*) FROM back_test_candels_base_line WHERE IsChecked = TRUE").fetchone()[0]
    return checked, total


# ── NEW Helper Functions for ML Pipeline ──────────────────────────────────

def candles_to_dataframe(candles: list, timeframe: str | None = None) -> pd.DataFrame:
    """
    Convert a list of candles (from get_candles_for_trigger) into a pandas DataFrame.

    The input is the same format returned by get_candles_for_trigger():
        [[Timestamp, Open, High, Low, Close, Volume], ...]

    Args:
        candles: list of lists, each containing [ts, open, high, low, close, volume].
        timeframe: optional string (ignored in conversion, kept for consistency).

    Returns:
        pandas DataFrame with columns: ['Open','High','Low','Close','Volume']
        and a DatetimeIndex (from the timestamp column).
    """
    if not candles:
        return pd.DataFrame(columns=['Open','High','Low','Close','Volume'])

    df = pd.DataFrame(candles, columns=['Timestamp','Open','High','Low','Close','Volume'])
    df['Timestamp'] = pd.to_datetime(df['Timestamp'], unit='s')
    df.set_index('Timestamp', inplace=True)
    return df

def get_position(pos_id: int) -> dict | None:
    """
    Fetch a full position row by its id (including setup_type and features_json).

    Args:
        pos_id: position primary key.

    Returns:
        dict representation of the row, or None if not found.
    """
    with _db() as cur:
        row = cur.execute("SELECT * FROM back_test_position WHERE id = ?", (pos_id,)).fetchone()
    return dict(row) if row else None


def store_position_features(pos_id: int, features: dict, setup_type: str) -> None:
    """
    Update an existing position's setup_type and features_json.

    Args:
        pos_id: position primary key.
        features: dict of feature values to store as JSON.
        setup_type: string identifying the rule (e.g., 'trend_pullback').
    """
    with _db() as cur:
        cur.execute("""
            UPDATE back_test_position
            SET setup_type = ?, features_json = ?
            WHERE id = ?
        """, (setup_type, json.dumps(features), pos_id))


def get_position_features(pos_id: int) -> dict:
    """
    Retrieve the features JSON for a given position.

    Args:
        pos_id: position primary key.

    Returns:
        dict of features, or empty dict if none stored.
    """
    with _db() as cur:
        row = cur.execute("SELECT features_json FROM back_test_position WHERE id = ?", (pos_id,)).fetchone()
    if row is None or row[0] is None:
        return {}
    return json.loads(row[0])


def get_candles_between(start_ts: int, end_ts: int, timeframe: str | None = None) -> pd.DataFrame:
    """
    Fetch historical candles between two timestamps as a DataFrame.

    Args:
        start_ts: unix timestamp (inclusive).
        end_ts: unix timestamp (inclusive).
        timeframe: candle interval (defaults to config.TRADING_TIME_FRAME).

    Returns:
        pandas DataFrame with columns: ['Timestamp','Open','High','Low','Close','Volume']
        and a DatetimeIndex.
    """
    tf = timeframe or config.TRADING_TIME_FRAME
    with _db() as cur:
        rows = cur.execute("""
            SELECT Timestamp, Open, High, Low, Close, Volume
            FROM historical_candels
            WHERE Timeframe = ? AND Timestamp BETWEEN ? AND ?
            ORDER BY Timestamp ASC
        """, (tf, start_ts, end_ts)).fetchall()
    if not rows:
        return pd.DataFrame(columns=['Timestamp','Open','High','Low','Close','Volume'])
    df = pd.DataFrame(rows, columns=['Timestamp','Open','High','Low','Close','Volume'])
    df['Timestamp'] = pd.to_datetime(df['Timestamp'], unit='s')
    df.set_index('Timestamp', inplace=True)
    return df


# ── Signals ───────────────────────────────────────────────────────────────────

def save_signal(raw: str, parsed: dict) -> int:
    """
    Persist every AI response (regardless of whether a trade is opened).
    Returns the new signal row id.
    """
    with _db() as cur:
        cur.execute("""
            INSERT INTO signals
                (raw, symbol, position, confidence, entry,
                 stop_loss, take_profit, risk_reward, reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            raw,
            parsed.get("symbol"),
            parsed.get("position"),
            parsed.get("confidence"),
            parsed.get("entry"),
            parsed.get("stop_loss"),
            parsed.get("take_profit"),
            parsed.get("risk_reward"),
            parsed.get("reason"),
        ))
        return cur.lastrowid


# ── Positions ─────────────────────────────────────────────────────────────────

def open_position(signal: dict, signal_id: int | None = None) -> int:
    """
    Insert a new OPEN position.  Returns the new position row id.
    Raises ValueError if signal is NO_TRADE.
    """
    if signal.get("position") == "NO_TRADE":
        raise ValueError("Cannot open a NO_TRADE signal.")
    with _db() as cur:
        cur.execute("""
            INSERT INTO positions
                (signal_id, symbol, position, confidence,
                 entry, stop_loss, take_profit, risk_reward, reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            signal_id,
            signal["symbol"],
            signal["position"],
            signal.get("confidence"),
            signal["entry"],
            signal["stop_loss"],
            signal["take_profit"],
            signal.get("risk_reward"),
            signal.get("reason"),
        ))
        return cur.lastrowid


def close_position(id: int, exit_price: float) -> dict | None:
    """
    Mark the open position for *symbol* as CLOSED and compute PnL %.
    Returns the updated row as a dict, or None if nothing was open.
    """
    row = get_by_id(id)
    if row is None:
        return None
    pnl_pct = (
        (exit_price - row["entry"]) / row["entry"] * 100
        if row["position"] == "LONG"
        else (row["entry"] - exit_price) / row["entry"] * 100
    )
    with _db() as cur:
        cur.execute("""
            UPDATE positions
               SET status     = 'CLOSED',
                   exit_price = ?,
                   pnl_pct    = ?,
                   closed_at  = datetime('now')
             WHERE id = ?
        """, (exit_price, round(pnl_pct, 4), row["id"]))
    return {**dict(row), "exit_price": exit_price, "pnl_pct": round(pnl_pct, 4)}


def cancel_position(id: str) -> bool:
    """Mark the open position for *symbol* as CANCELLED."""
    row = get_by_id(id)
    if row is None:
        return False
    with _db() as cur:
        cur.execute(
            "UPDATE positions SET status='CANCELLED', closed_at=datetime('now') WHERE id=?",
            (row["id"],)
        )
    return True


# ── Queries ───────────────────────────────────────────────────────────────────

def has_open_position(symbol: str | None = None) -> bool:
    with _db() as cur:
        if symbol:
            cur.execute(
                "SELECT 1 FROM positions WHERE status='OPEN' AND symbol=? LIMIT 1",
                (symbol,)
            )
        else:
            cur.execute("SELECT 1 FROM positions WHERE status='OPEN' LIMIT 1")
        return cur.fetchone() is not None


def get_by_id(id) -> sqlite3.Row | None:
    with _db() as cur:
        if id:
            cur.execute(
                "SELECT * FROM positions WHERE status='OPEN' AND id=? LIMIT 1",
                (id,)
            )
        else:
            cur.execute("SELECT * FROM positions WHERE status='OPEN' LIMIT 1")
        return cur.fetchone()


def get_open(symbol: str | None = None) -> sqlite3.Row | None:
    with _db() as cur:
        if symbol:
            cur.execute(
                "SELECT * FROM positions WHERE status='OPEN' AND symbol=? LIMIT 1",
                (symbol,)
            )
        else:
            cur.execute("SELECT * FROM positions WHERE status='OPEN' LIMIT 1")
        return cur.fetchone()


def get_stats(symbol: str | None = None) -> dict:
    """Return aggregated performance for CLOSED positions."""
    where = "WHERE status='CLOSED'"
    args: tuple = ()
    if symbol:
        where += " AND symbol=?"
        args   = (symbol,)
    with _db() as cur:
        cur.execute(f"""
            SELECT
                COUNT(*)                                          AS total,
                SUM(CASE WHEN pnl_pct > 0 THEN 1 ELSE 0 END)    AS wins,
                ROUND(AVG(pnl_pct),    2)                        AS avg_pnl_pct,
                ROUND(SUM(pnl_pct),    2)                        AS total_pnl_pct,
                ROUND(AVG(risk_reward),2)                        AS avg_rr
            FROM positions {where}
        """, args)
        row = cur.fetchone()
    total    = row["total"] or 0
    wins     = row["wins"]  or 0
    win_rate = round(wins / total * 100, 1) if total else 0.0
    return {
        "symbol":        symbol or "ALL",
        "total_trades":  total,
        "wins":          wins,
        "losses":        total - wins,
        "win_rate_pct":  win_rate,
        "avg_pnl_pct":   row["avg_pnl_pct"],
        "total_pnl_pct": row["total_pnl_pct"],
        "avg_rr":        row["avg_rr"],
    }


def get_history(limit: int = 20, symbol: str | None = None) -> list[dict]:
    """Return the last *limit* CLOSED positions as a list of dicts."""
    where = "WHERE status='CLOSED'"
    args: tuple = ()
    if symbol:
        where += " AND symbol=?"
        args   = (symbol,)
    with _db() as cur:
        cur.execute(
            f"SELECT * FROM positions {where} ORDER BY closed_at DESC LIMIT ?",
            (*args, limit)
        )
        return [dict(r) for r in cur.fetchall()]


# ── Display ───────────────────────────────────────────────────────────────────

def print_summary() -> None:
    with _db() as cur:
        cur.execute("SELECT * FROM positions ORDER BY opened_at DESC")
        rows = cur.fetchall()
    if not rows:
        print("No positions recorded yet.")
        return
    fmt = "{:<4} {:<8} {:<6} {:<11} {:<9} {:<9} {:<9} {:<9} {:<8} {:<19}"
    hdr = fmt.format("ID", "SYMBOL", "DIR", "STATUS", "ENTRY", "SL", "TP", "EXIT", "PNL%", "OPENED")
    print(hdr)
    print("─" * len(hdr))
    for r in rows:
        pnl = f"{r['pnl_pct']:+.2f}%" if r["pnl_pct"] is not None else "—"
        ext = f"{r['exit_price']:.2f}"  if r["exit_price"] is not None else "—"
        print(fmt.format(
            r["id"], r["symbol"], r["position"], r["status"],
            f"{r['entry']:.2f}", f"{r['stop_loss']:.2f}", f"{r['take_profit']:.2f}",
            ext, pnl, r["opened_at"][:19],
        ))
    print()
    s = get_stats()
    print(f"  Closed: {s['total_trades']}  |  "
          f"Win rate: {s['win_rate_pct']}%  |  "
          f"Total PnL: {s['total_pnl_pct']}%  |  "
          f"Avg R:R: {s['avg_rr']}")