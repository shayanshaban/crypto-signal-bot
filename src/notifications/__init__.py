"""
Notifications sub-package — alerting via Telegram, email, etc.

Currently a stub.  To add Telegram:
  1. Uncomment TELEGRAM_TOKEN / TELEGRAM_CHAT_ID in config.py
  2. pip install python-telegram-bot
  3. Implement send_telegram(message) here
"""


def notify(message: str) -> None:
    """
    Send a notification.  Currently just prints to stdout.
    Replace this function body when a real channel is configured.
    """
    print(f"[notify] {message}")
