# trading/wallet.py (نسخه اصلاح شده)

import json
import os
import threading
from pathlib import Path
from .models import Wallet
from .exceptions import WalletException


class WalletManager:
    """
    Manages loading, saving, and thread-safe access to the wallet state.
    The wallet is stored as a JSON file. Atomic writes prevent corruption.
    """

    def __init__(self, filepath: str = "data/wallet.json"):
        self.filepath = filepath
        self._lock = threading.Lock()
        self._ensure_file()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def load_wallet(self) -> Wallet:
        """Return the current wallet state from disk."""
        with self._lock:
            return self._read_from_disk()

    def save_wallet(self, wallet: Wallet) -> None:
        """
        Persist a wallet instance atomically.
        This method should be called after every state mutation.
        """
        with self._lock:
            self._write_to_disk(wallet)

    def create_default(self, initial_balance: float = 100.0) -> Wallet:
        """Create a new wallet with the given starting balance."""
        wallet = Wallet(
            balance=initial_balance,
            equity=initial_balance,
            free_margin=initial_balance,
            peak_balance=initial_balance
        )
        self.save_wallet(wallet)
        return wallet

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _ensure_file(self) -> None:
        """Create the wallet file with a default wallet if it does not exist or is empty."""
        path = Path(self.filepath)
        # اگر پوشه‌ی والد وجود ندارد، بساز
        path.parent.mkdir(parents=True, exist_ok=True)
        # اگر فایل وجود ندارد یا خالی است، کیف پول پیش‌فرض را بنویس
        if not path.exists() or path.stat().st_size == 0:
            self.create_default()

    def _read_from_disk(self) -> Wallet:
        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            return Wallet.from_dict(data)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            # اگر فایل موجود نبود یا محتوایش خراب/خالی بود،
            # یک کیف پول پیش‌فرض بساز و روی دیسک ذخیره کن
            wallet = Wallet(
                balance=10_000.0,
                equity=10_000.0,
                free_margin=10_000.0,
                peak_balance=10_000.0
            )
            self._write_to_disk(wallet)
            return wallet
        except Exception as e:
            raise WalletException(f"Failed to read wallet: {e}") from e

    def _write_to_disk(self, wallet: Wallet) -> None:
        """Atomic write using a temporary file and rename."""
        tmp_path = self.filepath + ".tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(wallet.to_dict(), f, indent=2, default=str)
            os.replace(tmp_path, self.filepath)  # atomic on POSIX
        except OSError as e:
            raise WalletException(f"Failed to write wallet: {e}") from e