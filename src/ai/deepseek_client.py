"""
src/ai/deepseek_client.py — Playwright automation for DeepSeek chat.

Public API:
  connect(prompt_text)   — send a prompt, return {'response': str, 'chat_link': str}
  run_from_file(path)    — read a file then call connect()
"""

import sys
import time

from playwright.sync_api import sync_playwright

import config


def _wait_for_response(page, timeout: int = config.RESPONSE_STABLE_TIMEOUT) -> str:
    """
    Poll until the assistant's reply is stable (unchanged for
    RESPONSE_STABLE_CHECKS consecutive 0.5-second checks).
    """
    last_text    = ""
    stable_count = 0

    for _ in range(timeout * 2):
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
            pass   # selector errors during streaming are normal

        time.sleep(0.5)

    return last_text


def connect(prompt_text: str, retries: int = config.RETRY_ATTEMPTS) -> dict | None:
    """
    Send *prompt_text* to DeepSeek and return {'response': str, 'chat_link': str}.

    Uses a fresh browser + shared storage_state (cookies/login) instead of a
    persistent_context, so multiple threads can run concurrently without
    fighting over a locked profile directory.
    """
    for attempt in range(retries):
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=config.HEAD_LESS_MODE,
                    channel="chrome",
                    timeout=config.BROWSER_LAUNCH_TIMEOUT,
                )
                context = browser.new_context(storage_state=config.BOT_STORAGE_STATE)
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

                response  = _wait_for_response(page)
                chat_link = page.url

                context.close()
                browser.close()
                return {"response": response, "chat_link": chat_link}

        except Exception as exc:
            print(f"[deepseek] Attempt {attempt + 1}/{retries} failed: {exc}",
                  file=sys.stderr)
            time.sleep(config.RETRY_DELAY_SEC)
            if attempt == retries - 1:
                raise RuntimeError("All DeepSeek connection attempts failed.") from exc

    return None


def run_from_file(file_path: str) -> dict | None:
    """Read a prompt file and send it to DeepSeek."""
    with open(file_path, "r", encoding="utf-8") as fh:
        return connect(fh.read())