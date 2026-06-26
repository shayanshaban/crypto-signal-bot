"""
src/backtest/runner.py — backtest orchestration: thread workers, progress bar.
"""

import sys
import threading
import time

import config
from src.data import fetcher
from src.ai.llm_confirmer import LLMConfirmer
from src.db import manager as db
from src.backtest import state as st
from src.trading.rule_engine import RuleEngine, SetupCandidate, SetupType
from src.ml.feature_engineering import FeatureExtractor
from src.ml.triple_barrier import TripleBarrierLabeler, TradeRecord
from src.ml.dataset_storage import save_sample
from src.data.baker import enrich_dataframe
from src.data.baker import calculate_reward_r


def _make_per_thread_resources():
    """هر thread منابع مستقل خودش رو داره — thread-safe"""
    return {
        "rule_engine": RuleEngine(),
        "llm_confirmer": LLMConfirmer(),
        "feature_extractor": FeatureExtractor(),
        "labeler": TripleBarrierLabeler(max_holding_bars=config.MAX_HOLDING_BARS),
    }

MAX_HOLDING_CANDLES = 20 
TARGET_SETUP = SetupType.RSI_DIVERGENCE
def run_thread(thread_state: dict) -> None:
    thread_index = thread_state["thread_index"]
    start_id = thread_state["start_id"]
    end_id = thread_state["end_id"]

    # هر thread منابع جداگانه داره
    res = _make_per_thread_resources()
    rule_engine = res["rule_engine"]
    llm_confirmer = res["llm_confirmer"]
    feature_extractor = res["feature_extractor"]
    labeler = res["labeler"]


    while True:
        candle = db.get_next_baseline_candle_in_range(start_id, end_id)
        if candle is None:
            thread_state["status"] = "done"
            st.save_thread_state(thread_index, thread_state)
            return
        # candle_window = db.get_candles_for_trigger(
        #     candle["Timestamp"], config.TRADING_TIME_FRAME,500)
        row = db.get_enriched_window(candle["id"],500)
        df_window = db.enriched_rows_to_dataframe(row)
        # df_window = enrich_dataframe(df_window)
        candidates = rule_engine.detect_setups(
            df_window, config.SYMBOL_DISPLAY, config.TRADING_TIME_FRAME
        )
        baseline_id = candle["id"]
        timestamp = candle["Timestamp"]
        for candidate in candidates:

        # candidate = next(
        #     (c for c in candidates if c.setup_type == TARGET_SETUP),
        #     None
        # )

            if candidate is None:
                continue
            
            pos_id = db.open_back_test_position(
                        {
                            "symbol": candidate.symbol,
                            "position": candidate.side,
                            "entry": candidate.entry_price,
                            "stop_loss": candidate.stop_loss,
                            "take_profit": candidate.take_profit,
                            "confidence": 100,
                            "reason": f"Rule: {candidate.setup_type.value}",
                        },
                        signal_id=None,
                        timeframe=config.TRADING_TIME_FRAME,
                        entry_timestamp=candle["Timestamp"],
                        thread_index=thread_index,
                    )
            
            
            future_candles = db.get_future_candles(baseline_id)
            exit_price = None
            for candle in future_candles:

                if candidate.side == "LONG":

                    if candle["Low"] <= candidate.stop_loss:
                        exit_price = candidate.stop_loss
                        db.check_position_tp_sl(pos_id,candle)
                        break

                    if candle["High"] >= candidate.take_profit:
                        exit_price = candidate.take_profit
                        db.check_position_tp_sl(pos_id,candle)
                        break

                else:

                    if candle["High"] >= candidate.stop_loss:
                        exit_price = candidate.stop_loss
                        db.check_position_tp_sl(pos_id,candle)
                        break

                    if candle["Low"] <= candidate.take_profit:
                        exit_price = candidate.take_profit
                        db.check_position_tp_sl(pos_id,candle)
                        break

            if exit_price is None:
                exit_price = future_candles[-1]["Close"]
            
            result_r = calculate_reward_r(
                candidate.side,
                candidate.entry_price,
                exit_price,
                candidate.stop_loss)
            
            
            save_sample(
                df_window,
                config.SYMBOL_DISPLAY,
                config.TRADING_TIME_FRAME,
                timestamp,
                candidate.side,
                candidate.setup_type.value,
                result_r)
        
        db.mark_baseline_candle_checked(baseline_id)
        thread_state["last_processed_id"] = baseline_id
        st.save_thread_state(thread_index, thread_state)
        # if candle is None:
        #     thread_state["status"] = "done"
        #     st.save_thread_state(thread_index, thread_state)
        #     return

        # open_pos = db.get_open_position_for_thread(thread_index)

        # # -----------------------------------------------------------------
        # # 1. مدیریت position باز (چک SL/TP)
        # # -----------------------------------------------------------------
        # if open_pos is not None:
        #     holding_candles = thread_state.get("holding_candles", 0)

        #     if holding_candles >= MAX_HOLDING_CANDLES:
        #         db.close_position_at_market(open_pos["id"], candle)
        #         thread_state["holding_candles"] = 0
        #         thread_state["open_position_id"] = None
        #         closed = True
        #     else :   
        #         closed = db.check_position_tp_sl(open_pos["id"], candle)

        #     if closed:
        #         pos = db.get_position(open_pos["id"])

        #         # محاسبه holding_candles از DB
        #         holding_candles = thread_state.get("holding_candles", 0)

        #         trade_record = TradeRecord(
        #             symbol=pos["symbol"],
        #             side=pos["position"],
        #             entry_price=pos["entry"],
        #             stop_loss=pos["stop_loss"],
        #             take_profit=pos["take_profit"],
        #             entry_timestamp=pos["entry_timestamp"],
        #             exit_timestamp=candle["Timestamp"],
        #             exit_price=candle["Close"],
        #             holding_candles=holding_candles,
        #         )
        #         thread_state["holding_candles"] = 0

        #         df_slice = db.get_candles_between(
        #             pos["entry_timestamp"], candle["Timestamp"]
        #         )
        #         df_slice = df_slice.reset_index(drop=True)
        #         label = labeler.label_trade(trade_record, df_slice)
        #         features = db.get_position_features(pos["id"])
        #         candidate = _reconstruct_candidate(pos)

        #         dataset_storage.store_trade(
        #             candidate=candidate,
        #             trade_record=trade_record,
        #             features=features,
        #             label=label,
        #             df=df_slice,
        #         )

        #         thread_state["open_position_id"] = None
        #     else: 
        #         thread_state["holding_candles"] = thread_state.get("holding_candles", 0) + 1
        # # -----------------------------------------------------------------
        # # 2. پیدا کردن setup جدید (فقط وقتی position باز نداریم)
        # # -----------------------------------------------------------------
        # else:
        #     candle_window = db.get_candles_for_trigger(
        #         candle["Timestamp"], config.TRADING_TIME_FRAME,500)
        #     df_window = db.candles_to_dataframe(candle_window)
        #     # df_window = enrich_dataframe(df_window) 
        #     candidates = rule_engine.detect_setups(
        #         df_window, config.SYMBOL_DISPLAY, config.TRADING_TIME_FRAME
        #     )

        #     for candidate in candidates:
        #         # sleep قبل از LLM call — برای همه candidateها
        #         # time.sleep(config.BACK_TEST_WAIT_AFTER_ASK_AI)

        #         # confirmed = llm_confirmer.confirm(candidate)
        #         # if not confirmed:
        #         #     continue

        #         features = feature_extractor.extract(candidate, df_window)
        #         thread_state["holding_candles"] = 0 
        #         pos_id = db.open_back_test_position(
        #             {
        #                 "symbol": candidate.symbol,
        #                 "position": candidate.side,
        #                 "entry": candidate.entry_price,
        #                 "stop_loss": candidate.stop_loss,
        #                 "take_profit": candidate.take_profit,
        #                 "confidence": 100,
        #                 "reason": f"Rule: {candidate.setup_type.value}",
        #             },
        #             signal_id=None,
        #             timeframe=config.TRADING_TIME_FRAME,
        #             entry_timestamp=candle["Timestamp"],
        #             thread_index=thread_index,
        #         )

        #         db.store_position_features(pos_id, features, candidate.setup_type.value)
        #         thread_state["open_position_id"] = pos_id
        #         break  # فقط یه position در هر لحظه

        # پیشروی
        


def _reconstruct_candidate(pos: dict) -> SetupCandidate:
    return SetupCandidate(
        setup_type=SetupType(pos.get("setup_type", "unknown")),
        symbol=pos["symbol"],
        side=pos["position"],
        timeframe=pos.get("timeframe", config.TRADING_TIME_FRAME),
        entry_price=pos["entry"],
        stop_loss=pos["stop_loss"],
        take_profit=pos["take_profit"],
        features={},
        timestamp=pos["entry_timestamp"],
    )


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
def start_backtest() -> None:
    
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
    db.rebuild_baseline_from_historical(config.TRADING_TIME_FRAME)

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