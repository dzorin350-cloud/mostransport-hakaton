"""Optional UI smoke test with Edge + Playwright (`pip install playwright`)."""
import tempfile
from pathlib import Path
from playwright.sync_api import sync_playwright


def main():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto("http://127.0.0.1:8080/", wait_until="domcontentloaded")
        page.locator("#authUser").fill("demo")
        page.locator("#authPass").fill("demo2025")
        page.locator("#authSubmit").click()
        page.locator("#authOverlay").wait_for(state="hidden", timeout=20000)
        page.wait_for_function("document.getElementById('kpiTotal').textContent !== '—'", timeout=20000)
        page.locator('a[href="/dispatcher.html"]').first.click()
        page.locator("#planTable table tr").nth(1).wait_for(timeout=20000)
        try:
            page.locator("#todayTop p").first.wait_for(timeout=20000)
        except Exception:
            print("dispatcher notice:", page.locator("#notice").inner_text(), "page errors:", errors)
            raise
        assert page.locator("#nextHours table tr").count() >= 2
        assert not errors, errors
        page.screenshot(path=str(Path(tempfile.gettempdir()) / "tram_dispatcher_smoke.png"), full_page=True)
        print("dashboard login, dispatcher plan, today and next-hours: OK")
        browser.close()


if __name__ == "__main__":
    main()
