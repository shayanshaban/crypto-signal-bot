"""
setup_browser.py — One-time DeepSeek login helper.

Run this script once before using main.py.  It opens a real Chrome
window pointed at DeepSeek so you can log in manually.  When you're
done, press Enter in this terminal and the browser will close, saving
your session cookies to config.BOT_PROFILE_DIR.

Usage:
    python setup_browser.py
"""

from playwright.sync_api import sync_playwright
import config


def main() -> None:
    print(f"Opening Chrome with profile directory: {config.BOT_PROFILE_DIR!r}")
    print("Log in to DeepSeek in the browser window that appears.")
    print("When you're done, press Enter here to save and close.")

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=config.BOT_PROFILE_DIR,
            headless=False,
            channel="chrome",
        )
        page = context.new_page()
        page.goto(config.DEEPSEEK_URL)

        input()   # wait for user to finish logging in

        context.close()

    print("Session saved. You can now run  python main.py")


if __name__ == "__main__":
    main()
