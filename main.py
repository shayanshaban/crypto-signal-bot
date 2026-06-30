"""
main.py — CLI entry point.

Commands:
  python main.py                    fetch signal, open position if worthy
  python main.py close <id> <price> close the open position at exit price
  python main.py cancel <id>        cancel the open position (no PnL)
  python main.py stats              show performance summary
  python main.py positions          show all positions table
"""

import sys
import json
from pathlib import Path
import webbrowser

sys.path.insert(0, str(Path(__file__).parent))

import config
from src.data          import fetcher
from src.data          import data_extractor
from src.ai            import deepseek_client
from src.db            import manager as db
from src.trading       import signal_handler
from src.notifications import notify
from src.backtest import runner
from src.data.drawer import backtest_draw
from src.ml.train import train
from src.ml.prediction import predictor
from src.data.baker import enrich_dataframe
from src.data.fetcher import fetch_lbank_df


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
    result = signal_handler.process(raw["response"])
    parsed = result["parsed"]

    if parsed:
        print("\n── Signal ─────────────────────────────────────────")
        print(json.dumps(parsed, indent=2))
    else:
        print("\n── Raw response (parse failed) ─────────────────────")
        print(raw["response"])

    print(f"\n── Decision: {result['decision']} — {result['reason']}")

    if result["pos_id"]:
        notify(
            f"OPENED {parsed['position']} {parsed['symbol']} "
            f"@ {parsed['entry']}  SL {parsed['stop_loss']}  TP {parsed['take_profit']}"
        )

    # Also append raw to the legacy log file
    Path(config.LOG_FILE).parent.mkdir(parents=True, exist_ok=True)
    with open(config.LOG_FILE, "a", encoding="utf-8") as log:
        log.write(raw["response"] + "\n")


def cmd_close(id,exit_price: float) -> None:
    result = db.close_position(id, exit_price)
    if result is None:
        print(f"No open position for {config.SYMBOL_DISPLAY}.")
        return
    pnl = result["pnl_pct"]
    icon = "✅" if pnl >= 0 else "❌"
    msg  = f"{icon} CLOSED {result['direction']} {result['symbol']} — exit {exit_price}  PnL {pnl:+.2f}%"
    print(msg)
    notify(msg)


def cmd_cancel(id) -> None:
    ok = db.cancel_position(id)
    print("Position CANCELLED." if ok else f"No open position for {id}.")


def cmd_stats() -> None:
    stats = db.get_stats(config.SYMBOL_DISPLAY)
    print(f"\n── Stats: {stats['symbol']} ──────────────────────────")
    for k, v in stats.items():
        print(f"  {k:<20} {v}")


def cmd_positions() -> None:
    print()
    db.print_summary()

def predict():
    df = fetch_lbank_df(2000,config.TRADING_TIME_FRAME)
    print(df.tail(1)["Close"])
    enriched_data = enrich_dataframe(df)
    prob = predictor.predict_probability(
    enriched_data=enriched_data,
    side="LONG",
    timeframe=config.TRADING_TIME_FRAME,
    symbol= config.SYMBOL_DISPLAY
    )
    if(prob > 0.67):
        print("LONG :",f"{prob:.2%}")
        # return
    prob = predictor.predict_probability(
    enriched_data=enriched_data,
    side="SHORT",
    timeframe=config.TRADING_TIME_FRAME,
    symbol= config.SYMBOL_DISPLAY
    )
    if(prob > 0.67):
        print("SHORT :",prob)
        return
    
    print("NO-TRADE")


# ── Router ────────────────────────────────────────────────────────────────────

def main() -> None:
    db.init_db()
    args = sys.argv[1:]

    if   not args:            cmd_signal()
    elif args[0] == "close":
        if len(args) < 3:
            print("Usage: python main.py close <position_id> <exit_price>")
            sys.exit(1)
        cmd_close(args[1],float(args[2]))
    elif args[0] == "cancel":
        if len(args) < 2:
            print("Usage: python main.py cancel <position_id>")
            sys.exit(1)
        cmd_cancel(args[1])
    elif args[0] == "stats":   cmd_stats()
    elif args[0] == "positions": cmd_positions()
    elif args[0] == "start-bt":
        runner.full_start()
    elif args[0] == "reset-bt":
        runner.re_start()
    elif args[0] == "resume-bt":
        runner.resume_backtest()
    elif args[0] == "draw-bt":
        backtest_draw.draw_chart(
        timeframe=config.TRADING_TIME_FRAME,
        output_html=config.BACK_TEST_CHART_OUTPUT_FILE,
        )
        webbrowser.open(config.BACK_TEST_CHART_OUTPUT_FILE)
    elif args[0] == "import-data":
        data_extractor.import_zip_folder(config.IMPORT_DATA_FOLDER_DIR)
    elif args[0] == "clear-historical":
        db.reset_back_test_db(True)
    elif args[0] == "train":
        train()
    elif args[0] == "predict":
        predict()
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
