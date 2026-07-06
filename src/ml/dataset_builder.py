"""
src/ml/dataset_builder.py — dataset_builder orchestration: thread workers, progress bar.
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

def run_thread(thread_state: dict) -> None:
    thread_index = thread_state["thread_index"]
    start_ts = thread_state["start_ts"]
    end_ts = thread_state["end_ts"]

    # هر thread منابع جداگانه داره
    # res = _make_per_thread_resources()
    # rule_engine = res["rule_engine"]
    # llm_confirmer = res["llm_confirmer"]
    # feature_extractor = res["feature_extractor"]
    # labeler = res["labeler"]

    index = 0
    while True:
        candle = db.get_next_baseline_candle_in_range(start_ts, end_ts)
        if candle is None:
            thread_state["status"] = "done"
            st.save_thread_state(thread_index, thread_state)
            return
        baseline_timestamp = candle["Timestamp"]
        baseline_id = candle["id"]
        timestamp = candle["Timestamp"]
           
        if index > 0:
            db.mark_baseline_candle_checked(baseline_id)
            thread_state["last_processed_ts"] = baseline_timestamp
            st.save_thread_state(thread_index, thread_state)
            index = index - 1 
            continue

        row = db.get_enriched_window(candle["id"],50)
        df_window = db.enriched_rows_to_dataframe(row)
       
        atr = df_window.iloc[-1]["atr14"]

        if atr is None or atr == 0:
            continue

        entry = candle["Close"]

        stop_loss = entry - 1.5 * atr
        take_profit = entry + 3.0 * atr
        future_candles = db.get_future_candles(baseline_timestamp,1000)
        exit_price = None
        position = {
            "side" : "LONG",
            "entry" : candle["Close"],
            "stop_loss" : stop_loss,
            "take_profit" : take_profit
        }

        exit_price = check_position(position,future_candles)
        
        result_r = calculate_reward_r(
            position["side"],
            position["entry"],
            exit_price,
            position["stop_loss"])
        
        
        save_market_snapshot(
            df_window,
            config.SYMBOL_DISPLAY,
            config.TRADING_TIME_FRAME,
            timestamp,
            position["side"],
            result_r)
        
        stop_loss = entry + 1.5 * atr
        take_profit = entry - 3.0 * atr

        position = {
            "side" : "SHORT",
            "entry" : candle["Close"],
            "stop_loss" : stop_loss,
            "take_profit" : take_profit
        }

        exit_price = check_position(position,future_candles)
        
        result_r = calculate_reward_r(
            position["side"],
            position["entry"],
            exit_price,
            position["stop_loss"])
        
        
        save_market_snapshot(
            df_window,
            config.SYMBOL_DISPLAY,
            config.TRADING_TIME_FRAME,
            timestamp,
            position["side"],
            result_r)
        
        db.mark_baseline_candle_checked(baseline_id)
        thread_state["last_processed_ts"] = baseline_timestamp
        st.save_thread_state(thread_index, thread_state)
        index = 3



# -----------------------------------------------------------------
# Progress bar
# -----------------------------------------------------------------
def _progress_bar_loop(stop_event: threading.Event) -> None:
    while not stop_event.is_set():
        checked, total = db.get_baseline_progress()
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
def start_dataset_builder() -> None:
    
    timestamps = db.get_baseline_timestamps(trim=config.BACK_TEST_WARMUP_TRIM)
    chunks = st.split_ranges_into_chunks(timestamps, config.BACK_TEST_THREAD)
    thread_states = [
        st.init_thread_state(i, chunk[0], chunk[-1])
        for i, chunk in enumerate(chunks) if chunk
    ]
    _run_all(thread_states)


def start():
    db.reset_back_test_db(False)
    db.rebuild_baseline_from_historical(config.TRADING_TIME_FRAME)
    start_dataset_builder()


def resume_dataset_builder() -> None:
    thread_states = []
    for i in range(config.BACK_TEST_THREAD):
        s = st.load_thread_state(i)
        if s is None or s["status"] == "done":
            continue
        thread_states.append(s)
    if not thread_states:
        print("No resumable dataset builder threads found.")
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
    print("Dataset builder complete.")