import pandas as pd
import config

DATASET1_FILE = config.DATASET_DIR + "/ml_dataset_v2_1m.csv"
DATASET2_FILE = config.DATASET_DIR + "/ml_dataset_v2.csv"
DATASET3_FILE = config.DATASET_DIR + "/merged.csv"
# خواندن فایل‌ها
df1 = pd.read_csv(DATASET1_FILE,low_memory=False)
df2 = pd.read_csv(DATASET2_FILE,low_memory=False)

# مرج (چسباندن سطرها)
merged = pd.concat([df1, df2], ignore_index=True)

# ذخیره
merged.to_csv(DATASET3_FILE, index=False)