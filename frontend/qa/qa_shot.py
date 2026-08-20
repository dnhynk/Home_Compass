# -*- coding: utf-8 -*-
"""Visual QA harness — Home_Compass frontend.
Drives the real flow with Playwright, captures full-page screenshots at
desktop + mobile, and reports console errors / overflow / contrast issues.

usage:  python qa_shot.py [tag]
"""
import sys, os, json, pathlib

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).resolve().parent
TAG = sys.argv[1] if len(sys.argv) > 1 else "p1"
URL = os.environ.get("QA_URL", "http://127.0.0.1:8000/")

VIEWPORTS = [("desktop", 1440, 900), ("mobile", 390, 844)]

# Elements that must never overflow the viewport horizontally.
OVERFLOW_JS = """
() => {
  const vw = document.documentElement.clientWidth;
  const bad = [];
  document.querySelectorAll('body *').forEach(el => {
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) return;
    if (r.right > vw + 1 || r.left < -1) {
      bad.push({
        sel: el.tagName.toLowerCase() + (el.id ? '#'+el.id : '') +
             (el.className && typeof el.className === 'string' ? '.'+el.className.trim().split(/\\s+/).join('.') : ''),
        left: Math.round(r.left), right: Math.round(r.right), vw
      });
    }
  });
  return {
    docScrollW: document.documentElement.scrollWidth,
    clientW: vw,
    bodyScrollW: document.body.scrollWidth,
    offenders: bad.slice(0, 25)
  };
}
"""

# Detect text nodes that are visually clipped (scrollWidth > clientWidth)
CLIP_JS = """
() => {
  const bad = [];
  document.querySelectorAll('body *').forEach(el => {
    if (el.children.length > 0) return;           // leaf text only
    const t = (el.textContent || '').trim();
    if (!t) return;
    if (el.scrollWidth > el.clientWidth + 1 && el.clientWidth > 0) {
      bad.push({sel: el.tagName.toLowerCase()+(el.id?'#'+el.id:'')+(el.className&&typeof el.className==='string'?'.'+el.className.trim().split(/\\s+/).join('.'):''),
                text: t.slice(0,40), sw: el.scrollWidth, cw: el.clientWidth});
    }
    if (el.scrollHeight > el.clientHeight + 2 && el.clientHeight > 0) {
      const st = getComputedStyle(el);
      if (st.overflowY === 'hidden') {
        bad.push({sel: el.tagName.toLowerCase()+(el.id?'#'+el.id:''), text: t.slice(0,40),
                  sh: el.scrollHeight, ch: el.clientHeight, note: 'vertical clip'});
      }
    }
  });
  return bad.slice(0, 25);
}
"""

# WCAG contrast audit over rendered text
CONTRAST_JS = """
() => {
  const srgb = c => { c /= 255; return c <= 0.03928 ? c/12.92 : Math.pow((c+0.055)/1.055, 2.4); };
  const lum = ([r,g,b]) => 0.2126*srgb(r)+0.7152*srgb(g)+0.0722*srgb(b);
  const parse = s => { const m = s.match(/[\\d.]+/g); return m ? m.slice(0,3).map(Number) : null; };
  const alpha = s => { const m = s.match(/[\\d.]+/g); return m && m.length > 3 ? Number(m[3]) : 1; };
  const blend = (fg, fa, bg) => fg.map((c,i) => c*fa + bg[i]*(1-fa));

  // Returns null when an ancestor paints a gradient/image: the effective
  // backdrop is not a single colour, so a computed ratio would be fiction.
  // (.card-summary and .hero are gradient-filled dark panels — reporting them
  // as 1.05:1 against the page plane was a false positive.)
  function bgOf(el) {
    let n = el;
    while (n && n !== document.documentElement) {
      const st = getComputedStyle(n);
      if (st.backgroundImage && st.backgroundImage !== 'none') return null;
      const c = parse(st.backgroundColor); const a = alpha(st.backgroundColor);
      if (c && a >= 1) return c;
      n = n.parentElement;
    }
    return [255,255,255];
  }
  const out = [];
  document.querySelectorAll('body *').forEach(el => {
    if (el.children.length > 0) return;
    const t = (el.textContent||'').trim(); if (!t) return;
    const r = el.getBoundingClientRect(); if (r.width===0||r.height===0) return;
    const st = getComputedStyle(el);
    if (st.visibility==='hidden'||st.opacity==='0') return;
    const fg0 = parse(st.color); if (!fg0) return;
    const fa = alpha(st.color);
    const bg = bgOf(el);
    if (!bg) return;                       // gradient backdrop — not measurable here
    const fg = fa >= 1 ? fg0 : blend(fg0, fa, bg);
    const L1 = lum(fg), L2 = lum(bg);
    const ratio = (Math.max(L1,L2)+0.05)/(Math.min(L1,L2)+0.05);
    const fs = parseFloat(st.fontSize), fw = parseInt(st.fontWeight)||400;
    const large = fs >= 24 || (fs >= 18.66 && fw >= 700);
    const need = large ? 3.0 : 4.5;
    if (ratio < need) {
      out.push({sel: el.tagName.toLowerCase()+(el.id?'#'+el.id:'')+(el.className&&typeof el.className==='string'?'.'+el.className.trim().split(/\\s+/)[0]:''),
                text: t.slice(0,32), ratio: Math.round(ratio*100)/100, need,
                fs, fw, color: st.color, bg: 'rgb('+bg.map(Math.round).join(',')+')'});
    }
  });
  // dedupe by selector+ratio
  const seen = new Set(); const uniq = [];
  out.forEach(o => { const k = o.sel+o.ratio; if (!seen.has(k)) { seen.add(k); uniq.push(o); } });
  return uniq.slice(0, 30);
}
"""


def audit(page, name, report):
    over = page.evaluate(OVERFLOW_JS)
    clip = page.evaluate(CLIP_JS)
    contrast = page.evaluate(CONTRAST_JS)
    report[name] = {"overflow": over, "clip": clip, "contrast": contrast}


def main():
    report = {"url": URL, "console": []}
    outdir = HERE
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for vpname, w, h in VIEWPORTS:
            ctx = browser.new_context(viewport={"width": w, "height": h},
                                      device_scale_factor=1, locale="ko-KR")
            page = ctx.new_page()
            errs = []
            page.on("console", lambda m, e=errs: e.append({"type": m.type, "text": m.text})
                    if m.type in ("error", "warning") else None)
            page.on("pageerror", lambda ex, e=errs: e.append({"type": "pageerror", "text": str(ex)}))

            page.goto(URL, wait_until="networkidle")
            page.wait_for_timeout(700)

            # --- state 0: onboarding
            page.screenshot(path=str(outdir / f"{TAG}_{vpname}_01_onboarding.png"), full_page=True)
            audit(page, f"{vpname}:onboarding", report)

            # --- fill form + analyze
            page.fill("#age", "28")
            page.fill("#annualIncome", "4200")
            page.fill("#monthlyNetIncome", "300")
            page.fill("#liquidAssets", "4000")
            page.fill("#existingDebt", "30")
            page.click('#preferredType button[data-value="any"]')
            page.click("#btnAnalyze")
            page.wait_for_selector("#dashboard:not([hidden])", timeout=15000)
            page.wait_for_timeout(1200)

            page.screenshot(path=str(outdir / f"{TAG}_{vpname}_02_dashboard.png"), full_page=True)
            audit(page, f"{vpname}:dashboard", report)

            # --- chat flow
            page.fill("#chatText", "전세랑 월세 중 뭐가 나아?")
            page.click("#btnSend")
            # the typing placeholder is itself a .msg-bot, so it must be gone
            # before the count means "a real answer arrived"
            try:
                page.wait_for_function(
                    "() => !document.getElementById('typingRow') && "
                    "document.querySelectorAll('#chatLog .msg-bot').length >= 2",
                    timeout=45000)
                report.setdefault("chat_ok", []).append(vpname)
            except Exception as ex:
                report.setdefault("chat_error", []).append(f"{vpname}: {type(ex).__name__}")
            reply = page.evaluate(
                "() => { const n = document.querySelectorAll('#chatLog .msg-bot .msg-bubble');"
                "  return n.length ? n[n.length-1].textContent.trim().slice(0,180) : null; }")
            report.setdefault("chat_reply", {})[vpname] = reply
            chip = page.evaluate("() => (document.getElementById('chatModeChip')||{}).textContent")
            conn = page.evaluate("() => (document.getElementById('connText')||{}).textContent")
            report.setdefault("badges", {})[vpname] = {"chatChip": chip, "conn": conn}
            page.wait_for_timeout(900)
            page.screenshot(path=str(outdir / f"{TAG}_{vpname}_03_chat.png"), full_page=True)
            audit(page, f"{vpname}:chat", report)

            # focused shot of just the chat card + risk card
            for sel, label in [("#cardChat", "chat"), ("#cardRisk", "risk"),
                               ("#cardVerdict", "verdict"), ("#cardScenarios", "scen")]:
                try:
                    page.locator(sel).screenshot(path=str(outdir / f"{TAG}_{vpname}_z_{label}.png"))
                except Exception:
                    pass

            report["console"].append({"viewport": vpname, "messages": errs})
            ctx.close()
        browser.close()

    (outdir / f"{TAG}_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    # console summary
    print("=== CONSOLE ===")
    for c in report["console"]:
        print(f"[{c['viewport']}] {len(c['messages'])} msg")
        for m in c["messages"][:20]:
            print("   ", m["type"], "|", m["text"][:200])
    print("\n=== OVERFLOW / CLIP / CONTRAST ===")
    for k, v in report.items():
        if not isinstance(v, dict) or "overflow" not in v:
            continue
        o = v["overflow"]
        hs = o["docScrollW"] > o["clientW"] + 1
        print(f"\n--- {k} --- h-scroll={hs} (scrollW={o['docScrollW']} vs {o['clientW']})")
        for x in o["offenders"][:8]:
            print("    OVERFLOW", x["sel"][:90], x["left"], "->", x["right"])
        for x in v["clip"][:8]:
            print("    CLIP    ", x["sel"][:70], "|", x.get("text", "")[:32], x)
        for x in v["contrast"][:12]:
            print(f"    CONTRAST {x['ratio']} (need {x['need']}) {x['sel'][:60]} | "
                  f"{x['text'][:26]} | {x['color']} on {x['bg']}")
    if "chat_error" in report:
        print("\n=== CHAT ERRORS ===", report["chat_error"])


if __name__ == "__main__":
    main()
