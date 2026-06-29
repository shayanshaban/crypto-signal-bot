from pathlib import Path
import requests
import config

# ==========================
# Configuration
# ==========================
SYMBOL = "BTCUSDT"

INTERVALS = [
    # "1m",
    # "3m",
    "5m",
    # "15m",
    # "30m",
    # "1h",
    # "2h",
    # "4h",
    # "6h",
    # "8h",
    # "12h",
    # "1d",
    # "3d",
    # "1w",
    # "1M",
]

START_YEAR = 2020
START_MONTH = 1

END_YEAR = 2026
END_MONTH = 5

BASE_URL = "https://data.binance.vision/data/futures/um/monthly/klines"

OUTPUT_DIR = Path(config.IMPORT_DATA_FOLDER_DIR)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

session = requests.Session()

for interval in INTERVALS:
    print(f"\n========== {interval} ==========")

    for year in range(START_YEAR, END_YEAR + 1):
        for month in range(1, 13):

            if year == START_YEAR and month < START_MONTH:
                continue

            if year == END_YEAR and month > END_MONTH:
                break

            month_str = f"{month:02d}"

            filename = f"{SYMBOL}-{interval}-{year}-{month_str}.zip"

            url = (
                f"{BASE_URL}/"
                f"{SYMBOL}/"
                f"{interval}/"
                f"{filename}"
            )

            output_file = OUTPUT_DIR / filename

            if output_file.exists():
                print(f"[SKIP] {filename}")
                continue

            print(f"[DOWNLOAD] {filename}")

            try:
                response = session.get(url, timeout=30)

                if response.status_code == 200:
                    output_file.write_bytes(response.content)
                    print("    ✓ Done")

                elif response.status_code == 404:
                    print("    ✗ Not Found")

                else:
                    print(f"    ✗ HTTP {response.status_code}")

            except Exception as e:
                print(f"    ✗ {e}")

print("\n✅ All downloads completed.")