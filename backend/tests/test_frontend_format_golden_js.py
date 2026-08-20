"""포맷 골든 픽스처에 대한 **JS 구현 적합성** (SPEC 9.1.1 · 계약 결정 #16 · #36).

`test_format_golden.py` 의 머리말이 「JS 변은 D-11(6단계 `web`)이 같은 파일을 읽어
붙든다」고 적어 두었다. **이 파일이 그 나머지 반쪽이다.**

  픽스처 완결성   crosscheck (코디네이터)  계약이 무엇을 요구하는가
  파이썬 적합성   test_format_golden.py    우리 구현이 그것을 내는가
  JS 적합성       여기                     저쪽 구현이 그것을 내는가

같은 파일(`contracts/format_golden.json`)을 읽는다. 한쪽만 바꾸면 그쪽이 깨진다.

**변경 전 실패의 관측** — 이 파일이 생기기 전 `frontend/app.js` 의 `pct()` 는
`toFixed()` 였고 `pct(2.5, 0)` 을 `"3%"` 로 냈다 (기대 `"2%"`). 파이썬의 `f"{x:.0f}"` 는
정확한 이진값에 대한 **짝수 반올림**이고 `toFixed` 는 동점에서 큰 쪽을 고르기 때문이다.
`frontend/format.js` 가 double 을 비트에서 분해해 정확한 십진 반올림을 하는 이유가 그것이다.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from js_runner import load_golden_fixture, node_version, run_js  # noqa: E402

GOLDEN = load_golden_fixture()
MONEY_CASES = [(c["in"], c["out"], c["why"]) for c in GOLDEN["money"]["cases"]]
PCT_CASES = [(c["in"], c["digits"], c["out"], c["why"]) for c in GOLDEN["pct"]["cases"]]


def _js_format_all():
    """픽스처 전 케이스를 **한 번의 node 실행**으로 돌린다. 프로세스를 케이스마다 띄우지 않는다."""
    return run_js(
        """
        var golden = JSON.parse(GOLDEN_JSON);
        var F = globalThis.FirstHomeFormat;
        return {
          money: golden.money.cases.map(function (c) { return F.money(c['in']); }),
          pct: golden.pct.cases.map(function (c) { return F.pct(c['in'], c.digits); })
        };
        """,
        include_generated=False,
        extra_globals={"GOLDEN_JSON": __import__("json").dumps(GOLDEN)},
    )


JS_RESULT = _js_format_all()


@pytest.mark.parametrize(
    "index, expected, why",
    [(i, c[1], c[2]) for i, c in enumerate(MONEY_CASES)],
    ids=[str(c[0]) for c in MONEY_CASES],
)
def test_js_money_matches_the_golden_fixture(index, expected, why):
    assert JS_RESULT["money"][index] == expected, f"fmt.money({MONEY_CASES[index][0]}) — {why}"


@pytest.mark.parametrize(
    "index, expected, why",
    [(i, c[2], c[3]) for i, c in enumerate(PCT_CASES)],
    ids=[f"{c[0]}@{c[1]}" for c in PCT_CASES],
)
def test_js_pct_matches_the_golden_fixture(index, expected, why):
    case = PCT_CASES[index]
    assert JS_RESULT["pct"][index] == expected, f"fmt.pct({case[0]}, {case[1]}) — {why}"


def test_the_fixture_is_actually_being_read():
    """케이스가 0건이면 위 두 테스트는 아무것도 검증하지 않고 초록이 된다."""
    assert len(MONEY_CASES) >= 15
    assert len(PCT_CASES) >= 10
    assert len(JS_RESULT["money"]) == len(MONEY_CASES)
    assert len(JS_RESULT["pct"]) == len(PCT_CASES)


def test_node_actually_ran_the_javascript():
    """하네스가 도는지 자체를 남긴다 — 실패 메시지에 node 버전이 실린다 (조건 1).

    CI 로그에서 이 테스트가 통과했다는 것이 곧 「러너에 node 가 있고 프론트 JS 를
    실행했다」의 관측이다. 문서 지식이 아니라 실행 결과다.
    """
    version = node_version()
    assert version.startswith("v"), version
    echoed = run_js("return typeof globalThis.FirstHomeFormat.money;", include_generated=False)
    assert echoed == "function"


def test_the_javascript_refuses_to_format_a_missing_number():
    """F-1 의 파손 그 자체 — `pct(undefined)` 가 조용히 "0.0%" 가 되면 안 된다.

    사라진 필드를 0 으로 메우는 것이 이 프로젝트가 실제로 겪은 사고다
    (PR #24 §6 ①②④). 포맷 함수가 그 자리에서 **던지게** 해 화면이 거짓 숫자를
    그리는 대신 멈추도록 한다.
    """
    threw = run_js(
        """
        try { globalThis.FirstHomeFormat.pct(undefined); return null; }
        catch (e) { return String(e.message); }
        """,
        include_generated=False,
    )
    assert threw is not None, "pct(undefined) 가 예외 없이 통과했다 — F-1 의 파손 형태다"
    assert "포맷할 수 없는" in threw
