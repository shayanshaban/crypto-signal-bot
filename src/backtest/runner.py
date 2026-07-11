"""
src/backtest/runner.py — backtest orchestration: thread workers, progress bar.
"""

import sys
import threading
import time

import config
from src.data import fetcher
from src.db import manager as db
from src.backtest import state as st
from src.ml.dataset_storage import save_market_snapshot
from src.data.baker import enrich_dataframe
from src.data.baker import calculate_reward_r
from src.ml.prediction import predictor
import bisect
import pandas as pd
import queue

global _checked_ids
_checked_ids = set()
BATCH_SIZE = 100_000


def load_global_data():
    global enriched_candels, enriched_timestamps
    global base_line_candels, base_line_timestamps

    enriched_rows = db.get_all_enriched_candels()
    enriched_candels = db.enriched_rows_to_dataframe(enriched_rows)
    enriched_candels = enriched_candels.sort_values("timestamp").reset_index(drop=True)
    enriched_timestamps = enriched_candels["timestamp"].tolist()

    base_line_candels = sorted(db.get_all_baseline(), key=lambda x: x["Timestamp"])
    base_line_timestamps = [c["Timestamp"] for c in base_line_candels]


def get_enriched_window_mem(baseline_timestamp: int, window_size: int = 50) -> pd.DataFrame:
    
    idx = bisect.bisect_right(enriched_timestamps, baseline_timestamp) - 1
    if idx < 0:
        return pd.DataFrame()  
    
    start_idx = max(0, idx - window_size + 1)
    return enriched_candels.iloc[start_idx : idx + 1]

def get_next_baseline_candle_in_range_mem(current_index: int,start_id: int,end_id: int) -> dict | None:
    if (current_index < start_id or current_index > end_id):
        return None
    if(current_index >= 0 and current_index < len(base_line_candels)):
        candle = base_line_candels[current_index]
        if candle["id"] not in _checked_ids:
            _checked_ids.add(candle["id"])
        return candle
    return None

def convert_ts_to_id(ts: int):
    idx = bisect.bisect_left(base_line_timestamps, ts)
    return idx

def get_baseline_progress_mem() -> tuple[int, int]:
    """Return (checked_count, total_count) from in-memory structures."""
    total = len(base_line_candels)
    checked = len(_checked_ids)
    return checked, total


MAX_HOLDING_CANDLES = 30
def check_position(position,future_candles):
    exit_price = None
    for candle in future_candles:

            if position["side"] == "LONG":

                if candle["Low"] <= position["stop_loss"]:
                    exit_price = position["stop_loss"]
                    break

                if candle["High"] >= position["take_profit"]:
                    exit_price = position["take_profit"]
                    break

            else:

                if candle["High"] >= position["stop_loss"]:
                    exit_price = position["stop_loss"]
                    break

                if candle["Low"] <= position["take_profit"]:
                    exit_price = position["take_profit"]
                    break

    if exit_price is None:
        exit_price = future_candles[-1]["Close"]

    return exit_price

def save_state(thread_state: dict,counter: int):
    if(counter % BATCH_SIZE == 0):
        thread_index = thread_state["thread_index"]
        st.save_thread_state(thread_index, thread_state)

def run_thread(thread_state: dict) -> None:
    thread_index = thread_state["thread_index"]
    start_ts = thread_state["start_ts"]
    end_ts = thread_state["end_ts"]
    id = convert_ts_to_id(int(thread_state["last_processed_ts"]))
    start_id = convert_ts_to_id(int(thread_state["start_ts"]))
    end_id = convert_ts_to_id(int(thread_state["end_ts"]))
    counter = 0

    while True:
        # candle = db.get_next_baseline_candle_in_range(start_ts, end_ts)
        candle = get_next_baseline_candle_in_range_mem(id,start_id,end_id)
        if candle is None:
            thread_state["status"] = "done"
            save_state(thread_state,counter)
            return
        open_pos = db.get_open_position_for_thread(thread_index)
        # open_pos = thread_state.get("open_position_id", None)
        baseline_timestamp = candle["Timestamp"]
        baseline_id = candle["id"]
        timestamp = candle["Timestamp"]
        if open_pos is not None:
            holding_candles = thread_state.get("holding_candles", 0)
            
            if holding_candles >= MAX_HOLDING_CANDLES:
                db.close_position_at_market(open_pos["id"], candle)
                thread_state["holding_candles"] = 0
                thread_state["open_position_id"] = None
                closed = True
                # db.mark_baseline_candle_checked(baseline_id)
                # thread_state["last_processed_ts"] = baseline_timestamp
                # st.save_thread_state(thread_index, thread_state)
                id = id + 1
                counter = counter + 1
                save_state(thread_state,counter)
                continue
            else :   
                closed = db.check_position_tp_sl(open_pos["id"], candle)
                if closed:
                    thread_state["holding_candles"] = 0
                    thread_state["open_position_id"] = None
                    # db.mark_baseline_candle_checked(baseline_id)
                    # thread_state["last_processed_ts"] = baseline_timestamp
                    # st.save_thread_state(thread_index, thread_state)
                    id = id + 1
                    counter = counter + 1
                    save_state(thread_state,counter)
                    continue

            thread_state["holding_candles"] = thread_state.get("holding_candles", 0) + 1
        else:
            df_window = get_enriched_window_mem(timestamp,5)
            atr = df_window.iloc[-1]["atr14"]
            if atr is None or atr == 0:
                # db.mark_baseline_candle_checked(baseline_id)
                # thread_state["last_processed_ts"] = baseline_timestamp
                # st.save_thread_state(thread_index, thread_state)
                id = id + 1
                counter = counter + 1
                save_state(thread_state,counter)
                continue
            entry = candle["Close"]
            prob = predictor.predict_probability(
                enriched_data=df_window,
                side="LONG",
                timeframe=config.TRADING_TIME_FRAME,
                symbol= config.SYMBOL_DISPLAY
                )
            atr_mul = ( entry * 0.0024 ) / atr
            if(prob >= 0.64):
                stop_loss = entry-(atr * atr_mul )
                take_profit = entry + 10 * atr
                position = {
                    "side" : "LONG",
                    "entry" : candle["Close"],
                    "stop_loss" : stop_loss,
                    "take_profit" : take_profit
                }
                
            else:
                prob = predictor.predict_probability(
                    enriched_data=df_window,
                    side="SHORT",
                    timeframe=config.TRADING_TIME_FRAME,
                    symbol= config.SYMBOL_DISPLAY
                    )
                atr_mul = ( entry * 0.0024 ) / atr
                if(prob >= 0.64):
                    stop_loss = entry+(atr * atr_mul )
                    take_profit = entry - 10* atr
                    position = {
                        "side" : "SHORT",
                        "entry" : candle["Close"],
                        "stop_loss" : stop_loss,
                        "take_profit" : take_profit
                    }
                else:
                    # db.mark_baseline_candle_checked(baseline_id)
                    # thread_state["last_processed_ts"] = baseline_timestamp
                    # st.save_thread_state(thread_index, thread_state)
                    id = id + 1
                    counter = counter + 1
                    save_state(thread_state,counter)
                    continue
        
            position["symbol"] = config.SYMBOL_DISPLAY
            position["confidence"] = prob * 100
            pid = db.open_back_test_position(position,0,config.TRADING_TIME_FRAME,timestamp,thread_index,None)

            thread_state["open_position_id"] = pid
            thread_state["holding_candles"] = 0

        # db.mark_baseline_candle_checked(baseline_id)
        # thread_state["last_processed_ts"] = baseline_timestamp
        # st.save_thread_state(thread_index, thread_state)
        id = id + 1
        counter = counter + 1
        save_state(thread_state,counter)
        



# -----------------------------------------------------------------
# Progress bar
# -----------------------------------------------------------------
def _progress_bar_loop(stop_event: threading.Event) -> None:
    while not stop_event.is_set():
        checked, total = get_baseline_progress_mem()
        total = max(1, total - config.BACK_TEST_WARMUP_TRIM)
        pct = checked / total * 100
        filled = int(30 * checked / total)
        bar = "█" * filled + "-" * (30 - filled)
        sys.stdout.write(f"\r[{bar}] {checked}/{total} ({pct:.1f}%)")
        sys.stdout.flush()
        time.sleep(1)
    print()


# -----------------------------------------------------------------
# Public entry points
# -----------------------------------------------------------------
def start_backtest() -> None:
    load_global_data()
    timestamps = db.get_baseline_timestamps(trim=config.BACK_TEST_WARMUP_TRIM)
    chunks = st.split_ranges_into_chunks(timestamps, config.BACK_TEST_THREAD)
    thread_states = [
        st.init_thread_state(i, chunk[0], chunk[-1])
        for i, chunk in enumerate(chunks) if chunk
    ]
    _run_all(thread_states)


def full_start():
    db.reset_back_test_db(True)
    fetcher.get_historical_data()
    db.rebuild_baseline_from_historical(config.TRADING_TIME_FRAME)

    print("Enriching Data....(It Take Several Minutes)")
    candles = db.get_all_baseline()
    df_window = db.candles_to_dataframe(candles)
    df_window = enrich_dataframe(df_window)
    db.insert_enriched_dataframe(df_window,config.SYMBOL_DISPLAY,config.TRADING_TIME_FRAME)
    start_backtest()


def re_start():
    db.reset_back_test_db(False)
    db.rebuild_baseline_from_historical(config.TRADING_TIME_FRAME)
    start_backtest()


def resume_backtest() -> None:
    thread_states = []
    for i in range(config.BACK_TEST_THREAD):
        s = st.load_thread_state(i)
        if s is None or s["status"] == "done":
            continue
        thread_states.append(s)
    if not thread_states:
        print("No resumable backtest threads found.")
        return
    _run_all(thread_states)


def _run_all(thread_states: list[dict]) -> None:
    stop_event = threading.Event()
    progress_thread = threading.Thread(
        target=_progress_bar_loop, args=(stop_event,), daemon=True
    )
    progress_thread.start()

    threads = [
        threading.Thread(target=run_thread, args=(s,))
        for s in thread_states
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    stop_event.set()
    progress_thread.join()
    print("Backtest complete.")