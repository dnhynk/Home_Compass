"""로컬 판정 경로에 **손으로 쓴 판정값이 없다** (SPEC 5.1.2 · 5.1.4 · D-11).

SPEC 5.1.4 가 「5.1 은 프론트 생성물에도 그대로 적용된다」고 적었고, 5.1.2 는 그 경계를
정하면서 검사 방법까지 못박았다 — *「`engines/` 하위 모듈을 AST로 훑어 숫자 리터럴을 찾고,
테스트 파일에 명시한 **허용 목록에 없으면 실패**시킨다. 허용 목록에 항목을 추가하려면
그 줄에 근거를 적는다. 목록이 커지는 것이 곧 규율이 무너지는 신호다.」*

**이 파일은 그 규율의 JS 변이다.** 대상은 `frontend/local_engine.js` 하나다 — 판정
숫자를 만드는 유일한 프론트 코드이기 때문이다. `app.js` 는 화면 코드이고 SVG 좌표처럼
판정 결과를 바꾸지 않는 숫자가 정상적으로 많아, 같은 잣대를 대면 허용 목록이 곧
파일 전체가 되어 검사가 아무것도 잡지 못한다. 대신 `app.js` 에는 **판정값의 출처**를
직접 확인하는 검사를 건다 (아래 마지막 두 함수).

파서를 새로 쓰지 않는다 — JS AST 를 파이썬에서 얻을 방법이 없으므로 주석과 문자열을
걷어낸 뒤 숫자 토큰을 세는 방식이다. 이 방식의 한계(템플릿 리터럴·정규식 안의 숫자)를
아래 `test_the_scanner_actually_sees_numbers` 가 대조군으로 붙든다.
"""

from __future__ import annotations

import re
from pathlib import Path

from js_runner import FRONTEND_DIR, run_js

LOCAL_ENGINE = FRONTEND_DIR / "local_engine.js"

#: 허용 목록. **각 줄에 근거를 적는다** (SPEC 5.1.2). 이 목록이 커지는 것이 규율이
#: 무너지는 신호이며, 판정 결과의 숫자를 바꾸는 값은 여기에 올 수 없다.
ALLOWED_LITERALS = {
    "0": "항등·초기값·비교 기준. 5.1.2 가 명시적으로 비대상으로 뒀다.",
    "1": "항등·최소 가구원수·비율 상한(1 = 100%). 5.1.2 비대상.",
    "2": "rationale 상위 2건 슬라이스 · 소수 자릿수 인자 — 표시 개수이지 판정값이 아니다.",
    "3": "① 알 수 없는 status 의 정렬 순위 sentinel (파이썬 `order.get(status, 3)` 과 같은 자리, "
         "정렬만 바꾸고 판정을 바꾸지 않는다) ② 보증료율 표기 자릿수 `pct(rate, 3)`.",
    "12": "연→월 환산. 5.1.2 가 단위·구조 상수의 예로 직접 든 값이다.",
    "100": "퍼센트 환산과 점수 상한. 5.1.2 비대상.",
    "100.0": "`valuePct` 의 「가입 가능 = 100%」 표기. 백분율 항등이며 5.1.2 비대상 — "
             "파이썬 `risk.scan_deposit_risk` 의 같은 자리도 리터럴 `100.0` 이다.",
    "10000": "만원 단위. 파이썬 `common.floor_to` 의 기본 unit 과 같은 단위 상수다.",
    "0.0": "부동소수 항등원. 비율·금리의 '없음' 표현.",
    "1.0": "부동소수 항등원. 배수 1배 = 가중치 미적용.",
}


def _strip_comments_and_strings(source: str) -> str:
    out: list[str] = []
    i, n = 0, len(source)
    while i < n:
        ch = source[i]
        if ch == "/" and i + 1 < n and source[i + 1] == "*":
            end = source.find("*/", i + 2)
            i = end + 2 if end >= 0 else n
            out.append(" ")
            continue
        if ch == "/" and i + 1 < n and source[i + 1] == "/":
            end = source.find("\n", i)
            i = end if end >= 0 else n
            continue
        if ch in "\"'`":
            quote = ch
            i += 1
            while i < n and source[i] != quote:
                if source[i] == "\\":
                    i += 1
                i += 1
            i += 1
            out.append('""')
            continue
        out.append(ch)
        i += 1
    return "".join(out)


NUMBER = re.compile(r"(?<![\w.$])\d+(?:\.\d+)?(?![\w.])")


def _literals(path: Path) -> list[str]:
    return NUMBER.findall(_strip_comments_and_strings(path.read_text(encoding="utf-8")))


def test_the_local_engine_has_no_model_parameter_literals():
    """판정 상수는 전부 생성물에서 온다. 코드에 숫자를 다시 쓰지 않는다."""
    found = sorted(set(_literals(LOCAL_ENGINE)))
    unlisted = [value for value in found if value not in ALLOWED_LITERALS]
    assert not unlisted, (
        f"`local_engine.js` 에 허용 목록에 없는 숫자 리터럴이 있다: {unlisted}\n"
        "판정 결과를 바꾸는 값이면 `frontend/generated/model_constants.js` 에서 읽어야 하고, "
        "단위·구조 상수라면 위 ALLOWED_LITERALS 에 **근거와 함께** 등재해야 한다 (SPEC 5.1.2)."
    )


def test_the_scanner_actually_sees_numbers():
    """★ 대조군 — 스캐너가 아무것도 못 보면 위 테스트는 무조건 통과한다."""
    assert len(_literals(LOCAL_ENGINE)) >= 10, "숫자 토큰을 한 개도 못 찾았다 — 스캐너가 죽어 있다"
    probe = _strip_comments_and_strings(
        "var a = 0.42; /* 0.99 는 주석 */ var s = '0.77'; // 0.11\nvar b = 12345;"
    )
    assert sorted(set(NUMBER.findall(probe))) == ["0.42", "12345"], NUMBER.findall(probe)


def test_the_allow_list_carries_a_reason_for_every_entry():
    """근거 없는 등재를 막는다. 근거 칸이 비면 목록은 그냥 우회로가 된다."""
    for value, reason in ALLOWED_LITERALS.items():
        assert reason.strip(), f"{value} 에 근거가 없다"


def test_the_allow_list_has_no_dead_entries():
    """쓰이지 않는 등재가 남으면 목록이 「미래를 위한 여유」가 되고, 그때부터 검사가 아니다."""
    found = set(_literals(LOCAL_ENGINE))
    dead = sorted(set(ALLOWED_LITERALS) - found)
    assert not dead, f"허용 목록에 있으나 코드에 없는 항목: {dead} — 지워라"


# --------------------------------------------------------------------------
# `app.js` — 리터럴이 아니라 **출처**를 본다
# --------------------------------------------------------------------------

def _expected_timeouts() -> dict:
    import json

    contract = json.loads(
        (Path(__file__).resolve().parents[2] / "contracts" / "openapi.json").read_text(encoding="utf-8")
    )
    profiles = contract["x-boundary-conditions"]["profiles"]
    return {
        "/api/analyze": profiles["analyze"]["clientTimeoutMs"],
        "/api/chat": profiles["chat"]["clientTimeoutMs"],
        "/api/regions": profiles["read"]["clientTimeoutMs"],
        "/api/health": profiles["read"]["clientTimeoutMs"],
        "/api/meta": profiles["read"]["clientTimeoutMs"],
    }


def test_the_screen_reads_its_timeouts_from_the_contract():
    """SPEC 8.3 #3 — 확정값은 계약 파일에만 존재한다. 프론트가 숫자를 다시 쓰지 않는다.

    예전 `app.js` 는 `ANALYZE_TIMEOUT_MS = 15000` · `FETCH_TIMEOUT_MS = 4500` 을
    들고 있었고 8.3.2 확정값(5,000 / 3,000)보다 낡아 있었다 (계약 결정 #34).

    ★ 스니펫을 여기 다시 적어 검사하지 않는다 — 그러면 테스트가 세 번째 사본이 된다.
      **`app.js` 를 node 에 올려 그 파일의 `timeoutFor` 를 실제로 호출**하고 계약값과 맞춘다.
    """
    import json

    expected = _expected_timeouts()
    got = run_js(
        """
        return JSON.parse(PATHS).reduce(function (acc, p) {
          acc[p] = globalThis.HomeCompass.timeoutFor(p);
          return acc;
        }, {});
        """,
        include_screen=True,
        extra_globals={"PATHS": json.dumps(sorted(expected))},
    )
    assert got == expected


def test_no_timeout_value_is_written_anywhere_in_the_screen_code():
    """★ `timeoutFor` **밖에서** 숫자가 되살아나는 경로를 덮는다 (코디네이터 조건 4).

    `crosscheck/test_openapi_contract.py` 의 분기 검사는 `timeoutFor` 함수 본문만 긁으므로,
    다른 자리에 `var ANALYZE_TIMEOUT_MS = 5000` 이 생기면 그쪽은 잡지 못한다. 여기서는
    파일 전체에서 계약의 타임아웃 값과 폐기된 옛 값을 **리터럴로** 찾는다.
    """
    values = set(_expected_timeouts().values()) | {4500, 15000}  # 폐기된 옛 예산 둘
    code = _strip_comments_and_strings((FRONTEND_DIR / "app.js").read_text(encoding="utf-8"))
    found = sorted({v for v in values if re.search(r"(?<![\w.$])" + str(v) + r"(?![\w.])", code)})
    assert not found, (
        f"`app.js` 코드에 타임아웃 값이 리터럴로 적혀 있다: {found} — "
        "값은 계약 파일에만 존재해야 한다 (SPEC 8.3 #3)."
    )


def test_the_screen_exports_no_judgement_engine():
    """`app.js` 가 판정 함수를 내보내면 그 표면이 곧 두 번째 판정 경로가 된다.

    예전 `HomeCompass` 는 `engineAffordability` · `enginePolicies` ·
    `POLICY_CATALOG` · `MOCK_REGIONS` · `MOCK_RESPONSE` 를 내보내고 있었다.
    """
    forbidden = [
        "engineAffordability", "engineScenarios", "enginePolicies", "engineRisk",
        "buildMockResponse", "POLICY_CATALOG", "MOCK_REGIONS", "MOCK_RESPONSE",
    ]
    source = (FRONTEND_DIR / "app.js").read_text(encoding="utf-8")
    code = _strip_comments_and_strings(source)
    leaked = [name for name in forbidden if re.search(r"(?<![\w$])" + name + r"(?![\w$])", code)]
    assert not leaked, f"`app.js` 코드에 판정 사본의 흔적이 남아 있다: {leaked}"
