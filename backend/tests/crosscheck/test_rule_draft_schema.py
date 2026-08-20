"""교차 테스트 — `RuleDraft` 스키마 (코디네이터 소유, SPEC 9.4).

SPEC 4.2.3 이 요구한 것은 둘이다.

  1. **판정에 실제로 쓰이는 필드만** 정의한다.
     일반적 규칙 표현 언어를 새로 만들지 않는다 — 쓰지 않는 표현력은
     **검증 불가능한 표면**만 늘린다.
  2. `additionalProperties: false`.

그리고 SPEC 4.2 의 **추정 금지**가 이 스키마에 걸린다:

    원문에 없는 값은 `null` + `not_found` 로 표기한다. 그럴듯한 값을 채워 넣는 것이
    이 단계의 지배적 실패 양상이므로 **프롬프트와 스키마 양쪽에서** 강제한다.

이 파일은 그 강제가 실제로 작동하는지를 **음성 케이스로** 붙든다. 스키마가 통과시켜서는
안 되는 것을 통과시키면, 4.2 의 방어는 프롬프트 한 줄로만 남는다.

**필드 집합이 코드와 어긋나지 않는지도 여기서 본다.** 스키마가 엔진이 안 읽는 필드를
정의하면 1번 요구가 깨지고, 엔진이 읽는 필드를 빠뜨리면 추출 결과가 판정에 못 쓰인다.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

REPO = Path(__file__).resolve().parents[3]
SCHEMA_PATH = REPO / "contracts" / "rule_draft.schema.json"
ELIGIBILITY = REPO / "backend" / "src" / "firsthome" / "engines" / "eligibility.py"


@pytest.fixture(scope="module")
def schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def validator(schema: dict) -> Draft202012Validator:
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


@pytest.fixture(scope="module")
def valid(schema: dict) -> dict:
    return json.loads(json.dumps(schema["examples"][0]))


def test_schema_accepts_its_own_example(validator, valid):
    assert not list(validator.iter_errors(valid))


def test_no_additional_properties_anywhere(schema):
    """SPEC 4.2.3. 어느 층에서든 열려 있으면 LLM 이 발명한 필드가 새어든다."""
    assert schema["additionalProperties"] is False
    assert schema["properties"]["criteria"]["additionalProperties"] is False


# --- 필드 집합이 코드와 맞는가 ---------------------------------------------

def test_criteria_matches_exactly_what_the_engine_reads(schema):
    """스키마의 criteria 가 eligibility.py 가 읽는 키와 **정확히** 일치해야 한다.

    많으면 SPEC 4.2.3 의 「쓰이는 필드만」이 깨지고, 적으면 추출 결과가 판정에 못 쓰인다.
    """
    source = ELIGIBILITY.read_text(encoding="utf-8")
    read_by_engine = set(re.findall(r'crit\.get\("([A-Za-z]+)"', source))
    declared = set(schema["properties"]["criteria"]["properties"])

    assert declared == read_by_engine, (
        f"스키마에만 있음: {sorted(declared - read_by_engine)} / "
        f"엔진만 읽음: {sorted(read_by_engine - declared)}")


def test_required_covers_every_declared_property(schema):
    """선택 필드를 두면 LLM 이 어려운 필드를 조용히 생략한다.

    전부 required 로 두고, 원문에 없는 것은 null + not_found 로 **명시**하게 한다.
    그래야 [못 찾았다] 와 [빠뜨렸다] 가 구분된다.
    """
    assert set(schema["required"]) == set(schema["properties"])
    crit = schema["properties"]["criteria"]
    assert set(crit["required"]) == set(crit["properties"])


# --- 추정 금지가 실제로 막히는가 (음성) ------------------------------------

def test_unknown_top_level_field_is_rejected(validator, valid):
    assert list(validator.iter_errors({**valid, "확신도": "높음"}))


def test_unknown_criteria_field_is_rejected(validator, valid):
    bad = json.loads(json.dumps(valid))
    bad["criteria"]["창의적새필드"] = 1
    assert list(validator.iter_errors(bad)), "LLM 이 발명한 criteria 가 통과했다"


def test_a_missing_required_field_is_rejected(validator, valid):
    bad = json.loads(json.dumps(valid))
    del bad["not_found"]
    assert list(validator.iter_errors(bad)), "not_found 없이 통과했다 — 추정 금지가 무력해진다"


def test_not_found_only_takes_json_pointers_into_this_document(validator, valid):
    for bogus in ("criteria/ageMin", "/criteria/없는필드/더깊이", "/제멋대로", "ageMin"):
        bad = {**valid, "not_found": [bogus]}
        assert list(validator.iter_errors(bad)), f"{bogus!r} 가 통과했다"


def test_not_found_rejects_duplicates(validator, valid):
    bad = {**valid, "not_found": ["/criteria/assetMaxKRW", "/criteria/assetMaxKRW"]}
    assert list(validator.iter_errors(bad))


@pytest.mark.parametrize(
    "path, value, why",
    [
        (("criteria", "ageMin"), -1, "음수 연령"),
        (("criteria", "ageMin"), "만 19세", "문자열로 적은 연령 — 원문 인용을 값 자리에 넣은 것"),
        (("criteria", "annualIncomeMaxKRW"), -1, "음수 소득 상한"),
        (("criteria", "requireHomeless"), "예", "불리언 자리의 문자열"),
        (("criteria", "regionPrefixes"), ["서울"], "법정동코드가 아닌 지역명"),
        (("maxAmountKRW",), -1, "음수 한도"),
        (("rateRangePct",), [1.5], "구간인데 값이 하나"),
        (("rateRangePct",), [1.5, 2.9, 3.1], "구간인데 값이 셋"),
        (("rateRangePct",), 2.9, "구간 자리의 스칼라"),
        (("conditionalChecks",), "기금 소진 시 마감", "배열 자리의 문자열"),
        (("conditionalChecks",), [""], "빈 문자열 항목"),
        (("policy_id",), "", "빈 policy_id"),
    ],
)
def test_shape_violations_are_rejected(validator, valid, path, value, why):
    bad = json.loads(json.dumps(valid))
    target = bad
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    assert list(validator.iter_errors(bad)), f"막았어야 한다: {why}"


# --- 「상한 없음」을 파수병으로 적지 않는가 --------------------------------

def test_no_sentinel_values_survive_the_schema(validator, valid):
    """`ageMax` 200 · 금액 10억 같은 파수병은 「상한 없음」의 표현이 아니다.

    현행 policies.json 이 그렇게 적고 있고 1-③ 에서 제거 대상이다 (레지스트리
    `slated_for_removal`). 새로 추출되는 규칙에까지 그 표현이 흘러들면 결함이 복제된다.
    「상한 없음」은 `null` 이다.
    """
    bad = json.loads(json.dumps(valid))
    bad["criteria"]["ageMax"] = 200
    assert list(validator.iter_errors(bad)), (
        "ageMax=200 파수병이 통과했다. 「상한 없음」은 null 로 적어야 한다")


def test_null_is_how_absence_is_expressed(validator, valid):
    """모든 값 필드가 null 을 받아야 한다 — 그것이 not_found 와 짝을 이루는 표현이다."""
    for field in ("maxAmountKRW", "rateRangePct"):
        assert not list(validator.iter_errors({**valid, field: None})), field
    for field in schema_criteria_fields(valid):
        bad = json.loads(json.dumps(valid))
        bad["criteria"][field] = None
        assert not list(validator.iter_errors(bad)), field


def schema_criteria_fields(valid: dict) -> list[str]:
    return sorted(valid["criteria"])
