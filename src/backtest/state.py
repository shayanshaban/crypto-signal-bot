"""
src/backtest/state.py — per-thread JSON state persistence for resumable backtests.
"""

import json
from pathlib import Path

import config


def init_thread_state(thread_index: int, start_ts: int, end_ts: int) -> dict:
    state = {
        "thread_index": thread_index,
        "start_ts": start_ts,
        "end_ts": end_ts,
        "last_processed_ts": None,
        "open_position_id": None,
        "status": "running",
    }
    save_thread_state(thread_index, state)
    return state


def save_thread_state(thread_index: int, state: dict) -> None:
    path = Path(config.BACK_TEST_STATE_FILES[thread_index])
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def load_thread_state(thread_index: int) -> dict | None:
    path = Path(config.BACK_TEST_STATE_FILES[thread_index])
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def split_ranges_into_chunks(ids: list[int], n_threads: int) -> list[list[int]]:
    """Split a sorted timestamp list into n contiguous chunks."""
    chunk_size = len(ids) // n_threads
    chunks = []
    for i in range(n_threads):
        start = i * chunk_size
        end = (i + 1) * chunk_size if i < n_threads - 1 else len(ids)
        chunks.append(ids[start:end])
    return chunks