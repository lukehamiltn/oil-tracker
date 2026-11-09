"""
Visit the live site in a real (headless) browser, so Streamlit Cloud never
puts it to sleep and its data stays loaded for the next real visitor.
Run every hour by .github/workflows/keep_awake.yml.

If the site is asleep, Streamlit shows a "get this app back up" button; we
click it and wait for the site to finish loading.
"""

import os
import sys
import time

from playwright.sync_api import sync_playwright

URL = "https://oil-tracker-q7rqjuftmvvqnrgbkzwjcd.streamlit.app/"
WAIT_SECONDS = 300


def site_ready(page) -> bool:
    """True once the site's tabs have appeared (the app may sit in an iframe)."""
    for frame in page.frames:
        try:
            if frame.get_by_role("tab", name="Scheduled events").count():
                return True
        except Exception:
            pass
    return False


def wake_button(page):
    for frame in page.frames:
        button = frame.get_by_role("button", name="get this app back up")
        try:
            if button.count():
                return button.first
        except Exception:
            pass
    return None


def main() -> int:
    with sync_playwright() as p:
        # BROWSER_CHANNEL=chrome uses an installed Chrome (for testing on a PC)
        browser = p.chromium.launch(channel=os.environ.get("BROWSER_CHANNEL"))
        page = browser.new_page()
        page.goto(URL, timeout=120_000)
        start = time.time()
        while time.time() - start < WAIT_SECONDS:
            if site_ready(page):
                print(f"Site is up ({time.time() - start:.0f}s).")
                page.wait_for_timeout(5_000)      # let the page finish its first run
                browser.close()
                return 0
            button = wake_button(page)
            if button is not None:
                print("Site was asleep - waking it up.")
                button.click()
            page.wait_for_timeout(5_000)
        print("Site didn't finish loading in time.")
        browser.close()
        return 1


if __name__ == "__main__":
    sys.exit(main())
