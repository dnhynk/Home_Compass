"""로컬 판정 경로와 백엔드 엔진이 **같은 입력에 같은 숫자를 내는가** (SPEC D-11 · 계약 결정 #36).

■ 이 파일이 무엇을 붙들고 있는가

이 과업의 지배적 실패 양상은 「조용히 다른 숫자를 내는 것」이다. 로컬 경로와 백엔드가
다른 답을 내면 화면은 아무 말도 하지 않는다 — 예선에서 실제로 일어난 사고이고(Part 0-A),
D-11 이 존재하는 이유다.

PR #59 의 「검증하지 않은 것 ②」가 그 구멍을 명시적으로 6단계에 넘겼다 —
*「필드 집합의 일치만 기계로 고정했고 **판정 로직이 같은지는 생성물이 보장할 수 없다.**
그 동등성 테스트는 6단계가 가져와야 한다.」* **이 파일이 그것이다.**

「같게 짰다」는 답이 아니므로, 여기서는 **양쪽을 실제로 돌려 결과를 비교한다.**

  파이썬 변  `firsthome.engines.analyze()` — 저장소의 상수·지역·활성 규칙을 주입받아
  JS 변      `frontend/local_engine.js` — `frontend/generated/*.js` 를 읽어
  모집단     `contracts/regression_profiles.json` 프로필 x 저장소 지역 **전수**
  비교 대상  SPEC 5.3 의 numeric 갈래 — 판정 숫자와 상태 필드
  제외       `rationale` · `reasons` · `summary` · `note` · `disclaimer`
             (SPEC 5.3 — 문자열은 계약이 아니다. 코디네이터 결정 2026-08-15 조건 4)

■ 이 파수병이 공허해지지 않게 하는 장치 (코디네이터 결정 조건 3)

생성물이 없거나 로컬 경로가 꺼져 있으면 비교할 것이 없어 **그냥 통과**할 수 있다.
그래서 셋을 함께 둔다.
  · 비교한 사례 수가 하한 이상인지 직접 단언한다.
  · **프로브** — 로컬 경로가 읽는 상수 하나를 흔들어 놓고 비교가 **실제로 깨지는지** 본다.
  · 생성물 하나를 빼면 로컬 경로가 **꺼지는지**(조용히 기본값으로 도는 것이 아니라) 본다.

■ 계보·등급도 여기서 대조한다 (D-13, 2026-08-15)

예전에는 `NUMERIC_ONLY_ON_LOCAL = ("dataGrade", "provenance")` 로 그 둘을 **JS 쪽에서
떼어내고** 비교했다. 백엔드에 그 필드가 없었기 때문이다. D-13 이 들어오면서 그 목록은
비었고, **두 계보가 같은지가 이 파일의 두 번째 산출물**이 되었다.

이 확장이 붙드는 것은 하나다 — **두 산정이 갈라지는 것.** 로컬 경로는 백엔드가 없을 때
자기 사실(생성물)로 스스로 등급을 산정해야 하고(그래야 오프라인에서 판정이 성립한다),
그래서 SPEC 2.4 를 구현한 코드가 **두 벌** 존재한다. 두 벌이 각자 자라면 시민은 같은
프로필에 대해 온라인에서는 `C`, 오프라인에서는 `A` 를 본다. 계약 결정 #37 이 지목한
지배적 실패 양상이 그것이다.

  비교 대상  `provenance` 배열 전체 + `dataGrade.grade` + 사유의 **유형과 지시 대상**
  제외       `message` (SPEC 5.3 의 text 갈래. 문자열은 계약이 아니다)

`fact` 는 **제외하지 않는다.** 사람이 읽는 문자열이지만 그것이 곧 [어느 사실인가]의
이름이고, 양쪽이 다른 이름을 붙이면 화면의 계보 목록이 경로에 따라 달라진다.
"""

from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from firsthome.common import DISCLAIMER  # noqa: E402
from firsthome.engines import analyze  # noqa: E402
from firsthome.main import (  # noqa: E402
    MODEL_CONSTANT_PROVENANCE,
    MODEL_CONSTANTS,
    build_lineage,
)
from firsthome.store import store_from_env  # noqa: E402

from decision_inputs import FROZEN_NOW, store_policies, store_regions  # noqa: E402
from js_runner import run_js  # noqa: E402
from snapshot_util import load_profiles, split_snapshot  # noqa: E402

#: 로컬 경로에만 있는 최상위 키. **비어 있는 것이 정상이다** — D-13 이 백엔드에 같은
#: 필드를 실으면서 비웠다. 여기에 키를 다시 더하는 것은 [비교하지 않겠다]는 뜻이므로
#: 아래 `test_nothing_is_quietly_excluded_from_the_comparison` 가 그 회귀를 막는다.
NUMERIC_ONLY_ON_LOCAL: tuple[str, ...] = ()

#: 계보 비교에서 빼는 키 — **여기 하나뿐이다.** 설명 문장은 SPEC 5.3 의 text 갈래다.
LINEAGE_TEXT_KEYS = ("message",)

#: `FROZEN_NOW` 를 JS 에 넘기는 형태 — 에포크 밀리초 하나. 양쪽이 같은 순간을 본다.
FROZEN_NOW_MS = int(FROZEN_NOW.timestamp() * 1000)


def _store_constants() -> dict:
    """`api` 가 엔진에 주입하는 바로 그 매핑. 계약 파일이 아니라 **저장소**에서 읽는다."""
    with store_from_env() as store:
        return store.model_constants.as_mapping()


def _cases() -> list[tuple[str, str, dict]]:
    """프로필 x 지역 전수. 지역을 도는 이유는 수도권/그 외 상한(F-4)과
    시장 여건이 지역마다 갈리기 때문이며, 프로필의 `regionCode` 만 쓰면 그 축이 안 돌아간다.

    프로필 자신의 `regionCode`(없는 지역 축 `99999` 포함)도 한 건씩 남긴다 —
    SPEC 9.2.2 가 그 축을 요구한다.
    """
    regions = store_regions()
    cases: list[tuple[str, str, dict]] = []
    for entry in load_profiles():
        cases.append((entry["id"], "as-written", entry["profile"]))
        for region in regions:
            profile = dict(entry["profile"])
            profile["regionCode"] = region["code"]
            cases.append((entry["id"], region["code"], profile))
    return cases


CASES = _cases()


def _store_lineage_inputs() -> tuple[list, list]:
    """계보 조립의 재료 — `Region` 레코드와 활성 `RuleVersion`.

    `store_regions()` 는 엔진 입력(dict)이라 계보가 `source` 한 줄로 접혀 있다.
    D-13 은 **접히기 전**의 것을 쓴다 (`main.read_region_records` 와 같은 이유).
    """
    with store_from_env() as store:
        return list(store.regions.list()), list(store.rule_versions.active(FROZEN_NOW))


def _python_side() -> tuple[dict, dict]:
    """(numeric 스냅샷, 계보) 두 벌. 계보는 API 계층이 조립하므로 `build_lineage` 를 부른다.

    엔진이 아니라 api 가 계보를 조립하는 것은 SPEC 1.2 의 방향 때문이다 — 엔진은 저장소를
    모른다. 그래서 이 파수병의 파이썬 변도 `engines.analyze()` 뒤에 같은 함수를 부른다.
    """
    constants = _store_constants()
    regions = store_regions()
    policies = store_policies(FROZEN_NOW)
    region_records, versions = _store_lineage_inputs()
    out, lineage = {}, {}
    for profile_id, region_key, profile in CASES:
        key = f"{profile_id}@{region_key}"
        try:
            result = analyze(
                profile,
                constants=constants,
                regions=regions,
                policies=policies,
                now=FROZEN_NOW,
            )
        except ValueError as exc:
            out[key] = {"raised": "ValueError", "message": str(exc)}
            continue
        result.update(build_lineage(
            result, region_records, versions,
            constants=MODEL_CONSTANTS,
            constant_provenance=MODEL_CONSTANT_PROVENANCE,
        ))
        lineage[key] = _lineage_of(result)
        numeric, _text = split_snapshot(result)
        out[key] = numeric
    return out, lineage


def _lineage_of(response: dict) -> dict:
    """`provenance` + `dataGrade` 만 남기고 설명 문장을 걷어낸다 (SPEC 5.3 text 갈래)."""
    return {
        "provenance": response["provenance"],
        "dataGrade": {
            "grade": response["dataGrade"]["grade"],
            "reasons": [
                {k: v for k, v in reason.items() if k not in LINEAGE_TEXT_KEYS}
                for reason in response["dataGrade"]["reasons"]
            ],
        },
    }


def _js_side(mutation: str = "") -> tuple[dict, dict]:
    """node 프로세스 **한 번**으로 전 사례를 돌린다.

    `mutation` 은 프로브용 JS 조각이다 — 생성물을 메모리에서만 흔들어 비교가
    실제로 깨지는지 확인한다. 파일은 건드리지 않는다 (생성물은 손으로 고치지 않는다).
    """
    body = (
        mutation
        + """
        var cases = JSON.parse(CASES_JSON);
        var now = Number(FROZEN_NOW_MS);
        var engine = globalThis.FirstHomeLocalEngine;
        var out = {};
        cases.forEach(function (c) {
          var key = c[0] + '@' + c[1];
          try {
            out[key] = engine.analyze(c[2], { now: now });
          } catch (e) {
            out[key] = { raised: 'ValueError', message: String(e.message) };
          }
        });
        return out;
        """
    )
    raw = run_js(
        body,
        extra_globals={
            "CASES_JSON": json.dumps([[a, b, c] for a, b, c in CASES], ensure_ascii=False),
            "FROZEN_NOW_MS": FROZEN_NOW_MS,
        },
    )
    out, lineage = {}, {}
    for key, value in raw.items():
        if isinstance(value, dict) and value.get("raised"):
            out[key] = value
            continue
        lineage[key] = _lineage_of(value)
        for extra in NUMERIC_ONLY_ON_LOCAL:
            value.pop(extra, None)
        numeric, _text = split_snapshot(value)
        out[key] = numeric
    return out, lineage


PYTHON_SIDE, PYTHON_LINEAGE = _python_side()
JS_SIDE, JS_LINEAGE = _js_side()


def _first_difference(left, right, path=""):
    """어디서 갈렸는지 한 곳만 콕 집어 돌려준다. 전체 덤프는 읽히지 않는다."""
    if isinstance(left, dict) and isinstance(right, dict):
        for key in sorted(set(left) | set(right)):
            if key not in left:
                return f"{path}/{key}: 파이썬에 없음 (JS={right[key]!r})"
            if key not in right:
                return f"{path}/{key}: JS 에 없음 (파이썬={left[key]!r})"
            found = _first_difference(left[key], right[key], f"{path}/{key}")
            if found:
                return found
        return None
    if isinstance(left, list) and isinstance(right, list):
        if len(left) != len(right):
            return f"{path}: 길이가 다르다 파이썬={len(left)} JS={len(right)}"
        for index, (a, b) in enumerate(zip(left, right)):
            found = _first_difference(a, b, f"{path}/{index}")
            if found:
                return found
        return None
    if left != right:
        return f"{path}: 파이썬={left!r} != JS={right!r}"
    return None


# --------------------------------------------------------------------------
# 본 검사 — 사례별로 갈라 두어 어느 프로필·지역에서 어긋났는지가 테스트 이름에 남는다
# --------------------------------------------------------------------------

@pytest.mark.parametrize("key", sorted(PYTHON_SIDE), ids=sorted(PYTHON_SIDE))
def test_the_local_path_and_the_backend_agree_on_every_number(key):
    difference = _first_difference(PYTHON_SIDE[key], JS_SIDE[key])
    assert difference is None, (
        f"로컬 판정 경로가 백엔드와 다른 값을 냈다 [{key}] — {difference}\n"
        "두 경로가 조용히 갈리는 것이 D-11 이 막으려는 상태다."
    )


# --------------------------------------------------------------------------
# 이 파수병이 공허하지 않다는 것의 증거 (코디네이터 결정 2026-08-15 조건 3)
# --------------------------------------------------------------------------

def test_the_comparison_actually_covered_something():
    """사례가 0건이면 위 테스트는 아무것도 검증하지 않고 초록이 된다."""
    assert len(CASES) >= 100, len(CASES)
    assert set(PYTHON_SIDE) == set(JS_SIDE)
    graded = [k for k, v in PYTHON_SIDE.items() if "raised" not in v]
    assert len(graded) >= 100, f"판정이 성립한 사례가 {len(graded)}건뿐이다"
    # 없는 지역 축(SPEC 9.2.2)이 실제로 양쪽에서 거부되는지도 함께 본다.
    rejected = [k for k, v in PYTHON_SIDE.items() if "raised" in v]
    assert rejected, "없는 지역 축이 모집단에서 빠졌다"
    for key in rejected:
        assert JS_SIDE[key].get("raised") == "ValueError", (
            f"[{key}] 파이썬은 판정을 거부했는데 JS 는 숫자를 냈다 — "
            "조용히 다른 답을 내는 바로 그 형태다"
        )


# --------------------------------------------------------------------------
# 계보·등급 (D-13) — **두 산정이 갈라지는 것**을 붙든다
# --------------------------------------------------------------------------

@pytest.mark.parametrize("key", sorted(PYTHON_LINEAGE), ids=sorted(PYTHON_LINEAGE))
def test_the_local_path_and_the_backend_agree_on_the_lineage_and_the_grade(key):
    difference = _first_difference(PYTHON_LINEAGE[key], JS_LINEAGE[key])
    assert difference is None, (
        f"로컬 판정 경로가 백엔드와 다른 계보·등급을 냈다 [{key}] — {difference}\n"
        "SPEC 2.4 를 구현한 코드가 두 벌 있고, 두 벌이 각자 자라면 시민은 같은 프로필에 "
        "온라인/오프라인에서 다른 등급을 본다 (계약 결정 #37)."
    )


def test_nothing_is_quietly_excluded_from_the_comparison():
    """★ 제외 목록이 자라지 않게 붙든다.

    이 파일이 실제로 비교하지 않는 것은 **설명 문장 하나**뿐이다. 목록이 늘어나면
    파수병은 남아 있는데 붙드는 것이 줄고, 그 상태가 이 저장소에서 이미 두 번 나왔다.
    """
    assert NUMERIC_ONLY_ON_LOCAL == (), (
        "로컬 전용 키가 다시 생겼다 — 그 키는 비교되지 않는다")
    assert LINEAGE_TEXT_KEYS == ("message",), (
        "계보 비교의 제외 목록이 늘었다. `message` 밖의 것을 빼려면 그것이 왜 계약이 "
        "아닌지를 먼저 적어야 한다 (SPEC 5.3)")


def test_the_lineage_comparison_actually_covered_something():
    """비교 대상이 비어 있으면 위 테스트는 아무것도 검증하지 않고 초록이 된다."""
    assert set(PYTHON_LINEAGE) == set(JS_LINEAGE)
    assert len(PYTHON_LINEAGE) >= 100, len(PYTHON_LINEAGE)
    sample = PYTHON_LINEAGE[sorted(PYTHON_LINEAGE)[0]]
    kinds = {item["factKind"] for item in sample["provenance"]}
    assert kinds == {"region_field", "rule_version", "model_constant"}, kinds
    assert sample["dataGrade"]["reasons"], "사유가 0건이면 등급 비교가 사실상 한 글자다"


def test_both_sides_grade_the_same_set_of_model_constants():
    """★ 상수 목록이 갈리면 등급도 갈린다. **어디서 갈렸는지를 이름으로 말하게 한다.**

    파이썬은 수요측(`required_constant_keys()`)을, JS 는 생성물의 엔진 접두사를 본다.
    지금은 두 집합이 같지만 같다는 것이 구조로 보장되지는 않는다 — 소비되지 않는
    `risk.*` 키가 하나 등재되면 JS 만 그것을 등급에 넣는다. 위 배열 비교로도 잡히지만
    그때 메시지는 「길이가 다르다」뿐이라 원인을 말하지 못한다.
    """
    def constant_facts(lineage):
        return {item["fact"] for item in lineage["provenance"]
                if item["factKind"] == "model_constant"}

    key = sorted(PYTHON_LINEAGE)[0]
    only_python = constant_facts(PYTHON_LINEAGE[key]) - constant_facts(JS_LINEAGE[key])
    only_js = constant_facts(JS_LINEAGE[key]) - constant_facts(PYTHON_LINEAGE[key])
    assert not only_python and not only_js, (
        f"등급 산정에 들어간 상수가 다르다. 파이썬에만: {sorted(only_python)} / "
        f"JS 에만: {sorted(only_js)}")


def test_a_shaken_verification_actually_breaks_the_grade_comparison():
    """★ 프로브 — 로컬 계보의 `verification` 하나를 흔들면 등급 비교가 **깨져야 한다.**

    깨지지 않으면 위 계보 비교는 「무조건 통과하던 검사」다. 생성물 파일은 건드리지 않고
    **메모리에서만** 흔든다.

    `verified` 로 올리는 방향인 것이 요점이다 — 등급을 **좋게** 만드는 조작이 통과하면
    이 파수병은 정확히 막아야 할 것을 막지 못한다.
    """
    _numeric, shaken = _js_side(
        mutation="""
        var e = globalThis.FIRSTHOME_MODEL_CONSTANTS.entries;
        Object.keys(e).forEach(function (k) {
          if (e[k].provenance.verification === 'unverified') e[k].provenance.verification = 'verified';
        });
        globalThis.FIRSTHOME_REGIONS.regions.forEach(function (r) {
          Object.keys(r.fieldProvenance).forEach(function (f) {
            if (r.fieldProvenance[f].verification === 'unverified') {
              r.fieldProvenance[f].verification = 'verified';
            }
          });
        });
        """
    )
    differing = [key for key in PYTHON_LINEAGE
                 if _first_difference(PYTHON_LINEAGE[key], shaken[key])]
    assert differing, (
        "로컬 계보의 unverified 를 전부 verified 로 올렸는데 비교가 하나도 깨지지 않았다 — "
        "이 파수병은 등급에 대해 아무것도 붙들고 있지 않다.")


def test_both_sides_refuse_to_evaluate_freshness_and_say_so():
    """신선도 미판정 표기가 **양쪽에서** 나온다. 한쪽만 나오면 등급의 뜻이 갈린다."""
    key = sorted(PYTHON_LINEAGE)[0]
    for side, lineage in (("파이썬", PYTHON_LINEAGE[key]), ("JS", JS_LINEAGE[key])):
        types = [r["type"] for r in lineage["dataGrade"]["reasons"]]
        assert types.count("freshness_not_evaluated") == 1, (
            f"{side} 쪽에 신선도 미판정 표기가 없거나 중복이다: {types}")


def test_a_shaken_constant_actually_breaks_the_comparison():
    """★ 프로브 — 로컬 상수 하나를 흔들면 이 비교가 **실제로 깨져야 한다.**

    깨지지 않으면 위 테스트는 「무조건 통과하던 검사」이며, 이 저장소에서 그 부류가
    이미 두 번 나왔다. 생성물 파일은 건드리지 않고 **메모리에서만** 흔든다.
    """
    shaken, _lineage = _js_side(
        mutation="""
        globalThis.FIRSTHOME_MODEL_CONSTANTS.entries['affordability.housing_cost_ratio_cap'].value = 0.31;
        """
    )
    differing = [key for key in PYTHON_SIDE if _first_difference(PYTHON_SIDE[key], shaken[key])]
    assert differing, (
        "상한 상수를 0.30 -> 0.31 로 흔들었는데 비교가 하나도 깨지지 않았다 — "
        "이 파수병은 아무것도 붙들고 있지 않다."
    )


def test_removing_one_artifact_turns_the_local_path_off():
    """생성물이 없으면 로컬 경로는 **동작하지 않는다** (D-11). 기본값으로 돌지 않는다."""
    reported = run_js(
        """
        delete globalThis.FIRSTHOME_MODEL_CONSTANTS;
        delete globalThis.window.FIRSTHOME_MODEL_CONSTANTS;
        var engine = globalThis.FirstHomeLocalEngine;
        var status = engine.status();
        var thrown = null;
        try { engine.analyze({ monthlyNetIncomeKRW: 3000000, regionCode: '11440' }, { now: 0 }); }
        catch (e) { thrown = String(e.message); }
        return { ready: status.ready, missing: status.missing, thrown: thrown };
        """
    )
    assert reported["ready"] is False
    assert any(m["global"] == "FIRSTHOME_MODEL_CONSTANTS" for m in reported["missing"])
    assert reported["thrown"] is not None, "생성물이 없는데 판정이 그대로 돌았다"
    assert "생성물" in reported["thrown"]


def test_the_local_path_refuses_to_read_a_clock_by_itself():
    """SPEC 5.3 — 시각은 주입받는다. 기본값을 두면 그 기본값이 곧 시계 읽기다."""
    thrown = run_js(
        """
        try { globalThis.FirstHomeLocalEngine.analyze({ regionCode: '11440' }); return null; }
        catch (e) { return String(e.message); }
        """
    )
    assert thrown is not None
    assert "시각을 주입" in thrown


def test_the_disclaimer_string_is_the_same_on_both_sides():
    """`meta.disclaimer` 는 SPEC 5.3 의 text 갈래라 위 비교에서 빠진다.

    그래서 **여기서 따로** 붙든다. 화면 문구이므로 `ModelConstant` 대상이 아니고
    (SPEC 5.1.2 비대상) 생성물에도 독립 항목으로 실리지 않지만, 갈리면 화면과
    백엔드가 다른 고지를 내보내게 된다.
    """
    js_value = run_js("return globalThis.FirstHomeLocalEngine.DISCLAIMER;")
    assert js_value == DISCLAIMER


def test_the_engine_version_comes_from_the_artifact_not_from_a_literal():
    """`meta.engineVersion` 이 손으로 쓴 문자열이면 판정이 바뀌어도 그대로 남는다."""
    from firsthome.common import ENGINE_VERSION

    js_value = run_js(
        """
        return globalThis.FirstHomeLocalEngine
          .analyze({ monthlyNetIncomeKRW: 3000000, regionCode: '11440' }, { now: Number(FROZEN_NOW_MS) })
          .meta.engineVersion;
        """,
        extra_globals={"FROZEN_NOW_MS": FROZEN_NOW_MS},
    )
    assert js_value == ENGINE_VERSION
