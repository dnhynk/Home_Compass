# -*- coding: utf-8 -*-
"""Offline check for the 판정 화면 — every /api/* call is aborted, so the page
must run on the **local judgement path** (SPEC 6.2 D-11), not on a static mock.

What this asserts, and why each one is here:

  1. no page exception, no unexplained console error  — 10.2 8단계 「매회 무오류」
  2. no request leaves the machine                    — D-8 「네트워크 의존 금지」
  3. the local path is **named on screen**            — D-11 #3 「침묵 폴백 금지」
  4. 판정 숫자가 실제로 나온다                          — D-11 #2 (생성물이 있을 때)
  5. no horizontal scroll at either viewport          — 6단계 QA 회귀 (QA_NOTES #1)

「무오류」의 정의에 주의할 것. 백엔드 부재를 **탐지하려면 요청을 보내야** 하고, 그 요청을
끊으면 Chromium 이 요청마다 `Failed to load resource: net::ERR_FAILED` 를 콘솔에 남긴다.
그것은 앱의 결함이 아니라 이 시험이 만든 조건이다. 그래서 아래는 갈라서 본다 —
**페이지 예외 0건**과 **끊은 `/api/*` 로 설명되지 않는 콘솔 에러 0건**이 합격선이고,
설명된 것들은 억누르지 않고 개수와 URL 을 함께 출력한다.

This file used to assert a built-in `MOCK_RESPONSE` fallback. PR #67 deleted
that constant: a static answer with no provenance is exactly what D-11 #3
forbids. The replacement is `generated/*.js` + `local_engine.js`, and when the
generated files are missing the path is **switched off** rather than guessed —
so "offline works" now means "the banner says which path produced the numbers",
not "some numbers appeared".

usage:
    python qa_offline.py                          # file:// — no backend at all
    QA_URL=http://127.0.0.1:8000/ python qa_offline.py   # served, /api/* cut

Exit code is non-zero when any check fails; screenshots are written next to
this file for a human to eyeball (gitignored).
"""
import os
import sys
import pathlib

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).resolve().parent
# Derive the page from this file's own location. The previous hard-coded
# absolute repository path outlived the tree it named, and the script died on
# ERR_FILE_NOT_FOUND before checking anything.
INDEX = HERE.parent / "index.html"
URL = os.environ.get("QA_URL") or INDEX.as_uri()

VIEWPORTS = [("desktop", 1440, 900), ("mobile", 390, 844)]

# D-8 sanctions **one local host**; it forbids depending on the network. So a
# loopback call is inside the rule and anything else is outside it. At file://
# the page has an opaque origin and `app.js` falls back to http://127.0.0.1:8000
# (app.js:20) — that is still the local host, not a network dependency.
LOCAL_SCHEMES = ("file:", "data:", "blob:", "about:")
LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "[::1]", "::1")


def leaves_the_machine(url):
    if url.startswith(LOCAL_SCHEMES):
        return False
    for scheme in ("http://", "https://"):
        if url.startswith(scheme):
            host = url[len(scheme):].split("/", 1)[0].split("@")[-1]
            return host.rsplit(":", 1)[0].strip("[]") not in (
                h.strip("[]") for h in LOOPBACK_HOSTS)
    return True


def check(results, name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print("    %s %s%s" % ("PASS" if ok else "FAIL", name,
                           ("  — " + detail) if detail else ""))
    return ok


def run_viewport(browser, vp, w, h, results):
    ctx = browser.new_context(viewport={"width": w, "height": h}, locale="ko-KR")
    page = ctx.new_page()

    console = []
    page_errors = []
    page.on("console", lambda m: console.append((m.type, m.text))
            if m.type in ("error", "warning") else None)
    page.on("pageerror", lambda e: page_errors.append(str(e)))

    external = []
    page.on("request", lambda r: external.append(r.url)
            if leaves_the_machine(r.url) else None)

    aborted = []

    def kill_api(route, request):
        aborted.append(request.url)
        route.abort()

    # hard-kill every backend call — this is the "backend is not there" case,
    # which is stricter than 8단계's "네트워크를 끊은 상태" (a cut network still
    # leaves the local uvicorn reachable on 127.0.0.1).
    page.route("**/api/**", kill_api)

    print("\n[%s] %s" % (vp, URL))
    page.goto(URL, wait_until="load")
    page.wait_for_timeout(1500)

    conn = page.evaluate("() => document.getElementById('connText').textContent")
    regions = page.evaluate("() => document.getElementById('regionCode').options.length")
    banner = page.evaluate(
        "() => { const b = document.getElementById('localBanner');"
        "  return b ? {hidden: b.hidden, kind: b.getAttribute('data-kind'),"
        "              text: (b.textContent||'').trim()} : null; }")
    print("    conn=%r regionOptions=%s" % (conn, regions))
    print("    banner=%s" % (banner and {k: (v[:90] if k == "text" else v)
                                         for k, v in banner.items()}))

    # D-11 #3 — the page must say which path produced the numbers.
    check(results, "%s: 로컬 경로가 화면에 적힌다 (D-11 #3)" % vp,
          banner is not None and banner["hidden"] is False and banner["text"] != "",
          "banner kind=%s" % (banner or {}).get("kind"))
    check(results, "%s: 연결 배지가 백엔드 부재를 말한다" % vp,
          "백엔드 미연결" in (conn or ""), repr(conn))

    ready = bool(banner and banner.get("kind") == "local")
    check(results, "%s: 생성물이 있어 로컬 판정 경로가 켜져 있다 (D-11 #2)" % vp, ready,
          "kind=disabled 이면 frontend/generated/ 가 없다 — "
          "python scripts/gen_contracts.py")
    check(results, "%s: 지역 목록이 생성물에서 채워진다" % vp, regions > 0,
          "options=%s" % regions)

    if ready:
        page.click("#btnAnalyze")
        page.wait_for_selector("#dashboard:not([hidden])", timeout=15000)
        page.wait_for_timeout(900)
        rec = page.evaluate("() => document.getElementById('recAmount').textContent")
        scen = page.evaluate("() => document.querySelectorAll('#scenarioGrid .scenario').length")
        pol = page.evaluate("() => document.querySelectorAll('#policyList .policy').length")
        risk = page.evaluate("() => document.getElementById('riskScore').textContent")
        print("    rec=%r scenarios=%s policies=%s risk=%r" % (rec, scen, pol, risk))
        # Counts are not asserted against a literal: they come from the
        # generated artifacts, and a number written here would become a second
        # source of truth the moment the registry changes.
        check(results, "%s: 판정 숫자가 나온다" % vp,
              bool((rec or "").strip()) and scen > 0 and pol > 0 and (risk or "").strip() != "",
              "rec=%r scenarios=%s policies=%s risk=%r" % (rec, scen, pol, risk))

        page.fill("#chatText", "전세랑 월세 중 뭐가 나아?")
        page.click("#btnSend")
        page.wait_for_function(
            "() => !document.getElementById('typingRow') && "
            "document.querySelectorAll('#chatLog .msg-bot').length >= 2", timeout=20000)
        page.wait_for_timeout(500)
        reply = page.evaluate(
            "() => { const n=document.querySelectorAll('#chatLog .msg-bot .msg-bubble');"
            "return n[n.length-1].textContent.trim().slice(0,140); }")
        chip = page.evaluate("() => document.getElementById('chatModeChip').textContent")
        print("    chatChip=%r" % chip)
        print("    reply=%r" % reply)
        check(results, "%s: 오프라인 채팅이 답한다" % vp, bool((reply or "").strip()))

    sw = page.evaluate(
        "() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]")
    check(results, "%s: 가로 스크롤 없음" % vp, sw[0] <= sw[1] + 1,
          "scrollW=%s clientW=%s" % (sw[0], sw[1]))

    page.screenshot(path=str(HERE / ("offline_%s_dashboard.png" % vp)), full_page=True)

    # Chromium logs one console error per aborted request and the message
    # carries no URL, so the aborted /api/* calls are accounted for by count
    # against the routes we killed, and everything else has to be zero.
    probe_noise = [c for c in console if "Failed to load resource" in c[1]]
    unexplained = [c for c in console if c not in probe_noise]
    print("    끊은 /api 호출 %d건: %s" % (len(aborted), sorted(set(aborted))))
    print("    그로 인한 콘솔 로그 %d건 (앱 결함 아님)" % len(probe_noise))
    check(results, "%s: 페이지 예외 0건" % vp, not page_errors, repr(page_errors[:3]))
    check(results, "%s: 끊은 요청으로 설명되지 않는 콘솔 에러 0건" % vp,
          not unexplained, repr(unexplained[:4]))
    check(results, "%s: 콘솔 로그가 끊은 호출 수를 넘지 않는다" % vp,
          len(probe_noise) <= len(aborted),
          "console=%d aborted=%d" % (len(probe_noise), len(aborted)))
    check(results, "%s: 이 기기를 벗어난 요청 없음 (D-8)" % vp, not external,
          repr(sorted(set(external))[:4]))
    ctx.close()


def main():
    results = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for vp, w, h in VIEWPORTS:
            run_viewport(browser, vp, w, h, results)
        browser.close()

    failed = [r for r in results if not r[1]]
    print("\n%s\n%d checks, %d failed" % ("=" * 60, len(results), len(failed)))
    for name, _, detail in failed:
        print("  ! %s  %s" % (name, detail))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
