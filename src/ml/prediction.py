from pathlib import Path

import pandas as pd
from catboost import CatBoostClassifier

import config

# نگاشت نام ستون‌های دیتافریم به نام‌های مورد انتظار مدل
DF_TO_DB_MAP = {v: k for k, v in config.FEUTURES.items()}

MODEL_PATH = Path(config.MODEL_SAVE_PATH) / "long_short_depth10_auc0.6014_1.06M.cbm"

TARGET = "is_win"

# این لیست را می‌توان در صورتی که مدل فقط ستون‌های خاصی را می‌پذیرد حذف کرد
DROP_COLUMNS = [
    "sample_id",
    "status",
    "result_r",
    "candle_ts",
    "timestamp",
    "id",
    "candle_id",
    "macd_signal",
    "macd_histogram",
    TARGET,
]


class WinProbabilityModel:
    def __init__(self):
        self.model = CatBoostClassifier()
        self.model.load_model(MODEL_PATH)
        # ذخیره‌ی ویژگی‌های مورد انتظار مدل برای سرعت و یکسان‌سازی
        self.expected_features = self.model.feature_names_

    def predict_probability(self, enriched_data: pd.DataFrame, side: str,timeframe :str,symbol) -> float:
        """
        Parameters
        ----------
        enriched_data : pd.DataFrame
            خروجی enrich_dataframe (حداقل شامل کندل جاری)
        side : str
            "LONG" یا "SHORT"

        Returns
        -------
        float
            احتمال WIN بین 0 و 1
        """
        
        df = enriched_data.tail(1).copy()

        
        df = df.rename(columns=DF_TO_DB_MAP)

        
        df["side"] = side
        df["symbol"] = symbol
        df["timeframe"] = timeframe

        
        categorical_fill = [
            "engulfing",
            "rsi_zone",
            "stoch_rsi_zone",
            "macd_position",
            "volume_signal",
            "bb_signal",
            "bb_squeeze",
            "market_structure",
            "candle_type",
            "last_3_candles",
            "session",
        ]

        for col in categorical_fill:
            if col in df.columns:
                df[col] = df[col].fillna("unknown")

        if "distance_to_support_pct" in df.columns:
            df["has_support"] = df["distance_to_support_pct"].notna().astype("int8")
            df["distance_to_support_pct"] = df["distance_to_support_pct"].fillna(-1.0)

        if "distance_to_resistance_pct" in df.columns:
            df["has_resistance"] = df["distance_to_resistance_pct"].notna().astype("int8")
            df["distance_to_resistance_pct"] = df["distance_to_resistance_pct"].fillna(-1.0)

        
        for col in DROP_COLUMNS:
            if col in df.columns:
                df.drop(columns=col, inplace=True)

        
        missing = set(self.expected_features) - set(df.columns)
        if missing:
            raise ValueError(
                f"Missing columns for prediction: {missing}"
            )
        
        df = df[self.expected_features]

        probability = self.model.predict_proba(df)[0][1]
        return float(probability)


# Singleton
predictor = WinProbabilityModel()