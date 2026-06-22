"""
src/ai/deepseek_client.py — Playwright automation for DeepSeek chat.

Public API:
  DeepSeekSession          — persistent browser session for a backtest thread
  run_from_file(path)      — stateless single call (for live trading)
"""

import sys
import time

from playwright.sync_api import sync_playwright, Playwright

import config


def _wait_for_response(page, timeout: int = config.RESPONSE_STABLE_TIMEOUT) -> str:
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
            pass

        time.sleep(0.5)

    return last_text


class DeepSeekSession:
    """
    Persistent browser session — open once per thread, reuse for every AI call.
    Each call opens a NEW chat page so context from previous signals
    doesn't leak into the next one.

    Usage:
        with DeepSeekSession() as session:
            result = session.send(prompt_text)
    """

    def __init__(self):
        self._playwright: Playwright | None = None
        self._browser    = None
        self._context    = None

    def __enter__(self):
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(
            headless=config.HEAD_LESS_MODE,
            channel="chrome",
            timeout=config.BROWSER_LAUNCH_TIMEOUT,
        )
        self._context = self._browser.new_context(
            storage_state=config.BOT_STORAGE_STATE
        )
        return self

    def __exit__(self, *_):
        try:
            self._context.close()
            self._browser.close()
            self._playwright.stop()
        except Exception:
            pass

    def send(self, prompt_text: str, retries: int = config.RETRY_ATTEMPTS) -> dict | None:
        """
        Send a prompt in a fresh chat page and return
        {'response': str, 'chat_link': str}.
        Browser stays open between calls.
        """
        for attempt in range(retries):
            page = None
            try:
                page = self._context.new_page()
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

                page.close()   # فقط tab بسته می‌شه، مرورگر باز می‌مونه
                return {"response": response, "chat_link": chat_link}

            except Exception as exc:
                print(f"[deepseek] Attempt {attempt + 1}/{retries} failed: {exc}",
                      file=sys.stderr)
                if page:
                    try:
                        page.close()
                    except Exception:
                        pass
                time.sleep(config.RETRY_DELAY_SEC)
                if attempt == retries - 1:
                    raise RuntimeError("All DeepSeek connection attempts failed.") from exc

        return None

    def send_from_file(self, file_path: str) -> dict | None:
        """Read a prompt file and send it."""
        with open(file_path, "r", encoding="utf-8") as fh:
            return self.send(fh.read())


# ── stateless API for live trading ───────────────────────────────────────────

def connect(prompt_text: str, retries: int = config.RETRY_ATTEMPTS) -> dict | None:
    """Single-shot call — opens and closes browser each time. For live trading."""
    with DeepSeekSession() as session:
        return session.send(prompt_text, retries=retries)


def run_from_file(file_path: str) -> dict | None:
    """Single-shot call from file. For live trading."""
    with DeepSeekSession() as session:
        return session.send_from_file(file_path)