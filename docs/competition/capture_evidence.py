"""Capture stable, real-browser evidence used by the submission PDFs."""

from __future__ import annotations

import argparse
from pathlib import Path

from playwright.sync_api import sync_playwright

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = REPO_ROOT / "output" / "evidence"


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture Home_Compass submission evidence")
    parser.add_argument("--url", default="http://127.0.0.1:8000/")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)

    console_errors: list[str] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            device_scale_factor=1.5,
            locale="ko-KR",
            color_scheme="light",
        )
        page = context.new_page()
        page.on(
            "console",
            lambda msg: console_errors.append(f"{msg.type}: {msg.text}")
            if msg.type in {"error", "warning"}
            else None,
        )
        page.on("pageerror", lambda exc: console_errors.append(f"pageerror: {exc}"))

        page.goto(args.url, wait_until="networkidle")
        page.wait_for_timeout(500)
        page.screenshot(path=out / "home_compass_onboarding.png")

        page.click("#btnSample")
        page.click("#btnAnalyze")
        page.wait_for_selector("#dashboard:not([hidden])", timeout=15_000)
        page.locator("#toast").wait_for(state="hidden", timeout=7_000)
        page.evaluate("window.scrollTo(0, 0)")
        page.evaluate(
            "() => { const column = document.querySelector('.col-form'); "
            "if (column) column.scrollTop = 0; }"
        )
        page.screenshot(path=out / "home_compass_dashboard.png")

        page.locator("#cardChat").scroll_into_view_if_needed()
        page.fill("#chatText", "전세랑 월세 중 뭐가 나아?")
        page.click("#btnSend")
        page.wait_for_function(
            "() => !document.getElementById('typingRow') && "
            "document.querySelectorAll('#chatLog .msg-bot').length >= 2",
            timeout=45_000,
        )
        page.locator("#cardChat").screenshot(path=out / "home_compass_chat.png")

        overflow = page.evaluate(
            "() => ({scrollWidth: document.documentElement.scrollWidth, "
            "clientWidth: document.documentElement.clientWidth})"
        )
        if overflow["scrollWidth"] > overflow["clientWidth"] + 1:
            raise RuntimeError(f"horizontal overflow: {overflow}")
        browser.close()

    if console_errors:
        raise RuntimeError("browser console was not clean: " + " | ".join(console_errors))
    for path in sorted(out.glob("home_compass_*.png")):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
