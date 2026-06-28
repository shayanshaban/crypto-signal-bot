import json
import zipfile
from pathlib import Path

import pandas as pd

import config
from src.data.baker import enrich_dataframe
from src.db import manager as db


STATE_FILE = "import_state.json"


def load_import_state(folder):
    folder = Path(folder)
    state_path = folder / STATE_FILE

    if not state_path.exists():
        return set()

    with state_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    return set(data.get("imported_files", []))


def save_import_state(folder, imported):
    folder = Path(folder)
    state_path = folder / STATE_FILE

    with state_path.open("w", encoding="utf-8") as f:
        json.dump(
            {"imported_files": sorted(imported)},
            f,
            indent=4,
        )


folder = config.IMPORT_DATA_FOLDER_DIR


def import_zip_folder(folder: str):
    folder = Path(folder)
    imported = load_import_state(folder)

    for zip_path in folder.glob("*.zip"):
        if zip_path.name in imported:
            print(f"Skip {zip_path.name}")
            continue

        print(f"Importing {zip_path.name}")

        with zipfile.ZipFile(zip_path) as z:
            csv_name = next(name for name in z.namelist() if name.endswith(".csv"))

            with z.open(csv_name) as f:
                # بدون فرض وجود هدر بخوان
                df = pd.read_csv(f, header=None)

                # اگر فایل هدر داشته باشد
                if str(df.iloc[0, 0]).strip().lower() == "open_time":
                    df.columns = df.iloc[0]
                    df = df.iloc[1:].reset_index(drop=True)
                    df = df[
                        ["open_time", "open", "high", "low", "close", "volume"]
                    ]
                else:
                    # فایل هدر ندارد
                    df = df.iloc[:, :6]
                    df.columns = [
                        "open_time",
                        "open",
                        "high",
                        "low",
                        "close",
                        "volume",
                    ]

        candles = [
            (
                int(row.open_time) // 1000,
                float(row.open),
                float(row.high),
                float(row.low),
                float(row.close),
                float(row.volume),
            )
            for row in df.itertuples(index=False)
        ]

        db.save_historical_candel(
            candles,
            config.TRADING_TIME_FRAME,
        )

        imported.add(zip_path.name)
        save_import_state(folder, imported)

        print(f"Saved {len(candles)} candles")

    db.rebuild_baseline_from_historical(config.TRADING_TIME_FRAME)

    print("Enriching Data.... (It Takes Several Minutes)")
    candles = db.get_all_baseline()
    df_window = db.candles_to_dataframe(candles)
    df_window = enrich_dataframe(df_window, True)
    db.insert_enriched_dataframe(
        df_window,
        config.SYMBOL_DISPLAY,
        config.TRADING_TIME_FRAME,
    )