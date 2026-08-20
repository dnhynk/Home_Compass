"""D-13 — 판정 응답의 계보 (`provenance`) 와 데이터 등급 (`dataGrade`).

SPEC 8.1 이 「응답에 `dataGrade` · `provenance` 추가」라고 적었고 SPEC 2.4 · D-13 이 그
모양을 확정했는데, Part 10 의 어느 단계도 그 구현을 맡지 않았다 (계약 결정 #37).
**이 파일이 그 누락을 먼저 실패로 고정한다** (SPEC 9.3 #1).

`TestClient` 로 HTTP 를 치는 이유는 `test_auth.py` 와 같다 — 계보가 응답에 실제로 실리는지는
API 계층에서만 증명된다. 함수를 직접 부르면 조립 경로를 우회한다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from firsthome.main import app

REPO_ROOT = Path(__file__).resolve().parents[3]

PROFILE = {
    "age": 28,
    "annualIncomeKRW": 42_000_000,
    "monthlyNetIncomeKRW": 3_000_000,
    "liquidAssetsKRW": 40_000_000,
    "existingDebtMonthlyKRW": 300_000,
    "householdSize": 1,
    "regionCode": "11440",
    "preferredType": "any",
}


@pytest.fixture(scope="module")
def response() -> dict:
    """익명 판정 1회. 계보는 역할과 무관하게 실린다 (D-13 — 최상단 필드다)."""
    with TestClient(app) as client:
        result = client.post("/api/analyze", json=PROFILE)
    assert result.status_code == 200, result.text
    return result.json()


def _provenance_schema() -> dict:
    return json.loads((REPO_ROOT / "contracts" / "provenance.schema.json").read_text(encoding="utf-8"))


def _resolve_pointer(document, pointer: str):
    """RFC 6901. 가리키는 곳이 없으면 `KeyError`/`IndexError` 로 터진다."""
    if pointer == "":
        return document
    assert pointer.startswith("/"), pointer
    node = document
    for raw in pointer[1:].split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        node = node[int(token)] if isinstance(node, list) else node[token]
    return node


# --------------------------------------------------------------------------
# A. `provenance` — 최상단 배열, 사실 단위 (D-13)
# --------------------------------------------------------------------------

def test_the_response_carries_a_top_level_provenance_array(response):
    assert "provenance" in response, (
        "판정 응답에 `provenance` 가 없다 (SPEC 8.1 · D-13). "
        f"최상단 키: {sorted(response)}"
    )
    assert isinstance(response["provenance"], list)
    assert response["provenance"], "계보가 0건이면 판정이 아무 사실도 안 썼다는 뜻이다"


def test_every_provenance_item_validates_against_the_contract_schema(response):
    """항목의 `provenance` 는 `contracts/provenance.schema.json` 그 모양이다 (SPEC 2.1)."""
    validator = Draft202012Validator(_provenance_schema())
    for index, item in enumerate(response["provenance"]):
        errors = sorted(validator.iter_errors(item["provenance"]), key=str)
        assert not errors, f"provenance[{index}] 이 계약을 위반한다: {[e.message for e in errors]}"


def test_data_and_model_constants_share_one_array_separated_by_source_kind(response):
    """D-13 — 데이터(D-5)와 모델 상수(Part 0-C)가 **같은 배열**에 들어간다."""
    kinds = {item["factKind"] for item in response["provenance"]}
    assert {"region_field", "model_constant"} <= kinds, kinds
    source_kinds = {item["provenance"]["source_kind"] for item in response["provenance"]}
    assert "normative" in source_kinds, "모델 상수의 (d) 가 배열에 없다"
    assert source_kinds & {"market", "statute", "statistic"}, "데이터 쪽 사실이 배열에 없다"


def test_every_target_is_a_pointer_that_resolves_in_this_response(response):
    """`targets` 는 RFC 6901 이며 **이 응답의 실제 위치**를 가리킨다 (SPEC 2.1)."""
    for index, item in enumerate(response["provenance"]):
        assert item["targets"], f"provenance[{index}] 이 아무 곳도 가리키지 않는다"
        for pointer in item["targets"]:
            try:
                _resolve_pointer(response, pointer)
            except (KeyError, IndexError, ValueError) as exc:
                pytest.fail(f"provenance[{index}].targets 의 {pointer!r} 가 응답에 없다: {exc!r}")


def test_the_screen_facing_source_fields_still_coexist(response):
    """D-13 — `policies[].source` · `meta.disclaimer` 는 **병존**한다. 지우지 않는다."""
    assert all("source" in policy for policy in response["policies"])
    assert response["meta"]["disclaimer"]


# --------------------------------------------------------------------------
# B. `dataGrade` — 등급값 + 사유 목록 (SPEC 2.4)
# --------------------------------------------------------------------------

def test_the_response_carries_a_top_level_data_grade(response):
    assert "dataGrade" in response, (
        "판정 응답에 `dataGrade` 가 없다 (SPEC 8.1 · 2.4). "
        f"최상단 키: {sorted(response)}"
    )
    assert set(response["dataGrade"]) >= {"grade", "reasons"}


def test_our_choice_is_carried_but_never_graded(response):
    """Part 0-E #3 — 규범적 선택은 `provenance` 에 **반드시** 실리고 등급에서는 빠진다."""
    our_choice = [i for i, item in enumerate(response["provenance"])
                  if item["provenance"]["verification"] == "our_choice"]
    assert our_choice, "our_choice 사실이 계보에서 통째로 빠졌다"
    graded = {reason["provenanceIndex"] for reason in response["dataGrade"]["reasons"]}
    assert not (graded & set(our_choice)), (
        "규범적 선택이 등급 사유에 실렸다 — 신선도 개념이 없는 사실이 등급을 움직인다")


def test_each_fact_caused_reason_points_at_its_provenance_item(response):
    """SPEC 2.4 — 사유는 원인 유형을 구분해 담고 각 사유가 계보 항목을 가리킨다.

    `freshness_not_evaluated` 만 예외다 — 그것은 특정 사실의 결함이 아니라 판정 자체가
    서지 않은 상태이며, 그래서 `provenanceIndex` 가 `null` 이다.
    """
    for reason in response["dataGrade"]["reasons"]:
        assert reason["type"] in (
            "unverified", "stale", "pending_review", "freshness_not_evaluated"), reason
        if reason["type"] == "freshness_not_evaluated":
            assert reason["provenanceIndex"] is None
            continue
        item = response["provenance"][reason["provenanceIndex"]]
        assert reason["fact"] == item["fact"]
        if reason["type"] != "pending_review":
            assert item["provenance"]["verification"] == reason["type"]


def test_the_worst_grade_wins(response):
    """SPEC 2.4 — `C` > `B` > `A`."""
    types = {reason["type"] for reason in response["dataGrade"]["reasons"]}
    if "unverified" in types:
        assert response["dataGrade"]["grade"] == "C"
    elif types & {"stale", "pending_review"}:
        assert response["dataGrade"]["grade"] == "B"


def test_the_seeded_store_grades_c_and_the_other_branches_are_unreachable_today(response):
    """지금 도달 가능한 등급은 `C` 하나다. **그 사실을 적어 둔다.**

    시드의 지역 8필드와 상수 4건이 `unverified` 이므로 어떤 프로필로도 `C` 가 나온다.
    `B`(`stale` · `pending_review`)와 `null` 분기는 **구조만 있고 지금은 도달 불가**다 —
    승인 대기 큐는 5단계 산출물이고 신선도 임계는 아직 없다. 도달 불가를 초록으로
    덮지 않으려고 여기 명시한다.
    """
    assert response["dataGrade"]["grade"] == "C"
    types = {reason["type"] for reason in response["dataGrade"]["reasons"]}
    assert "unverified" in types
    assert "stale" not in types and "pending_review" not in types


# --------------------------------------------------------------------------
# C. `stale` 은 판정하지 않는다 — 그리고 그 사실이 응답에 드러난다
# --------------------------------------------------------------------------

def test_the_response_says_out_loud_that_freshness_was_not_evaluated(response):
    """SPEC 2.4 「신선도 임계는 미정이다」를 **기계 판독 가능하게** 드러낸다.

    없는 판정을 [해당 없음] 으로 조용히 처리하면 화면은 그것을 「신선하다」로 읽는다.
    그것이 이 저장소가 반복해서 막아 온 침묵 폴백이다.
    """
    reasons = [r for r in response["dataGrade"]["reasons"]
               if r["type"] == "freshness_not_evaluated"]
    assert len(reasons) == 1, "신선도 미판정 표기가 없거나 중복이다"
    assert reasons[0]["message"], "유형만 있고 사람이 읽을 문장이 없다"


def test_not_evaluating_freshness_can_never_produce_an_optimistic_grade():
    """★ 판정하지 않은 것이 `A` 의 근거가 되면 안 된다.

    사실이 **전부 `verified`** 인 가상 입력으로 산정기를 직접 부른다. 실기동에서는 시드가
    `unverified` 를 갖고 있어 이 분기를 지나갈 수 없고, 지나가지 않는 분기는 조용히 틀린다.
    """
    from firsthome.main import grade_facts

    clean = [{
        "fact": "가상 사실",
        "factKind": "model_constant",
        "provenance": {"source_kind": "statute", "source_name": "x", "source_ref": "y",
                       "observed_at": "2026-01-01T00:00:00+09:00", "fetched_at": None,
                       "verification": "verified"},
        "targets": ["/affordability"],
    }]
    graded = grade_facts(clean, {"affordability.buffer_ratio": 0.1})
    assert graded["grade"] is None, (
        "신선도를 판정하지 않았는데 등급이 나왔다 — "
        "SPEC 2.4 의 A 는 「전부 verified 이며 신선도 기준 이내」라는 두 조건의 곱이다")
    assert any(r["type"] == "freshness_not_evaluated" for r in graded["reasons"]), (
        "사유 없는 null 은 소비자에게 「깨끗함」으로 읽힌다")


def test_the_marker_turns_itself_off_when_a_threshold_is_registered():
    """임계가 등재되면 표기가 **자동으로** 꺼진다 — 어딘가의 리터럴을 사람이 지우지 않는다."""
    from firsthome.main import grade_facts

    clean = [{
        "fact": "가상 사실",
        "factKind": "model_constant",
        "provenance": {"source_kind": "statute", "source_name": "x", "source_ref": "y",
                       "observed_at": "2026-01-01T00:00:00+09:00", "fetched_at": None,
                       "verification": "verified"},
        "targets": ["/affordability"],
    }]
    graded = grade_facts(clean, {"data.freshness_threshold_days": 30})
    assert not any(r["type"] == "freshness_not_evaluated" for r in graded["reasons"])
    assert graded["grade"] == "A"


def test_no_freshness_threshold_constant_is_registered_yet():
    """★ 파수병 — 임계가 등재되는 날 이 테스트가 깨진다. **그때 할 일은 표기 삭제가 아니다.**

    표기만 걷고 `stale` 판정을 넣지 않으면 등급은 조용히 낙관적이 된다 (임계가 생겼으므로
    위 표기가 자동으로 꺼지고, 판정이 없으므로 `stale` 사유는 하나도 나오지 않는다).
    그 전환을 사람이 눈치채지 못한 채 지나가지 않게 여기서 붙든다.

    깨졌다면 순서는 이렇다 — ① SPEC 2.4 의 `stale` 판정을 구현하고
    ② `frontend/local_engine.js` 의 같은 자리도 함께 고치고 (두 산정이 갈라지면 안 된다)
    ③ 그 다음에 이 테스트를 걷는다.
    """
    from firsthome.main import MODEL_CONSTANTS, freshness_threshold_keys

    assert freshness_threshold_keys(MODEL_CONSTANTS) == [], (
        "신선도 임계로 보이는 상수가 등재됐다. 미판정 표기가 자동으로 꺼졌을 것이다 — "
        "stale 판정을 구현하지 않았다면 지금 등급은 낙관적이다 (SPEC 2.4).")
