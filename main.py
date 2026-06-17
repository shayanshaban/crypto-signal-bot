"""
main.py — Entry point for the crypto signal bot.

Usage:
    python main.py

Flow:
  1. Fetch multi-timeframe market data from LBank → output/market_data.txt
  2. Send the assembled prompt to DeepSeek and capture the trading signal
  3. Print the signal and append it to logs/signals.log
"""

import sys
import json
from pathlib import Path

# Make sure src/ is importable when running from the project root
sys.path.insert(0, str(Path(__file__).parent))

import config
from src import data_fetcher, deepseek_client


def main() -> None:
    print("── Step 1: Fetching market data …")
    data_fetcher.fetch_data(config.PROMPT_FILE)
    print(f"   Data written to {config.OUTPUT_FILE!r}")

    print("── Step 2: Requesting trading signal from DeepSeek …")
    signal = deepseek_client.run_from_file(config.OUTPUT_FILE)

    if not signal:
        print("ERROR: No response received from DeepSeek.", file=sys.stderr)
        sys.exit(1)

    # Pretty-print if the response is valid JSON (it should be)
    try:
        parsed = json.loads(signal)
        print("\n── Signal ──────────────────────────────────────")
        print(json.dumps(parsed, indent=2))
    except json.JSONDecodeError:
        print("\n── Raw response (not valid JSON) ───────────────")
        print(signal)

    # Append to log
    Path(config.LOG_FILE).parent.mkdir(parents=True, exist_ok=True)
    with open(config.LOG_FILE, "a", encoding="utf-8") as log:
        log.write(signal + "\n")
    print(f"\n   Signal appended to {config.LOG_FILE!r}")


if __name__ == "__main__":
    main()
