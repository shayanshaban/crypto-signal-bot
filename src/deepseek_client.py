"""
src/deepseek_client.py — Browser automation for DeepSeek chat via Playwright.

Public API:
  connect(prompt_text)   — send a prompt string, return the response string
  run_from_file(path)    — read a file then call connect()
"""

import sys
import time

from playwright.sync_api import sync_playwright

import config


def _wait_for_response(page, timeout: int = config.RESPONSE_STABLE_TIMEOUT) -> str:
    """
    Poll the page until the assistant's reply stops changing.

    "Stable" means the text is non-empty and identical across
    RESPONSE_STABLE_CHECKS consecutive half-second polls.
    Returns the final text, or the last captured text on timeout.
    """
    last_text    = ""
    stable_count = 0

    for _ in range(timeout * 2):           # each iteration = 0.5 s
        try:
            messages = page.locator("div.ds-assistant-message-main-content")
            if messages.count() == 0:
                messages = page.locator(".chat-message-text, .prose, .markdown")

            if messages.count() == 0:
                time.sleep(0.5)
                continue

            text = messages.last.inner_text().strip()

            if text == last_text and len(text) > 0:
                stable_count += 1
            else:
                stable_count = 0
                last_text    = text

            if stable_count >= config.RESPONSE_STABLE_CHECKS:
                return text

        except Exception:
            pass   # selector errors during streaming are expected — keep polling

        time.sleep(0.5)

    return last_text   # timeout: return whatever we captured


def connect(prompt_text: str, retries: int = config.RETRY_ATTEMPTS) -> str | None:
    """
    Send *prompt_text* to DeepSeek and return the assistant's reply.

    Uses a persistent Chromium profile (config.BOT_PROFILE_DIR) so the
    session login is preserved between runs.  Run setup_browser.py once
    to authenticate and save the profile.
    """
    for attempt in range(retries):
        try:
            with sync_playwright() as p:
                context = p.chromium.launch_persistent_context(
                    user_data_dir=config.BOT_PROFILE_DIR,
                    headless=False,
                    channel="chrome",
                    timeout=config.BROWSER_LAUNCH_TIMEOUT,
                )
                page = context.new_page()
                page.set_default_timeout(config.BROWSER_LAUNCH_TIMEOUT)

                page.goto(config.DEEPSEEK_URL, timeout=config.BROWSER_LAUNCH_TIMEOUT)
                page.wait_for_load_state("load", timeout=config.PAGE_LOAD_TIMEOUT)

                page.wait_for_selector(
                    "textarea, div[contenteditable], input[type='text']",
                    timeout=config.SELECTOR_TIMEOUT,
                )

                textbox = page.get_by_role("textbox", name="Message DeepSeek")
                textbox.fill(prompt_text)

                page.get_by_role("radio", name=config.DEEPSEEK_MODE).click()
                page.keyboard.press("Enter")

                page.wait_for_selector(
                    "div.ds-assistant-message-main-content",
                    timeout=config.RESPONSE_START_TIMEOUT,
                )

                response = _wait_for_response(page)
                context.close()
                return response

        except Exception as exc:
            print(f"Attempt {attempt + 1}/{retries} failed: {exc}", file=sys.stderr)
            time.sleep(config.RETRY_DELAY_SEC)

            if attempt == retries - 1:
                raise RuntimeError(
                    "All attempts to connect to DeepSeek failed."
                ) from exc

    return None   # unreachable, but satisfies type-checkers


def run_from_file(file_path: str) -> str | None:
    """Read a prompt from *file_path* and send it to DeepSeek."""
    with open(file_path, "r", encoding="utf-8") as fh:
        prompt = fh.read()
    return connect(prompt)
