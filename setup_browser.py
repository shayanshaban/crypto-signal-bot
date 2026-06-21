"""
setup_browser.py — One-time DeepSeek login helper.

Run once before using main.py. Opens Chrome so you can log in manually,
then saves the session to config.BOT_PROFILE_DIR.

Usage:
    python setup_browser.py
"""

# from playwright.sync_api import sync_playwright
# import config


# def main() -> None:
#     print(f"Profile directory : {config.BOT_PROFILE_DIR}")
#     print("Log in to DeepSeek in the browser that opens.")
#     print("Press Enter here when done to save and close.\n")

#     with sync_playwright() as p:
#         ctx  = p.chromium.launch_persistent_context(
#             user_data_dir=config.BOT_PROFILE_DIR,
#             headless=False,
#             channel="chrome",
#         )
#         page = ctx.new_page()
#         page.goto(config.DEEPSEEK_URL)
#         input()
#         ctx.close()

#     print("Session saved.  Run:  python main.py")





from playwright.sync_api import sync_playwright
import config
def main() -> None:
    with sync_playwright() as p:
        print("Log in to DeepSeek in the browser that opens.")
        browser = p.chromium.launch(headless=False, channel="chrome")
        context = browser.new_context()
        page = context.new_page()
        page.goto(config.DEEPSEEK_URL)
        input("Press Enter here when done to save and close.\n")
        context.storage_state(path=config.BOT_STORAGE_STATE)
        browser.close()
    print(f"Storage state saved to {config.BOT_STORAGE_STATE}")


if __name__ == "__main__":
    main()