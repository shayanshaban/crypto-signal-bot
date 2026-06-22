"""
src/backtest/runner.py — backtest orchestration: thread workers, progress bar.
"""

import sys
import threading
import time

import config
from src.data import fetcher
from src.ai import deepseek_client
from src.db import manager as db
from src.backtest import state as st
from src.trading       import signal_handler
from src.data.baker import should_ask_ai


def _parse_ai_response(raw: str) -> dict:
    """
    TODO: plug in your existing parser that turns the raw AI text
    into {symbol, position, confidence, entry, stop_loss, take_profit,
    risk_reward, reason}.
    """
    return signal_handler.parse(raw)


def run_thread(thread_state: dict) -> None:
    thread_index = thread_state["thread_index"]
    start_id, end_id = thread_state["start_id"], thread_state["end_id"]

    with deepseek_client.DeepSeekSession() as session:  
        while True:
            open_pos = db.get_open_position_for_thread(thread_index)
            candle   = db.get_next_baseline_candle_in_range(start_id, end_id)

            if candle is None:
                thread_state["status"] = "done"
                st.save_thread_state(thread_index, thread_state)
                return

            if open_pos is not None:
                closed = db.check_position_tp_sl(open_pos["id"], candle)
                if closed:
                    thread_state["open_position_id"] = None
            else:
                candle_window = db.get_candles_for_trigger(
                    candle["Timestamp"], config.TRADING_TIME_FRAME
                )
                if should_ask_ai(candle_window):
                    fetcher.fetch_data_for_back_test(candle["Timestamp"], thread_index)
                    result    = session.send_from_file(  
                        config.BACK_TEST_OUTPUT_FILES[thread_index]
                    )
                    raw       = result["response"]
                    chat_link = result["chat_link"]
                    parsed    = _parse_ai_response(raw)

                    signal_id = db.save_back_test_signal(
                        raw, parsed, chat_link=chat_link, thread_index=thread_index
                    )
                    if parsed.get("position") != "NO_TRADE":
                        pos_id = db.open_back_test_position(
                            parsed, signal_id=signal_id,
                            timeframe=config.TRADING_TIME_FRAME,
                            entry_timestamp=candle["Timestamp"],
                            thread_index=thread_index,
                        )
                        thread_state["open_position_id"] = pos_id
                    time.sleep(config.BACK_TEST_WAIT_AFTER_ASK_AI+(thread_index*(config.BACK_TEST_WAIT_AFTER_ASK_AI/2)))

            db.mark_baseline_candle_checked(candle["id"])
            thread_state["last_processed_id"] = candle["id"]
            st.save_thread_state(thread_index, thread_state)


def read_prompt_file(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _progress_bar_loop(stop_event: threading.Event) -> None:
    while not stop_event.is_set():
        checked, total = db.get_baseline_progress()
        total = total - config.BACK_TEST_WARMUP_TRIM
        pct = (checked / total * 100) if total else 0
        bar_len = 30
        filled = int(bar_len * checked / total) if total else 0
        bar = "█" * filled + "-" * (bar_len - filled)
        sys.stdout.write(f"\r[{bar}] {checked}/{total} ({pct:.1f}%)")
        sys.stdout.flush()
        time.sleep(1)
    print()


def start_backtest() -> None:
    db.rebuild_baseline_from_historical(config.TRADING_TIME_FRAME)

    ids = db.get_baseline_ids(trim=config.BACK_TEST_WARMUP_TRIM)
    chunks = st.split_ids_into_chunks(ids, config.BACK_TEST_THREAD)

    thread_states = [
        st.init_thread_state(i, chunk[0], chunk[-1])
        for i, chunk in enumerate(chunks) if chunk
    ]

    _run_all(thread_states)

def full_start():
    """
    Wipe all back test data including historical data and receieve it again from API
    """
    db.reset_back_test_db(True)
    fetcher.get_historical_data()
    start_backtest()

def re_start():
    """
    Wipe position and signals and re-test from current historical data
    """
    db.reset_back_test_db(False)
    start_backtest()


def resume_backtest() -> None:
    thread_states = []
    for i in range(config.BACK_TEST_THREAD):
        s = st.load_thread_state(i)
        if s is None:
            continue
        if s["status"] == "done":
            continue
        thread_states.append(s)

    if not thread_states:
        print("No resumable backtest threads found.")
        return

    _run_all(thread_states)


def _run_all(thread_states: list[dict]) -> None:
    stop_event = threading.Event()
    progress_thread = threading.Thread(target=_progress_bar_loop, args=(stop_event,), daemon=True)
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