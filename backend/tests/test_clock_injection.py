"""SPEC 5.3 클럭 주입 — 엔진은 시계를 읽지 않고 주입받는다.

SPEC 5.3 원문이 요구하는 것은 두 문장이다.

    엔진은 시계를 직접 읽지 않고 클럭을 주입받는다. 결정성 테스트는 클럭을 고정하고
    응답 **전체를 바이트 비교**한다. **필드를 빼고 비교하지 않는다 — 제외 목록은 자라기 때문이다.**

그전까지 저장소는 정반대였다. `engines/__init__.py` 가 `datetime.now(timezone.utc)` 를
직접 읽어 `meta.generatedAt` 을 만들었고, 그래서 결정성 테스트가 응답 전체를 비교하지
못한 채 `snapshot_util.VOLATILE_KEYS` 라는 **제외 목록**을 두고 있었다. 항목이 하나뿐이었던
것은 다행이지 규약이 지켜진 것이 아니다.

이 파일이 고정하는 것은 넷이다.

  (a) 클럭을 고정하면 **응답 전체**가 바이트 동일하다 — 빼는 필드가 없다
  (b) 클럭을 다르게 주면 `meta.generatedAt` **만** 달라진다. 이걸 안 보면 주입한 시각이
      판정의 다른 곳으로 새는 것을 잡지 못한다
  (c) `engines/` 어디에도 시계를 읽는 호출이 없다 — 되돌아오는 것을 막는 파수병
      (`api/test_store_cutover.py` 가 `lru_cache` 에 대해 하는 것과 같은 모양이다)
  (d) 제외 목록이 **비어서라도 남아 있지 않다.** 빈 목록이 남으면 다음 사람이 거기에
      하나를 더한다. 자리를 없애는 것이 목록을 비우는 것보다 강하다
  (e) **판정 입력을 꺼내는 쪽도** 시계를 읽지 않는다. 엔진에 고정 클럭을 주면서 활성 규칙은
      벽시계로 물으면 그 테스트는 돌리는 날에 따라 달라진다 — 엔진만 막은 (c) 의 사각지대다

`meta.generatedAt` 의 표기(`%Y-%m-%dT%H:%M:%SZ`)는 **바뀌지 않는다.** 계약 결정 #4 의
「`Z` 표기 금지」는 `observed_at` · `fetched_at` 에 걸리는 규칙이고, SPEC 2.1 이
「현행 `meta.generatedAt` 은 `Z` 표기 — 별개 필드이며 변경하지 않는다」고 예외를 적어 두었다.
"""

from __future__ import annotations

import ast
import inspect
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from firsthome.engines import analyze  # noqa: E402
import snapshot_util  # noqa: E402
from decision_inputs import FROZEN_NOW, store_policies, store_regions  # noqa: E402
from seed_constants import frozen_seed  # noqa: E402
from snapshot_util import dumps  # noqa: E402

CONSTANTS = frozen_seed()
REGIONS = store_regions()
# 활성 규칙 질의도 **같은 고정 클럭**으로 한다. 벽시계로 물으면 판정만 고정되고 규칙
# 목록은 돌리는 날에 따라 달라진다 — 아래 (e) 절이 그것을 파수병으로 막는다.
POLICIES = store_policies(FROZEN_NOW)

PROFILE = {
    "age": 28,
    "annualIncomeKRW": 42_000_000,
    "monthlyNetIncomeKRW": 2_900_000,
    "liquidAssetsKRW": 30_000_000,
    "existingDebtMonthlyKRW": 0,
    "householdSize": 1,
    "regionCode": "11440",
}

#: 두 번째 클럭. **연·월·일·시·분·초가 전부 달라야 한다.**
#:
#: 처음에는 `+97일 13:41:07` 로 잡았다가 변이 심기에서 걸렸다 — 클럭을 `now.year` 로만
#: 새게 만든 변이가 통과했다. 두 시각의 연도가 같아서(둘 다 2026) 「샜는데도 응답이
#: 동일한」 경로가 남아 있었던 것이다. 한 성분이라도 겹치면 그 성분으로 새는 누출을
#: 이 파일이 못 잡는다.
OTHER_NOW = FROZEN_NOW + timedelta(days=400, hours=13, minutes=41, seconds=7)

ENGINES_DIR = Path(__file__).resolve().parents[1] / "src" / "firsthome" / "engines"

#: 시계를 읽는 호출. 판정 경로에 있으면 그 자리가 곧 SPEC 5.3 위반이다.
_CLOCK_ATTRS = {"now", "utcnow", "today", "fromtimestamp", "time", "monotonic", "perf_counter"}


def _run(now: datetime) -> dict:
    return analyze(PROFILE, constants=CONSTANTS, regions=REGIONS, policies=POLICIES, now=now)


# --- (a) 클럭을 고정하면 응답 전체가 바이트 동일하다 -------------------------


def test_a_fixed_clock_makes_the_whole_response_byte_identical():
    """SPEC 9.2 #5 결정성 — **응답 전체**를 비교한다. 빼는 필드가 없다."""
    first = dumps(_run(FROZEN_NOW))
    second = dumps(_run(FROZEN_NOW))
    assert first == second


def test_the_comparison_actually_covers_generated_at():
    """(a) 가 의미를 가지려면 비교 대상 안에 `generatedAt` 이 실제로 들어 있어야 한다.

    이 검사가 없으면 어느 날 필드가 응답에서 빠져도 위 테스트는 초록으로 통과한다 —
    「전체를 비교한다」가 「비교할 것이 없다」로 조용히 바뀌는 경로다.
    """
    assert "generatedAt" in dumps(_run(FROZEN_NOW))


# --- (b) 클럭을 바꾸면 generatedAt 만 달라진다 -------------------------------


def test_moving_the_clock_moves_generated_at_and_nothing_else():
    """주입한 시각이 판정의 다른 곳으로 새지 않는가.

    (a) 만으로는 잡지 못한다 — 클럭이 어딘가 더 쓰이고 있어도 **같은 클럭을 두 번** 주면
    응답은 여전히 동일하기 때문이다. 다르게 줘 봐야 샌 자리가 드러난다.
    """
    early, late = _run(FROZEN_NOW), _run(OTHER_NOW)

    assert early["meta"]["generatedAt"] != late["meta"]["generatedAt"], (
        "클럭을 바꿨는데 generatedAt 이 그대로다 — 주입한 시각이 쓰이지 않고 있다")

    early["meta"].pop("generatedAt")
    late["meta"].pop("generatedAt")
    assert dumps(early) == dumps(late), "generatedAt 말고 다른 필드가 클럭에 따라 움직인다"


def test_generated_at_is_the_injected_instant_in_the_unchanged_z_form():
    """표기는 현행 그대로다 (SPEC 2.1 · 계약 결정 #4 의 명시적 예외)."""
    assert _run(FROZEN_NOW)["meta"]["generatedAt"] == "2026-01-01T00:00:00Z"


def test_a_non_utc_clock_is_stamped_as_the_same_instant():
    """`Z` 는 UTC 라는 **주장**이다. KST 로 주면 그 시각을 UTC 로 옮겨 찍어야 한다.

    옮기지 않으면 응답이 09:00 만큼 틀린 시각을 UTC 인 척 적는다.
    """
    kst = timezone(timedelta(hours=9))
    same_instant = FROZEN_NOW.astimezone(kst)
    assert _run(same_instant)["meta"]["generatedAt"] == _run(FROZEN_NOW)["meta"]["generatedAt"]


def test_a_naive_clock_is_refused():
    """타임존 없는 시각은 거부한다 — 받아 주면 로컬 시각을 `Z` 로 적게 된다."""
    with pytest.raises(ValueError):
        _run(datetime(2026, 1, 1, 0, 0, 0))


def test_the_clock_has_no_default():
    """fail-closed (SPEC 5.1.1). 기본값을 두면 그 기본값이 곧 시계 읽기다."""
    with pytest.raises(TypeError):
        analyze(PROFILE, constants=CONSTANTS, regions=REGIONS, policies=POLICIES)


# --- (c) 엔진은 시계를 읽지 않는다 -------------------------------------------


def test_the_engines_package_never_reads_the_clock():
    """되돌아오는 것을 막는 파수병. 행동 테스트가 아니라 구조 검사다.

    문자열 검색이 아니라 AST 로 본다 — 줄 단위로 훑으면 이 사고를 서술한 주석·docstring 이
    스스로 걸리고, 그런 검사는 결함이 아니라 설명을 금지하게 된다
    (`api/test_store_cutover.py` 가 캐시 검사에서 같은 이유로 AST 를 쓴다).
    """
    offenders = []
    for path in sorted(ENGINES_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr in _CLOCK_ATTRS:
                offenders.append(f"{path.name}:{node.lineno}: .{func.attr}()")
    assert not offenders, (
        "engines 가 시계를 직접 읽는다 (SPEC 5.3 — 클럭은 주입받는다):\n" + "\n".join(offenders)
    )


# --- (d) 제외 목록이 남아 있지 않다 ------------------------------------------


def test_the_snapshot_helper_keeps_no_exclusion_list():
    """비워서 남기는 것도 금지다 — 빈 목록이 있으면 다음 사람이 거기에 하나를 더한다."""
    assert not hasattr(snapshot_util, "VOLATILE_KEYS"), (
        "제외 목록이 되살아났다. SPEC 5.3 은 「필드를 빼고 비교하지 않는다」이다.")


def test_the_golden_snapshot_carries_generated_at():
    """골든이 **응답 전체**를 붙들고 있는가 — 커밋본에서 직접 확인한다."""
    committed = json.loads(snapshot_util.NUMERIC_PATH.read_text(encoding="utf-8"))
    stamped = [
        case_id
        for case_id, result in committed.items()
        if isinstance(result.get("meta"), dict) and "generatedAt" in result["meta"]
    ]
    assert stamped, "골든 숫자 스냅샷에 generatedAt 이 하나도 없다 — 아직 빼고 비교하고 있다"


# --- (e) 판정 입력을 꺼내는 쪽도 시계를 읽지 않는다 ---------------------------
#
# (c) 는 `engines/` 만 본다. 그런데 판정 입력의 절반인 **활성 규칙 질의**는 테스트 쪽
# 헬퍼(`decision_inputs.store_policies`)에 있고, 거기 `at` 에 기본값이 있으면 그 기본값이
# 곧 시계 읽기다 (계약 결정 #24 가 `analyze(now=...)` 에 대해 내린 결정과 같은 부류이며,
# 위 `test_the_clock_has_no_default` 가 엔진 쪽에서 지키는 것과 같은 규율이다).
#
# 지금은 시드 규칙 8건이 `effective_from` · `effective_to` 가 둘 다 NULL 이라 어느 시각에도
# 활성이므로 결과가 같다 (계약 결정 #5 · #6). **그래서 지금 닫는다** — 승인 흐름이 유효기간
# 있는 `RuleVersion` 을 만들기 시작하면 그때는 [돌리는 날에 따라 다른 결과]가 되고,
# 그 원인을 찾는 비용이 지금 이 파수병을 두는 비용보다 훨씬 크다. PR #39 가 crosscheck 의
# 한 곳을 같은 이유로 닫았고, 여기서 나머지를 닫는다.

TESTS_DIR = Path(__file__).resolve().parent

#: 활성 규칙 질의. 인자 없이 부르면 그 순간 벽시계다.
_ACTIVE_RULE_QUERY = "store_policies"


def _called_names(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _active_rule_queries(source: str, filename: str) -> list[tuple[int, int]]:
    """`store_policies(...)` 호출의 (줄번호, 인자 개수) 목록.

    문자열 검색이 아니라 AST 다 — (c) 와 같은 이유이며, 여기서는 이유가 하나 더 있다.
    이 사고를 설명하는 주석·docstring 이 스스로 걸리면 검사가 설명을 금지하게 된다.
    """
    found = []
    for node in ast.walk(ast.parse(source, filename=filename)):
        if isinstance(node, ast.Call) and _called_names(node) == _ACTIVE_RULE_QUERY:
            found.append((node.lineno, len(node.args) + len(node.keywords)))
    return found


def test_the_active_rule_query_has_no_default_clock():
    """fail-closed. 기본값을 두면 그 기본값이 곧 시계 읽기다 (SPEC 5.1.1 · 결정 #24)."""
    parameter = inspect.signature(store_policies).parameters["at"]
    assert parameter.default is inspect.Parameter.empty, (
        "store_policies(at=...) 에 기본값이 돌아왔다. 기본값이 있으면 "
        "인자를 빠뜨린 호출이 조용히 벽시계를 읽는다 — 아래 정적 검사보다 이쪽이 먼저다."
    )


def test_the_input_helper_never_reads_the_clock():
    """`decision_inputs` 모듈 자체에 시계 읽기가 없다 — 기본값을 없애도 본문에서 읽으면 같다."""
    path = TESTS_DIR / "decision_inputs.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    offenders = [
        f"{path.name}:{node.lineno}: .{node.func.attr}()"
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in _CLOCK_ATTRS
    ]
    assert not offenders, (
        "판정 입력을 꺼내는 헬퍼가 시계를 읽는다 (SPEC 5.3):\n" + "\n".join(offenders)
    )


def test_no_test_module_queries_active_rules_on_the_wall_clock():
    """★ 파수병 — `backend/tests/` 전수. 인자 없는 호출이 곧 벽시계 질의다."""
    offenders = []
    for path in sorted(TESTS_DIR.rglob("*.py")):
        for lineno, argcount in _active_rule_queries(
            path.read_text(encoding="utf-8"), str(path)
        ):
            if argcount == 0:
                offenders.append(f"{path.relative_to(TESTS_DIR)}:{lineno}")
    assert not offenders, (
        "활성 규칙을 벽시계로 묻는 호출이 있다 — 판정은 고정 클럭인데 규칙 질의만 "
        "돌리는 날에 따라 달라진다. `store_policies(FROZEN_NOW)` 로 부른다:\n"
        + "\n".join(offenders)
    )


def test_the_guard_actually_flags_a_wall_clock_query():
    """★ 프로브 — 파수병이 진짜로 잡는지 본다.

    이 프로젝트에서 「규칙이 표에만 남고 아무것도 안 잡는」 일이 세 번 있었다. 위 검사가
    초록인 것은 위반이 없어서일 수도 있고 스캐너가 아무것도 못 보고 있어서일 수도 있다.
    그 둘을 가르는 것은 **일부러 심은 위반이 실제로 걸리는지** 뿐이다.
    """
    violating = "policies = store_policies()\n"
    compliant = "policies = store_policies(FROZEN_NOW)\nother = store.policies()\n"

    assert _active_rule_queries(violating, "<probe>") == [(1, 0)], (
        "심은 위반을 스캐너가 못 봤다 — 위 파수병은 아무것도 지키지 않는다"
    )
    assert [argcount for _, argcount in _active_rule_queries(compliant, "<probe>")] == [1], (
        "고정 클럭을 넘긴 호출을 위반으로 세거나, 같은 이름의 다른 속성 호출을 함께 셌다"
    )


def test_the_guard_actually_reaches_the_real_call_sites():
    """프로브가 통과해도 **실물 파일**을 못 읽고 있으면 파수병은 여전히 비어 있다."""
    seen = {
        f"{path.relative_to(TESTS_DIR)}:{lineno}"
        for path in sorted(TESTS_DIR.rglob("*.py"))
        for lineno, _ in _active_rule_queries(path.read_text(encoding="utf-8"), str(path))
    }
    assert len(seen) >= 7, (
        f"스캐너가 실제 호출부를 {len(seen)}곳밖에 못 찾았다. 호출부가 사라진 것이 아니라면 "
        f"스캐너가 파일을 못 읽고 있는 것이다: {sorted(seen)}"
    )
