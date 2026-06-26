import zipfile
from pathlib import Path

import pandas as pd

import config
from src.db            import manager as db
import json
from pathlib import Path

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
            indent=4
        )

folder = config.IMPORT_DATA_FOLDER_DIR


def import_zip_folder(folder: str):
    folder = Path(folder)
    imported = load_import_state(folder)
    for zip_path in folder.glob("*.zip"):
        print(f"Importing {zip_path.name}")

        with zipfile.ZipFile(zip_path) as z:

            csv_name = next(name for name in z.namelist() if name.endswith(".csv"))

            with z.open(csv_name) as f:
                df = pd.read_csv(f)

        
        candles = [
            (
                int(row.open_time) // 1000,   # timestamp -> second
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
            config.TRADING_TIME_FRAME
        )
        imported.add(zip_path.name)
        save_import_state(folder, imported)

        print(f"Saved {len(candles)} candles")