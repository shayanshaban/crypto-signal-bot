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
from src.notifications import notify
from src.backtest import runner
from src.data.drawer import backtest_draw
from src.ml.train import train
from src.ml.tunning import tune
from src.ml.prediction import predictor
from src.data.baker import enrich_dataframe
from src.data.fetcher import fetch_lbank_df,_get_current_price
from src.ml import dataset_builder

from src.trading.wallet import WalletManager
from src.trading.risk_manager import RiskManager
from src.trading.trade_logger import TradeLogger
from src.trading.paper_trader import PaperTrader
from src.trading.constants import DEFAULT_SLIPPAGE

import time
from datetime import datetime, timezone


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_signal() -> None:
    pass


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
    entry = df.iloc[-1]["Close"]
    print("Current Price :",entry)
    enriched_data = enrich_dataframe(df)
    prob = predictor.predict_probability(
    enriched_data=enriched_data,
    side="LONG",
    timeframe=config.TRADING_TIME_FRAME,
    symbol= config.SYMBOL_DISPLAY
    )
    atr = enriched_data.iloc[-1]["ATR(14)"]
    print("LONG :",f"{prob:.2%}")
    stop_loss = entry - 1.5 * atr
    take_profit = entry + 3.0 * atr
    print("LONG :",f"{prob:.2%}")
    print("TP :",take_profit)
    print("SL :",stop_loss)
    if(prob >= 0.56):
        stop_loss = entry - 1.5 * atr
        take_profit = entry + 3.0 * atr
        print("LONG :",f"{prob:.2%}")
        print("TP :",take_profit)
        print("SL :",stop_loss)
        return
    prob = predictor.predict_probability(
    enriched_data=enriched_data,
    side="SHORT",
    timeframe=config.TRADING_TIME_FRAME,
    symbol= config.SYMBOL_DISPLAY
    )
    print("SHORT :",f"{prob:.2%}")
    stop_loss = entry + 1.5 * atr
    take_profit = entry - 3.0 * atr
    print("SHORT :",f"{prob:.2%}")
    print("TP :",take_profit)
    print("SL :",stop_loss)
    if(prob >= 0.56):
        stop_loss = entry + 1.5 * atr
        take_profit = entry - 3.0 * atr
        print("SHORT :",f"{prob:.2%}")
        print("TP :",take_profit)
        print("SL :",stop_loss)
        return
    
    print("NO-TRADE")

def trade():

    # 1. Setup components
    wallet_mgr = WalletManager("data/wallet.json")
    risk_mgr = RiskManager()
    logger = TradeLogger("logs/trades.jsonl")
    trader = PaperTrader(wallet_mgr, risk_mgr, logger)

    # Print initial wallet
    wallet = wallet_mgr.load_wallet()

    if (len(wallet.open_positions) != 0):
        ticker = _get_current_price()


        df = fetch_lbank_df(5,config.TRADING_TIME_FRAME)
        current_price = df.iloc[-1]["High"]
        trader.update_positions(current_price)
        print("High Price :",current_price)
        current_price = df.iloc[-1]["Low"]
        trader.update_positions(current_price)
        print("Low Price :",current_price)
        current_price = float(ticker['data'][0]['price'])
        print("Current Price :",current_price)
        trader.update_positions(current_price)
        
        print("Positions Update")
        return
    
    entry,take_profit,stop_loss,side = None,None,None,None

    df = fetch_lbank_df(2000,config.TRADING_TIME_FRAME)
    entry = df.iloc[-1]["Close"]
    enriched_data = enrich_dataframe(df)
    prob = predictor.predict_probability(
        enriched_data=enriched_data,
        side="LONG",
        timeframe=config.TRADING_TIME_FRAME,
        symbol= config.SYMBOL_DISPLAY
        )
    atr = enriched_data.iloc[-1]["ATR(14)"]
    if(prob >= 0.56):
        stop_loss = entry - 1.5 * atr
        take_profit = entry + 3.0 * atr
        side = "LONG"
        
    prob = predictor.predict_probability(
        enriched_data=enriched_data,
        side="SHORT",
        timeframe=config.TRADING_TIME_FRAME,
        symbol= config.SYMBOL_DISPLAY
        )
    if(prob >= 0.56):
        stop_loss = entry + 1.5 * atr
        take_profit = entry - 3.0 * atr
        side = "SHORT"

    if(entry == None or take_profit == None or stop_loss == None):
        print("NO-TRADE")
        return


    # 2. Open a LONG position
    pos = trader.open_position(
        symbol=config.SYMBOL_DISPLAY,
        side=side,
        entry_price=entry,
        stop_loss=stop_loss,
        take_profit=take_profit,
        risk_percent=0.01,   # risk 1% of balance
        leverage=100,
        slippage_rate=DEFAULT_SLIPPAGE,
    )
    print(f"\nOpened position {pos.id}: {pos}")
    

def paper_trade():
    while True:
       
        now = datetime.now(timezone.utc)

        
        sleep_time = 60 - now.second - now.microsecond / 1_000_000

        time.sleep(sleep_time+4)

        trade()
def make_file_name_list(interval: str) -> list:
    START_YEAR = 2026
    START_MONTH = 1

    END_YEAR = 2026
    END_MONTH = 5
    file_list = []
    for year in range(START_YEAR, END_YEAR + 1):
        for month in range(1, 13):

            if year == START_YEAR and month < START_MONTH:
                continue

            if year == END_YEAR and month > END_MONTH:
                break

            month_str = f"{month:02d}"

            filename = f"{config.SYMBOL_DISPLAY}-{interval}-{year}-{month_str}.zip"
            file_list.append(filename)

    return file_list

def build_multitime_dataset(timeframe):
    file_name = config.DATASET_FILE_NAME
    file = file_name
    if not timeframe in config.MULTI_TIMME_FRAME_LIST:
        return
    file = file_name
    print("-"*5,timeframe,"-"*5)
    db.reset_back_test_db(True)
    print("-"*5,"DataBase Cleared","-"*5)
    config.TRADING_TIME_FRAME = timeframe
    config.DATASET_FILE_NAME = file + "_" +timeframe+".csv"
    file_list = make_file_name_list(config.MULTI_TIMME_FRAME_MAP[timeframe])
    print("-"*5,"File List Created","-"*5)
    data_extractor.import_selected_files(config.IMPORT_DATA_FOLDER_DIR,file_list,True)
    print("-"*5,"Zip Files has been imported","-"*5)
    dataset_builder.start()
    print("-"*5,"Dataset Built","-"*5)
        

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
    elif args[0] == "tune":
        tune()
    elif args[0] == "build-dataset":
        dataset_builder.start()
    elif args[0] == "build-easy-dataset":
        build_multitime_dataset(input("Please Enter Timeframe: "))
    elif args[0] == "resume-build-dataset":
        dataset_builder.resume_dataset_builder()
    elif args[0] == "start-pt":
        paper_trade()
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
