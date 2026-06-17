"""
src/trading/signal_handler.py — Parse and act on AI-generated signals.

All business logic for deciding what to do with a signal sits here,
keeping main.py clean and this layer independently testable.

Public API:
  parse(raw_text)            — clean + parse JSON, return dict or None
  evaluate(signal)           — decide: OPEN / SKIP / NO_TRADE
  process(raw_text)          — full pipeline: parse → save → evaluate → open
"""

import json
import re

import config
from src.db import manager as db


# ── Parsing ───────────────────────────────────────────────────────────────────

def parse(raw_text: str) -> dict | None:
    """
    Extract a JSON object from the AI response.
    Strips markdown fences DeepSeek sometimes wraps around the output.
    Returns the parsed dict, or None if parsing fails.
    """
    text = raw_text.strip()

    # Strip ```json … ``` or ``` … ``` fences
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$",          "", text)

    # Find the first {...} block in case there's any extra prose
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None

    try:
        return json.loads(match.group())
    except json.JSONDecodeError:
        return None


# ── Evaluation ────────────────────────────────────────────────────────────────

DECISION_OPEN     = "OPEN"
DECISION_SKIP     = "SKIP"
DECISION_NO_TRADE = "NO_TRADE"


def evaluate(signal: dict) -> tuple[str, str]:
    """
    Decide what to do with a parsed signal.
    Returns (decision, reason_string).

    Decisions:
      OPEN      — all checks passed, open a position
      SKIP      — valid signal but below confidence threshold
      NO_TRADE  — AI returned NO_TRADE
    """
    direction  = signal.get("position", "NO_TRADE")
    confidence = signal.get("confidence", 0)

    if direction == "NO_TRADE":
        return DECISION_NO_TRADE, "AI returned NO_TRADE"

    if confidence < config.MIN_CONFIDENCE:
        return DECISION_SKIP, f"Confidence {confidence} < minimum {config.MIN_CONFIDENCE}"

    if db.has_open_position(signal.get("symbol")):
        return DECISION_SKIP, f"Position already open for {signal.get('symbol')}"

    return DECISION_OPEN, f"{direction} @ {signal.get('entry')} — confidence {confidence}"


# ── Full pipeline ─────────────────────────────────────────────────────────────

def process(raw_text: str) -> dict:
    """
    Full pipeline:
      1. Parse the raw AI text into a signal dict
      2. Save the raw response to the signals table
      3. Evaluate whether to open a position
      4. Open the position if appropriate
      5. Return a result dict with all info

    Returns:
      {
        "parsed":    dict | None,
        "signal_id": int  | None,
        "decision":  str,
        "reason":    str,
        "pos_id":    int  | None,
      }
    """
    result = {
        "parsed":    None,
        "signal_id": None,
        "decision":  DECISION_NO_TRADE,
        "reason":    "",
        "pos_id":    None,
    }

    # 1. Parse
    parsed = parse(raw_text)
    if parsed is None:
        result["reason"] = "Failed to parse AI response as JSON"
        return result
    result["parsed"] = parsed

    # 2. Save signal
    signal_id = db.save_signal(raw_text, parsed)
    result["signal_id"] = signal_id

    # 3. Evaluate
    decision, reason = evaluate(parsed)
    result["decision"] = decision
    result["reason"]   = reason

    # 4. Open if appropriate
    if decision == DECISION_OPEN:
        pos_id = db.open_position(parsed, signal_id=signal_id)
        result["pos_id"] = pos_id

    return result
