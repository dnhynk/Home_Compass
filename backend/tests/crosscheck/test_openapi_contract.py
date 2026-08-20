"""교차 테스트 — 계약 파일이 SPEC 이 요구한 것을 실제로 담고 있는가 (코디네이터 소유).

`test_generated_contracts_diff.py` 는 "커밋본 == 재생성본"만 본다. 그것만으로는
**빈 계약도 자기 자신과 일치한다.** 응답 스키마가 `{}` 인 채로 통과하면 SPEC 9.1.2 의
"2xx 만으로는 불합격"이 이름만 남는다. 그래서 내용을 여기서 따로 붙든다.

  1. OpenAPI 3.1 (JSON Schema 2020-12)                      D-12
  2. 응답 스키마가 비어 있지 않다                            9.1.2
  3. 모든 4xx·5xx 가 오류 봉투다                             8.1
  4. **단위**가 전 수치 필드에 정의되어 있다                 8.2 #4
  5. **반올림** 규칙이 계약에 있다                           8.2 #4
  6. `x-requires-role` **표기 자리**가 있고 어휘가 맞다      6.1 · Part 0-E #1
  7. **경계 조건**(타임아웃·재시도) 자리가 있다              8.3
  8. `x-serialization` 이 실제 직렬화를 서술한다             D-12
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "backend" / "src"))

OPENAPI = REPO_ROOT / "contracts" / "openapi.json"

#: SPEC 8.1 이 "기존 필드명 변경 금지"를 건 응답들.
CONTRACTED_PATHS = ("/api/analyze", "/api/regions", "/api/meta", "/api/health", "/api/chat")


@pytest.fixture(scope="module")
def doc() -> dict:
    return json.loads(OPENAPI.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def schemas(doc: dict) -> dict:
    return doc["components"]["schemas"]


def _operations(doc: dict):
    for path, item in doc["paths"].items():
        for method, operation in item.items():
            if method in ("get", "post", "put", "patch", "delete"):
                yield path, method, operation


def _is_numeric(schema: dict) -> bool:
    types = [schema.get("type")]
    types += [variant.get("type") for variant in schema.get("anyOf", [])]
    return any(t in ("integer", "number") for t in types)


# --- 1~3. 형식과 봉투 -------------------------------------------------------

def test_it_is_openapi_31(doc):
    """D-12 — OpenAPI 3.1 (JSON Schema 2020-12). 3.0 은 nullable 표기가 달라 생성물이 갈린다."""
    assert doc["openapi"].startswith("3.1."), doc["openapi"]


def test_every_contracted_path_is_present(doc):
    missing = [p for p in CONTRACTED_PATHS if p not in doc["paths"]]
    assert not missing, f"SPEC 8.1 이 계약으로 지정한 응답인데 계약 파일에 없다: {missing}"


def test_no_response_schema_is_vacuous(doc, schemas):
    """★ 빈 스키마는 무엇이든 통과시킨다. 스모크가 무력화되는 가장 흔한 경로다."""
    vacuous = []
    for path, method, operation in _operations(doc):
        for status, response in operation.get("responses", {}).items():
            content = (response.get("content") or {}).get("application/json")
            if content is None:
                vacuous.append(f"{method.upper()} {path} {status}: content 없음")
                continue
            schema = content.get("schema") or {}
            if not schema:
                vacuous.append(f"{method.upper()} {path} {status}: schema 가 빈 객체다")
                continue
            ref = schema.get("$ref")
            if ref and not (schemas.get(ref.rsplit("/", 1)[-1]) or {}).get("properties"):
                vacuous.append(f"{method.upper()} {path} {status}: {ref} 에 properties 가 없다")
    assert not vacuous, (
        "응답 스키마가 비어 있다. 이 상태로는 SPEC 9.1.2 의 스키마 검증이 아무것도 "
        f"잡지 못한다: {vacuous}")


def _response_schema_names(doc: dict, schemas: dict) -> set[str]:
    """응답에서 도달 가능한 컴포넌트 스키마 이름 (요청 전용 스키마와 가르기 위해)."""
    seen: set[str] = set()
    queue = [
        ((response.get("content") or {}).get("application/json") or {}).get("schema") or {}
        for _, _, operation in _operations(doc)
        for response in operation.get("responses", {}).values()
    ]
    while queue:
        node = queue.pop()
        if isinstance(node, dict):
            ref = node.get("$ref")
            if ref and ref.startswith("#/components/schemas/"):
                name = ref.rsplit("/", 1)[-1]
                if name not in seen:
                    seen.add(name)
                    queue.append(schemas.get(name) or {})
            queue.extend(v for v in node.values() if isinstance(v, (dict, list)))
        elif isinstance(node, list):
            queue.extend(v for v in node if isinstance(v, (dict, list)))
    return seen


def test_response_schemas_forbid_undeclared_fields(doc, schemas):
    """`additionalProperties: false` 가 없으면 계약에 없는 필드가 조용히 실린다.

    **응답에만 건다.** 우리가 만들어 내는 것에는 엄격하고 받는 것에는 관대한 쪽이
    맞다 — 요청 스키마를 닫으면 모르는 필드 하나에 422 가 나가고, 그것은 프론트가
    필드를 하나 더 보내는 순간 화면이 죽는다는 뜻이다. 요청 쪽을 닫는 것은 계약
    변경이므로 코디네이터 결정(SPEC 8.2)이며 여기서 몰래 하지 않는다.
    """
    lax = sorted(
        name for name in _response_schema_names(doc, schemas)
        if (schemas[name].get("type") == "object"
            and schemas[name].get("additionalProperties") is not False)
    )
    assert not lax, f"응답 스키마인데 additionalProperties 가 열려 있다: {lax}"


def test_request_schemas_stay_lenient(doc, schemas):
    """현행 동작을 못 박는다 — 요청 쪽이 조용히 엄격해지면 여기서 잡힌다.

    깨지는 것이 곧 "요청 계약을 바꾸려 한다"는 신호이고, 그것은 8.2 절차 대상이다.
    """
    request_only = {"ProfileRequest", "ChatRequest", "ChatMessage"} - _response_schema_names(doc, schemas)
    for name in sorted(request_only):
        assert schemas[name].get("additionalProperties") is not False, (
            f"{name} 이 모르는 필드를 거부하게 바뀌었다. 요청 계약 변경은 SPEC 8.2 절차다")


def test_every_error_status_uses_the_error_envelope(doc):
    """SPEC 8.1 — 오류 봉투도 계약이다."""
    wrong = []
    for path, method, operation in _operations(doc):
        for status, response in operation.get("responses", {}).items():
            if not status.isdigit() or int(status) < 400:
                continue
            schema = ((response.get("content") or {}).get("application/json") or {}).get("schema") or {}
            if schema.get("$ref") != "#/components/schemas/ErrorEnvelope":
                wrong.append(f"{method.upper()} {path} {status}: {schema}")
    assert not wrong, f"오류 봉투가 아닌 4xx/5xx 응답: {wrong}"


def test_the_error_envelope_shape_is_code_and_message(schemas):
    assert set(schemas["ErrorBody"]["properties"]) == {"code", "message"}
    assert set(schemas["ErrorEnvelope"]["properties"]) == {"error"}


# --- 4. 단위 (SPEC 8.2 #4) --------------------------------------------------

def test_every_numeric_field_has_a_declared_unit(doc, schemas):
    """접미사 규약에 걸리거나 예외 목록에 이름이 있어야 한다. 둘 다 아니면 실패다.

    예선의 80만/81만 사고는 단위·반올림이 계약에 없어서 양쪽이 각자 정한 결과였다.
    "적어 두자"는 규율이고, 이 검사가 그것을 구조로 바꾼다.
    """
    declared = doc["x-units"]["unsuffixedNumericFields"]
    undeclared = []
    for name, schema in sorted(schemas.items()):
        for prop, spec in sorted((schema.get("properties") or {}).items()):
            if not _is_numeric(spec):
                continue
            if prop.endswith("KRW") or prop.endswith("Pct"):
                continue
            if f"{name}/{prop}" not in declared:
                undeclared.append(f"{name}/{prop}")
    assert not undeclared, (
        "단위가 선언되지 않은 수치 필드다 (SPEC 8.2 #4). 이름에 KRW/Pct 접미사를 붙이거나 "
        f"main.py 의 X_UNITS['unsuffixedNumericFields'] 에 단위를 적어라: {undeclared}")


def test_the_unit_exception_list_has_no_dead_entries(doc, schemas):
    """목록이 자라기만 하면 규율이 아니라 장식이 된다."""
    dead = []
    for key, unit in doc["x-units"]["unsuffixedNumericFields"].items():
        assert unit, f"{key} 에 단위가 비어 있다"
        schema_name, _, prop = key.partition("/")
        spec = ((schemas.get(schema_name) or {}).get("properties") or {}).get(prop)
        if spec is None or not _is_numeric(spec):
            dead.append(key)
    assert not dead, f"예외 목록에 있는데 계약에는 없거나 수치가 아닌 필드: {dead}"


def test_the_suffix_convention_is_declared(doc):
    suffixes = doc["x-units"]["fieldSuffix"]
    assert set(suffixes) == {"KRW", "Pct"}
    for suffix, spec in suffixes.items():
        assert spec.get("unit") and spec.get("note"), suffix


# --- 5. 반올림 (SPEC 8.2 #4) ------------------------------------------------

def test_rounding_rules_are_in_the_contract(doc):
    rounding = doc["x-rounding"]
    assert rounding["responseValues"]
    assert rounding["engineInternal"]["floorTo"]


def test_display_formatting_names_its_arbiter(doc):
    """SPEC 9.1.1 — 정본이 확정됐으므로 계약이 그 정본을 가리켜야 한다.

    **이 테스트는 원래 반대를 단정했다** (`test_display_formatting_is_marked_unsettled`,
    「미확정」 표기를 요구). 파이썬과 JS 가 다른 문자열을 내던 동안에는 그것이 맞았다.
    **계약 결정 #16 이 정본을 확정하면서 그 단정이 낡았다** — 정본은
    `contracts/format_golden.json` 이고 기준은 언어가 아니라 「정보를 버리지 않는 쪽」이다
    (money 는 half-up·부호 보존, pct 는 고정 소수). 확정된 것을 미확정이라 적으면
    클라이언트가 자기 구현을 맞출 근거를 잃으므로, 단정을 뒤집고 이름도 바꿨다.
    """
    display = doc["x-rounding"]["displayFormatting"]
    assert "미확정" not in display["$status"], "결정 #16 이 정본을 확정했다"
    assert "format_golden.json" in display["$arbiter"]
    assert "half-up" in display["money"]


# --- 6. x-requires-role 표기 자리 (SPEC 6.1 · Part 0-E #1) ------------------

def test_the_role_annotation_slot_exists(doc):
    """인증은 4단계지만 표기 자리는 계약이 먼저 갖는다."""
    slot = doc["x-role-annotations"]
    assert slot["extension"] == "x-requires-role"
    assert slot["appliesTo"]


def test_the_role_vocabulary_matches_the_store(doc):
    """어휘가 두 곳에서 갈리면 4단계에 그대로 사고가 된다."""
    from firsthome.store.models import ROLES

    assert set(doc["x-role-annotations"]["roles"]) == set(ROLES) - {"citizen"}


def test_the_annotated_property_list_matches_reality(doc, schemas):
    """실제로 붙어 있는 `x-requires-role` 과 목록이 일치해야 한다.

    지금은 양쪽 다 비어 있다. 4단계가 필드를 역할 뒤로 옮기면 목록도 같이 바뀌어야
    하고, 안 바뀌면 여기서 잡힌다.
    """
    actual = sorted(
        f"{name}/{prop}"
        for name, schema in schemas.items()
        for prop, spec in (schema.get("properties") or {}).items()
        if "x-requires-role" in spec
    )
    assert actual == sorted(doc["x-role-annotations"]["annotatedProperties"])

    allowed = set(doc["x-role-annotations"]["roles"])
    for name, schema in schemas.items():
        for prop, spec in (schema.get("properties") or {}).items():
            role = spec.get("x-requires-role")
            if role is not None:
                assert role in allowed, f"{name}/{prop}: 알 수 없는 역할 {role!r}"


# --- 7. 경계 조건 (SPEC 8.3) ------------------------------------------------

def test_the_boundary_conditions_are_per_path(doc):
    """8.3 — 경로별 구조. 평면으로 뭉치면 예선 사고가 계약 안에서 다시 가능해진다."""
    boundary = doc["x-boundary-conditions"]
    assert boundary["$rule"], "8.3 #2 규칙이 계약에 없다"
    assert boundary["profiles"], "프로필이 없다"
    for field in ("clientTimeoutMs", "serverResponseBudgetMs", "retries", "onTimeout"):
        assert field not in boundary, (
            f"{field} 가 최상단에 있다 — 평면 구조로 되돌아갔다. 경로별이어야 한다")


@pytest.mark.parametrize("profile", ["analyze", "read", "chat"])
def test_each_profile_declares_a_full_boundary(doc, profile):
    spec = doc["x-boundary-conditions"]["profiles"][profile]
    for field in ("appliesTo", "clientTimeoutMs", "serverResponseBudgetMs",
                  "retries", "onTimeout", "measurement"):
        assert field in spec, f"{profile}: {field} 가 없다"
    assert spec["appliesTo"], f"{profile}: 어느 경로에 걸리는지가 없다"
    assert spec["onTimeout"]["silentFallback"] is False, (
        f"{profile}: 침묵 폴백이 허용되었다 — Part 0-A 에 기록된 실패 그 자체다")


def test_every_applied_path_declares_its_measurement_status(doc):
    """`measured: true` 가 **프로필 전체를 덮는다고 읽히는 것**을 막는다.

    프로필 하나에 경로가 여럿 걸리는데 측정은 그중 일부만 된 상태가 실제로 생긴다 —
    4단계가 인증·관리 경로를 `read` 에 얹으면서 그렇게 됐다. 그때 `measured: true` 만
    남아 있으면 **재 본 적 없는 경로의 타임아웃이 측정에서 유도된 값처럼 읽힌다.**

    SPEC 8.3 #1 은 [타임아웃은 측정에서 유도한다]이고, 8.3.2 는 측정하지 않은 값을
    `measured: false` 로 **기계 판독 가능하게** 표시하는 규약을 이미 세웠다(`chat` 의 75,000ms).
    이 검사는 그 규약을 **경로 단위**로 강제한다. 주석에만 적으면 테스트가 읽지 못한다.

    선언하는 방법은 둘 중 하나다 — `measurement.perPath` 에 측정치를 싣거나,
    `measurement.unmeasuredPaths.paths` 에 [재지 않았다]고 적거나. **비워 두는 것만 안 된다.**

    경로가 **하나뿐인** 프로필은 대상이 아니다. 그때는 measurement 블록 자체가 그 경로의
    측정이라 오해할 여지가 없고, 형식만 강요하면 정직한 계약을 번거롭게 만든다.
    """
    for name, spec in doc["x-boundary-conditions"]["profiles"].items():
        measurement = spec["measurement"]
        if not measurement.get("measured"):
            continue  # 프로필 전체가 미측정이면 이미 정직하다 (chat 이 그렇다)
        if len(spec["appliesTo"]) == 1:
            # 경로가 하나면 measurement 블록 자체가 그 경로의 측정이다 — 모호하지 않다.
            # 여기까지 요구하면 `analyze` 처럼 정직한 프로필에 형식만 강요하게 된다.
            continue
        declared = set(measurement.get("perPath") or {})
        declared |= set((measurement.get("unmeasuredPaths") or {}).get("paths") or [])
        missing = [path for path in spec["appliesTo"] if path not in declared]
        assert not missing, (
            f"{name}: measured=true 인데 측정 상태가 선언되지 않은 경로가 있다 {missing}. "
            "perPath 에 측정치를 싣거나 unmeasuredPaths 에 재지 않았다고 적어라 — "
            "비워 두면 이 경로들의 타임아웃이 측정에서 나온 값처럼 읽힌다")


def test_client_timeout_exceeds_the_server_budget(doc):
    """SPEC 8.3 #2 — 역전되면 정상 응답이 폴백으로 처리된다."""
    for name, spec in doc["x-boundary-conditions"]["profiles"].items():
        budget = spec["serverResponseBudgetMs"]
        if budget is None:
            continue
        assert spec["clientTimeoutMs"] > budget, (
            f"{name}: 클라이언트 타임아웃 {spec['clientTimeoutMs']} <= 서버 예산 {budget}")


def test_the_collapsed_single_budget_does_not_come_back(doc):
    """예선 사고는 **하나의 4500ms 예산**이 chat 호출을 중간에 끊은 것이었다.

    `frontend/app.js` 주석이 그 경위를 직접 적어 두었다. 사고의 본질은 숫자가 아니라
    **성격이 다른 경로를 한 예산으로 뭉친 것**이다. 다시 뭉치는지를 여기서 본다.
    """
    profiles = doc["x-boundary-conditions"]["profiles"]
    timeouts = {name: spec["clientTimeoutMs"] for name, spec in profiles.items()}
    assert timeouts["chat"] > timeouts["analyze"] > timeouts["read"], (
        f"세 경로의 예산이 성격 순서를 잃었다: {timeouts}")
    assert 4500 not in timeouts.values(), (
        f"4500ms 가 계약에 들어왔다. 예선에서 조용한 폴백을 만든 값이다: {timeouts}")


def test_every_boundary_value_carries_its_measurement_evidence(doc):
    """벌거벗은 숫자만 남으면 반년 뒤 아무도 왜 그 값인지 모르고 감으로 고친다."""
    for name, spec in doc["x-boundary-conditions"]["profiles"].items():
        evidence = spec["measurement"]
        assert isinstance(evidence.get("measured"), bool), f"{name}: measured 가 없다"
        if evidence["measured"]:
            for field in ("samples", "p50Ms", "p95Ms", "maxMs", "measuredAt",
                          "environment", "providerMode", "scope", "script", "report"):
                assert evidence.get(field) is not None, f"{name}: 측정 근거에 {field} 가 없다"
            assert (REPO_ROOT / evidence["script"]).is_file(), evidence["script"]
            assert (REPO_ROOT / evidence["report"]).is_file(), evidence["report"]
        else:
            assert evidence.get("$whyNotMeasured"), f"{name}: 측정하지 않은 이유가 없다"
            assert evidence.get("$valueOrigin"), f"{name}: 값의 출처가 없다"


def test_an_unmeasured_timeout_is_machine_readably_marked(doc):
    """SPEC 8.3 #1 은 "타임아웃은 측정에서 유도한다"이다.

    측정하지 않은 값을 측정된 값과 같은 형태로 실으면 그 규칙이 이름만 남는다.
    Part 0-C 의 "(d)를 (a)(b)(c)인 척하지 않는다"와 같은 규율이므로 산문이 아니라
    기계 판독 가능한 표시여야 한다.
    """
    chat = doc["x-boundary-conditions"]["profiles"]["chat"]["measurement"]
    assert chat["measured"] is False
    # 참고용 offline 수치가 측정값 자리로 승격되지 않았는지.
    for field in ("p50Ms", "p95Ms", "p99Ms", "maxMs", "samples"):
        assert field not in chat, f"측정하지 않았다면서 {field} 를 최상위에 실었다"


def test_a_server_budget_is_declared_as_a_promise(doc):
    """예산은 측정값이 아니라 약속이다. 그 간극이 의도된 것임이 계약에 드러나야 한다."""
    for name, spec in doc["x-boundary-conditions"]["profiles"].items():
        if spec["serverResponseBudgetMs"] is None:
            continue
        assert spec.get("budgetIsAPromiseNotAMeasurement") is True, (
            f"{name}: 서버 예산이 측정값처럼 보인다. 약속임을 명시하라")
        assert spec.get("$budgetComment"), f"{name}: 예산 근거가 없다"


# --- 8.3 #4 — 서버와 클라이언트가 같은 파일에서 읽는가 -----------------------

def test_the_frontend_derives_its_timeouts_from_the_dispatch_table(doc):
    """★ 프론트가 경로별 예산을 **다시 쓰지 않고 계약에서 유도하는가** (SPEC 8.3 #3 · #4).

    ── 경위 (완화가 아니라 대상 교체다. 회귀로 오해하지 말 것) ───────────────────
    이 검사의 이전 이름은 `test_the_dispatch_table_mirrors_the_frontend_timeout_branches`
    였고, `frontend/app.js` 본문에서 `path === '/api/chat'` 같은 **분기 집합**을 긁어
    계약의 `clientDispatch.byPath` 키 집합과 같은지 봤다. 그 docstring 은 자기 유효기간을
    스스로 적어 두었다 — *「지금 프론트는 숫자를 자기 파일에 박고 있고, 그것을 생성물로
    바꾸는 것은 D-11(다음 웨이브 · `web` 소유)이다. 다만 계약 구조가 그 생성을 받아낼 수
    있는 형태인지는 지금 확정되어야 한다.」*

    **그 웨이브가 6단계이고, 배선이 붙자 비교할 두 번째 표가 사라졌다.** 프론트는 이제
    계약 결정 #34 의 소비자 스니펫 그대로 `clientDispatch.byPath` 를 직접 조회한다.
    분기를 되살리는 것은 SPEC 8.3 #3(코드에 다시 쓰지 않는다)을 정면으로 어기는 것이므로
    프론트 쪽으로 맞출 수는 없다. 그래서 **검사 대상을 바꾼다** —
    「두 표가 같은가」 → 「**두 번째 표가 되살아나지 않았는가** + 계약이 자기 안에서 정합한가」.

    ── 값 동등성은 이제 어디가 지는가 ──────────────────────────────────────────
    `backend/tests/test_frontend_no_handwritten_constants.py` 의 둘이다 (계약 결정 #36).
      · `test_the_screen_reads_its_timeouts_from_the_contract`
        — node 로 `app.js` 를 올려 **그 파일의 `timeoutFor` 를 실제 호출**해 5종 경로를 대조한다.
      · `test_no_timeout_value_is_written_anywhere_in_the_screen_code`
        — 이 함수의 정규식이 `timeoutFor` 본문만 보므로, 파일 **어디에서든** 타임아웃 값이
          리터럴로 되살아나는 경우를 그쪽이 덮는다.
    SPEC 9.1.1 이 정한 형태 그대로다 — 구현이 아니라 **출력**으로 판정한다.

    이 함수 교체는 코디네이터가 6단계 `web` 에 위임했다 (2026-08-15). 두 변경이 함께
    착지해야만 어느 쪽도 혼자 빨간불이 되지 않기 때문이며, 5단계 `test_boot_smoke.py`
    위임과 같은 모양이다.
    """
    app_js = (REPO_ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    body = app_js[app_js.index("function timeoutFor("):]
    body = body[:body.index("\n  }")]
    branch_paths = set(re.findall(r"path === '([^']+)'", body))

    assert not branch_paths, (
        f"`app.js` 의 timeoutFor 에 경로 분기가 되살아났다: {sorted(branch_paths)} — "
        "계약의 clientDispatch 를 프론트가 다시 적은 것이다 (SPEC 8.3 #3).")
    assert "clientDispatch" in body, (
        "timeoutFor 가 계약의 clientDispatch 를 조회하지 않는다. 값을 어디서 얻는지 확인하라.")

    dispatch = doc["x-boundary-conditions"]["clientDispatch"]
    profiles = doc["x-boundary-conditions"]["profiles"]
    assert dispatch["default"] in profiles, "기본 프로필이 정의되지 않았다"
    for path, profile in dispatch["byPath"].items():
        assert profile in profiles, f"{path} 가 없는 프로필 {profile} 을 가리킨다"
        assert path in profiles[profile]["appliesTo"], f"{path} 가 {profile}.appliesTo 에 없다"


def test_every_contracted_path_resolves_to_exactly_one_profile(doc):
    """계약에 있는 경로가 어느 프로필에도 안 걸리거나 둘에 걸리면 클라이언트가 갈린다."""
    boundary = doc["x-boundary-conditions"]
    profiles = boundary["profiles"]
    for path in doc["paths"]:
        name = boundary["clientDispatch"]["byPath"].get(path, boundary["clientDispatch"]["default"])
        owners = [key for key, spec in profiles.items() if path in spec["appliesTo"]]
        assert owners == [name], f"{path}: 프로필 배정이 어긋난다 (dispatch={name}, appliesTo={owners})"


# --- 8. 직렬화 (D-12) -------------------------------------------------------

def test_the_declared_serialization_actually_reproduces_the_file(doc):
    """`x-serialization` 이 장식이 아니라 서술인지 본다.

    적힌 규칙 그대로 직렬화했을 때 커밋본이 나와야 한다. 생성기를 바꾸면서 이 표를
    갱신하지 않으면 여기서 잡힌다.
    """
    rules = doc["x-serialization"]
    rendered = json.dumps(
        doc,
        ensure_ascii=rules["ensureAscii"],
        indent=rules["indent"],
        sort_keys=rules["sortKeys"],
    ) + "\n"
    assert rendered.encode("utf-8") == OPENAPI.read_bytes()


def test_the_generator_command_is_documented(doc):
    command = doc["x-serialization"]["command"]
    script = REPO_ROOT / command.split()[-1]
    assert script.is_file(), f"계약이 가리키는 생성 명령이 없다: {command}"
