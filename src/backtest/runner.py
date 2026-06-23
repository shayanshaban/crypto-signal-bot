"""
src/backtest/runner.py — backtest orchestration: thread workers, progress bar.
Now with Rule Engine, LLM Confirmation, and ML Dataset Collection.
"""

import sys
import threading
import time

import config
from src.data import fetcher
from src.ai.llm_confirmer import LLMConfirmer      # NEW
from src.db import manager as db
from src.backtest import state as st
from src.trading.rule_engine import RuleEngine     # NEW
from src.ml.feature_engineering import FeatureExtractor   # NEW
from src.ml.triple_barrier import TripleBarrierLabeler, TradeRecord  # NEW
from src.ml.dataset_storage import DatasetStorage   # NEW


# --- Global instances (initialized once) ---
# Since run_thread is called per thread, we can share these across threads (they are stateless)
_rule_engine = RuleEngine()
_llm_confirmer = LLMConfirmer()
_feature_extractor = FeatureExtractor()
_labeler = TripleBarrierLabeler(max_holding_bars=config.MAX_HOLDING_BARS)
_dataset_storage = DatasetStorage(config.DATASET_DIR)


def run_thread(thread_state: dict) -> None:
    """
    Modified run_thread that uses Rule Engine + LLM Confirmation + ML dataset.
    """
    thread_index = thread_state["thread_index"]
    start_id, end_id = thread_state["start_id"], thread_state["end_id"]

    # We'll reuse a single session per thread (like before)
    with _llm_confirmer.session as session:   # LLMConfirmer holds a session
        while True:
            open_pos = db.get_open_position_for_thread(thread_index)
            candle   = db.get_next_baseline_candle_in_range(start_id, end_id)

            if candle is None:
                thread_state["status"] = "done"
                st.save_thread_state(thread_index, thread_state)
                return

            # -----------------------------------------------------------------
            # 1. MANAGE OPEN POSITIONS (SL/TP check)
            # -----------------------------------------------------------------
            if open_pos is not None:
                closed = db.check_position_tp_sl(open_pos["id"], candle)
                if closed:
                    # ---------------------------------------------------------
                    # 2. CLOSE POSITION -> LABEL & STORE IN DATASET
                    # ---------------------------------------------------------
                    # Retrieve full position details (including entry, SL, TP)
                    pos = db.get_position(open_pos["id"])  # you may need to implement this
                    # Build TradeRecord
                    trade_record = TradeRecord(
                        symbol=pos['symbol'],
                        side=pos['position'],
                        entry_price=pos['entry'],
                        stop_loss=pos['stop_loss'],
                        take_profit=pos['take_profit'],
                        entry_timestamp=pos['entry_timestamp'],  # store this in DB
                        exit_timestamp=candle['Timestamp'],
                        exit_price=candle['Close'],  # approximate exit price
                        holding_candles=0,  # compute if you have entry index
                    )
                    # Load historical data slice for labeling
                    # We need a DataFrame from entry to exit; you can fetch from DB or from cache.
                    # For simplicity, we assume you have a function to get candles between timestamps.
                    df_slice = db.get_candles_between(pos['entry_timestamp'], candle['Timestamp'])
                    label = _labeler.label_trade(trade_record, df_slice)

                    # Retrieve stored features (you need to store them when opening)
                    features = db.get_position_features(pos['id'])  # you'll store this in a separate table

                    # Store in Parquet
                    candidate = reconstruct_candidate_from_position(pos)  # helper below
                    _dataset_storage.store_trade(
                        candidate=candidate,
                        trade_record=trade_record,
                        features=features,
                        label=label,
                        df=df_slice
                    )

                    thread_state["open_position_id"] = None

            # -----------------------------------------------------------------
            # 3. DETECT NEW SETUPS (only if no open position)
            # -----------------------------------------------------------------
            else:
                # Get candle window (just like before)
                candle_window = db.get_candles_for_trigger(
                    candle["Timestamp"], config.TRADING_TIME_FRAME
                )
                # Convert candle_window to DataFrame (assuming you have a utility)
                df_window = db.candles_to_dataframe(candle_window)

                # Run Rule Engine
                symbol = config.SYMBOL_DISPLAY # or from config
                timeframe = config.TRADING_TIME_FRAME
                candidates = _rule_engine.detect_setups(df_window, symbol, timeframe)

                # Filter with LLM Confirmation
                for candidate in candidates:
                    if _llm_confirmer.confirm(candidate, session=session):  # use existing session
                        # Extract features for ML
                        features = _feature_extractor.extract(candidate, df_window)

                        # Open position
                        pos_id = db.open_back_test_position(
                            {
                                'symbol': candidate.symbol,
                                'position': candidate.side,
                                'entry': candidate.entry_price,
                                'stop_loss': candidate.stop_loss,
                                'take_profit': candidate.take_profit,
                                'confidence': 100,
                                'reason': f"Rule: {candidate.setup_type.value}",
                            },
                            signal_id=None,  # we don't have a signal_id anymore
                            timeframe=timeframe,
                            entry_timestamp=candle["Timestamp"],
                            thread_index=thread_index,
                        )
                        # Store features and setup_type alongside the position
                        db.store_position_features(pos_id, features, candidate.setup_type.value)
                        thread_state["open_position_id"] = pos_id
                        break  # only one position at a time

                    # Optional: wait between LLM calls to avoid rate limits
                    time.sleep(config.BACK_TEST_WAIT_AFTER_ASK_AI)

            # Mark candle as processed
            db.mark_baseline_candle_checked(candle["id"])
            thread_state["last_processed_id"] = candle["id"]
            st.save_thread_state(thread_index, thread_state)


# -----------------------------------------------------------------
# Helper function to reconstruct a SetupCandidate from DB position
# (used when labeling a closed trade)
# -----------------------------------------------------------------
def reconstruct_candidate_from_position(pos: dict):
    from src.trading.rule_engine import SetupCandidate, SetupType
    return SetupCandidate(
        setup_type=SetupType(pos.get('setup_type', 'unknown')),
        symbol=pos['symbol'],
        side=pos['position'],
        timeframe=pos.get('timeframe', '1m'),
        entry_price=pos['entry'],
        stop_loss=pos['stop_loss'],
        take_profit=pos['take_profit'],
        features={},  # not needed for labeling
        timestamp=pos['entry_timestamp']
    )


# -----------------------------------------------------------------
# (Keep existing functions: read_prompt_file, progress bar, etc.)
# -----------------------------------------------------------------
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
    db.reset_back_test_db(True)
    fetcher.get_historical_data()
    start_backtest()


def re_start():
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