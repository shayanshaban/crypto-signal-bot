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
                direction    TEXT    NOT NULL,   -- LONG / SHORT
                status       TEXT    NOT NULL DEFAULT 'OPEN',
                confidence   INTEGER,
                entry        REAL    NOT NULL,
                stop_loss    REAL    NOT NULL,
                take_profit  REAL    NOT NULL,
                risk_reward  REAL,
                exit_price   REAL,
                pnl_pct      REAL,
                reason       TEXT,
                opened_at    TEXT    DEFAULT (datetime('now')),
                closed_at    TEXT
            )
        """)


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
                (signal_id, symbol, direction, confidence,
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


def close_position(symbol: str, exit_price: float) -> dict | None:
    """
    Mark the open position for *symbol* as CLOSED and compute PnL %.
    Returns the updated row as a dict, or None if nothing was open.
    """
    row = get_open(symbol)
    if row is None:
        return None

    pnl_pct = (
        (exit_price - row["entry"]) / row["entry"] * 100
        if row["direction"] == "LONG"
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


def cancel_position(symbol: str) -> bool:
    """Mark the open position for *symbol* as CANCELLED."""
    row = get_open(symbol)
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
            r["id"], r["symbol"], r["direction"], r["status"],
            f"{r['entry']:.2f}", f"{r['stop_loss']:.2f}", f"{r['take_profit']:.2f}",
            ext, pnl, r["opened_at"][:19],
        ))

    print()
    s = get_stats()
    print(f"  Closed: {s['total_trades']}  |  "
          f"Win rate: {s['win_rate_pct']}%  |  "
          f"Total PnL: {s['total_pnl_pct']}%  |  "
          f"Avg R:R: {s['avg_rr']}")
