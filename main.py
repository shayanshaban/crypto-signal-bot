"""
main.py — CLI entry point.

Commands:
  python main.py                   fetch signal, open position if worthy
  python main.py close <price>     close the open position at exit price
  python main.py cancel            cancel the open position (no PnL)
  python main.py stats             show performance summary
  python main.py positions         show all positions table
"""

import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import config
from src.data          import fetcher
from src.ai            import deepseek_client
from src.db            import manager as db
from src.trading       import signal_handler
from src.notifications import notify


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_signal() -> None:
    print("── [1/2] Fetching market data …")
    fetcher.fetch_data()
    print(f"      → {config.OUTPUT_FILE}")

    print("── [2/2] Querying DeepSeek …")
    raw = deepseek_client.run_from_file(config.OUTPUT_FILE)

    if not raw:
        print("ERROR: No response from DeepSeek.", file=sys.stderr)
        sys.exit(1)

    # Full pipeline: parse → save → evaluate → open
    result = signal_handler.process(raw)
    parsed = result["parsed"]

    if parsed:
        print("\n── Signal ─────────────────────────────────────────")
        print(json.dumps(parsed, indent=2))
    else:
        print("\n── Raw response (parse failed) ─────────────────────")
        print(raw)

    print(f"\n── Decision: {result['decision']} — {result['reason']}")

    if result["pos_id"]:
        notify(
            f"OPENED {parsed['position']} {parsed['symbol']} "
            f"@ {parsed['entry']}  SL {parsed['stop_loss']}  TP {parsed['take_profit']}"
        )

    # Also append raw to the legacy log file
    Path(config.LOG_FILE).parent.mkdir(parents=True, exist_ok=True)
    with open(config.LOG_FILE, "a", encoding="utf-8") as log:
        log.write(raw + "\n")


def cmd_close(exit_price: float) -> None:
    result = db.close_position(config.SYMBOL_DISPLAY, exit_price)
    if result is None:
        print(f"No open position for {config.SYMBOL_DISPLAY}.")
        return
    pnl = result["pnl_pct"]
    icon = "✅" if pnl >= 0 else "❌"
    msg  = f"{icon} CLOSED {result['direction']} {result['symbol']} — exit {exit_price}  PnL {pnl:+.2f}%"
    print(msg)
    notify(msg)


def cmd_cancel() -> None:
    ok = db.cancel_position(config.SYMBOL_DISPLAY)
    print("Position CANCELLED." if ok else f"No open position for {config.SYMBOL_DISPLAY}.")


def cmd_stats() -> None:
    stats = db.get_stats(config.SYMBOL_DISPLAY)
    print(f"\n── Stats: {stats['symbol']} ──────────────────────────")
    for k, v in stats.items():
        print(f"  {k:<20} {v}")


def cmd_positions() -> None:
    print()
    db.print_summary()


# ── Router ────────────────────────────────────────────────────────────────────

def main() -> None:
    db.init_db()
    args = sys.argv[1:]

    if   not args:            cmd_signal()
    elif args[0] == "close":
        if len(args) < 2:
            print("Usage: python main.py close <exit_price>")
            sys.exit(1)
        cmd_close(float(args[1]))
    elif args[0] == "cancel":  cmd_cancel()
    elif args[0] == "stats":   cmd_stats()
    elif args[0] == "positions": cmd_positions()
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
