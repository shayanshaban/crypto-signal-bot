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
from src.ml.dataset_storage import save_market_snapshot,save_market_snapshots_batch
from src.data.baker import calculate_reward_r
import bisect
import pandas as pd
import queue


snapshot_queue = queue.Queue(maxsize=0)
writer_stop_event = threading.Event()
BATCH_SIZE = 100_000

def writer_loop():
    buffer = []
    while not writer_stop_event.is_set() or not snapshot_queue.empty():
        try:
           
            item = snapshot_queue.get(timeout=0.5)
            buffer.append(item)
            if len(buffer) >= BATCH_SIZE:
                _flush_buffer(buffer)
                buffer.clear()
        except queue.Empty:
            if buffer:
                _flush_buffer(buffer)
                buffer.clear()

    if buffer:
        _flush_buffer(buffer)

def _flush_buffer(buf):
    save_market_snapshots_batch(buf)

def load_global_data():
    global enriched_candels, enriched_timestamps
    global base_line_candels, base_line_timestamps

    enriched_rows = db.get_all_enriched_candels()
    enriched_candels = db.enriched_rows_to_dataframe(enriched_rows)
    enriched_candels = enriched_candels.sort_values("timestamp").reset_index(drop=True)
    enriched_timestamps = enriched_candels["timestamp"].tolist()

    base_line_candels = sorted(db.get_all_baseline(), key=lambda x: x["Timestamp"])
    base_line_timestamps = [c["Timestamp"] for c in base_line_candels]

global _checked_ids
_checked_ids = set()
global _check_lock
_check_lock = threading.Lock()

file_lock = threading.Lock()

def flush_snapshots(buffer: list, lock: threading.Lock):
    if not buffer:
        return
    with lock:
        for args in buffer:
            # args = (df_window, symbol, timeframe, timestamp, side, result_r)
            save_market_snapshot(*args)
    buffer.clear()

def get_enriched_window_mem(baseline_timestamp: int, window_size: int = 50) -> pd.DataFrame:
    
    idx = bisect.bisect_right(enriched_timestamps, baseline_timestamp) - 1
    if idx < 0:
        return pd.DataFrame()  
    
    start_idx = max(0, idx - window_size + 1)
    return enriched_candels.iloc[start_idx : idx + 1].copy(deep=True)

# def get_next_baseline_candle_in_range_mem(start_ts: int, end_ts: int) -> dict | None:
   
#     idx = bisect.bisect_left(base_line_timestamps, start_ts)
           
#     for i in range(idx, len(base_line_candels)):
#         candle = base_line_candels[i]
#         ts = candle["Timestamp"]
#         if ts > end_ts:
#             break                          
#         if candle["id"] not in _checked_ids:
#             _checked_ids.add(candle["id"])
#             return candle
#     return None
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

def get_future_candles_mem(start_timestamp: int, limit: int = 1000) -> list[dict]:
    """
    Return up to `limit` candles with Timestamp > start_timestamp,
    using the in-memory sorted list (no database).
    """
    
    idx = bisect.bisect_right(base_line_timestamps, start_timestamp)
    return base_line_candels[idx:idx + limit]


def check_positions(long_pos: dict, short_pos: dict, future_candles: list[dict]) -> tuple[float, float]:
    """
    با یک بار پیمایش کندل‌های آینده، نقطه خروج برای هر دو موقعیت LONG و SHORT را مشخص می‌کند.
    اگر حد ضرر یا سود هیچ‌کدام لمس نشود، مطابق منطق قبلی، حد ضرر برگردانده می‌شود.
    (می‌توان این پیش‌فرض را به قیمت بسته‌شدن آخرین کندل تغییر داد)
    """
    long_exit = None
    short_exit = None

    for candle in future_candles:
        # بررسی موقعیت LONG (اگر هنوز خروجش مشخص نشده)
        if long_exit is None:
            if candle["Low"] <= long_pos["stop_loss"]:
                long_exit = long_pos["stop_loss"]
            elif candle["High"] >= long_pos["take_profit"]:
                long_exit = long_pos["take_profit"]

        # بررسی موقعیت SHORT (اگر هنوز خروجش مشخص نشده)
        if short_exit is None:
            if candle["High"] >= short_pos["stop_loss"]:
                short_exit = short_pos["stop_loss"]
            elif candle["Low"] <= short_pos["take_profit"]:
                short_exit = short_pos["take_profit"]

        # اگر هر دو خروج مشخص شد، ادامه دادن بی‌فایده است
        if long_exit is not None and short_exit is not None:
            break

    # مقدار پیش‌فرض (مطابق رفتار قبلی: حد ضرر)
    if long_exit is None:
        long_exit = long_pos["stop_loss"]
    if short_exit is None:
        short_exit = short_pos["stop_loss"]

    return long_exit, short_exit

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
    index = 0
    while True:
        
        candle = get_next_baseline_candle_in_range_mem(id,start_id,end_id)
        # candle = get_next_baseline_candle_in_range_mem(start_ts, end_ts)
        if candle is None:
            thread_state["status"] = "done"
            st.save_thread_state(thread_index, thread_state)
            return
        baseline_timestamp = candle["Timestamp"]
        baseline_id = candle["id"]
        timestamp = candle["Timestamp"]
           
        if index > 0:
            # db.mark_baseline_candle_checked(baseline_id)counter = counter + 1
            index = index - 1 
            thread_state["last_processed_ts"] = baseline_timestamp
            # st.save_thread_state(thread: int_index, thread_state)
            save_state(thread_state,counter)
            id = id + 1
            counter = counter + 1
            index = index - 1 
            continue

        df_window = get_enriched_window_mem(timestamp, 5)
       
        atr = df_window.iloc[-1]["atr14"]

        if atr is None or atr == 0:
            id = id + 1
            counter = counter + 1
            index = index - 1 
            continue

        entry = candle["Close"]
        stop_distance = max(
            atr * config.ATR_MULTIPLIER,
            entry * config.MIN_STOP_PERCENT
        )
        profit_distance = stop_distance * config.RR

        

        future_candles = get_future_candles_mem(baseline_timestamp,1000)
        stop_loss = entry - stop_distance
        take_profit = entry + profit_distance

        long_pos = {
            "side" : "LONG",
            "entry" : candle["Close"],
            "stop_loss" : stop_loss,
            "take_profit" : take_profit
        }

        stop_loss = entry + stop_distance
        take_profit = entry - profit_distance

        short_pos = {
            "side" : "SHORT",
            "entry" : candle["Close"],
            "stop_loss" : stop_loss,
            "take_profit" : take_profit
        }


        long_exit_price, short_exit_price = check_positions(long_pos, short_pos, future_candles)
        
        result_r = calculate_reward_r(
            long_pos["side"],
            long_pos["entry"],
            long_exit_price,
            long_pos["stop_loss"])
        
        
        snapshot_queue.put((df_window, config.SYMBOL_DISPLAY, config.TRADING_TIME_FRAME,
                    timestamp, long_pos["side"], result_r))
        
        
        result_r = calculate_reward_r(
            short_pos["side"],
            short_pos["entry"],
            short_exit_price,
            short_pos["stop_loss"])
        
        
        snapshot_queue.put((df_window, config.SYMBOL_DISPLAY, config.TRADING_TIME_FRAME,
                    timestamp, short_pos["side"], result_r))
        
        
        # db.mark_baseline_candle_checked(baseline_id)
        thread_state["last_processed_ts"] = baseline_timestamp
        # st.save_thread_state(thread_index, thread_state)
        save_state(thread_state,counter)
        index = 3
        counter = counter + 1
        id = id + 1



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
def start_dataset_builder() -> None:
    load_global_data()
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
    load_global_data()
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
   
    writer_thread = threading.Thread(target=writer_loop, daemon=True)
    writer_thread.start()

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

    global enriched_candels, enriched_timestamps
    global base_line_candels, base_line_timestamps

    del enriched_candels
    del enriched_timestamps
    del base_line_candels
    del base_line_timestamps

    import gc
    gc.collect()


    
    writer_stop_event.set()
    writer_thread.join()

    stop_event.set()
    progress_thread.join()
    print("Dataset builder complete.")