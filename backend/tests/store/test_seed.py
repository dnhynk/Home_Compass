"""시드 — 계약과 기존 시드 데이터를 저장소로 옮긴다.

두 가지가 걸려 있다.
  - `contracts/model_constants.json` 의 `seedRule` 을 **그대로** 따른다.
    (d)는 `our_choice`, (a)(b)(c)는 `unverified`. `pending_diligence` 의 준거 후보를
    `seed_provenance` 로 옮겨 적지 않는다 — 실사 승인 전 인용은 Part 0-C 위반이다.
  - `data/*.json` 이관 후에도 **판정 숫자가 바뀌지 않는다** (SPEC 10.2 1-①).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from conftest import T0

from firsthome.store.models import REGION_FACT_FIELDS
from firsthome.store.seed import (
    SEED_DATA_DIR,
    seed_all,
    seed_model_constants,
    seed_policies,
    seed_regions,
)

REPO = Path(__file__).resolve().parents[3]
REGISTRY = json.loads((REPO / "contracts" / "model_constants.json").read_text(encoding="utf-8"))
DATA = REPO / "backend" / "src" / "firsthome" / "data"
#: 굳힌 시드의 한 항목은 `payload`(엔진 입력) + `provenance`(레코드 요약) +
#: `fieldProvenance`(사실 단위) 셋이다 — 계약 결정 #40 이 계보를 필드별로 갈랐고,
#: 값과 계보를 파일 안에서 떼어 놓으면 그 둘이 조용히 어긋난다. 생성물
#: `frontend/generated/regions.js` 와 같은 모양이다 (결정 #34).
REGIONS_JSON = json.loads((DATA / "regions.json").read_text(encoding="utf-8"))["regions"]
REGION_PAYLOADS = [entry["payload"] for entry in REGIONS_JSON]
POLICIES_JSON = json.loads((DATA / "policies.json").read_text(encoding="utf-8"))["policies"]


# --------------------------------------------------------------------------
# ModelConstant
# --------------------------------------------------------------------------


def test_every_registry_entry_is_seeded(store):
    seed_model_constants(store)
    assert {c.key for c in store.model_constants.list()} == {e["key"] for e in REGISTRY["entries"]}


def test_seeded_values_are_the_frozen_current_values(store):
    """1-① 이 '판정 숫자를 바꾸지 않는 구조 변경'임을 기계적으로 붙드는 지점이다."""
    seed_model_constants(store)
    mapping = store.model_constants.as_mapping()

    for entry in REGISTRY["entries"]:
        expected = entry["frozen_current_value"]
        if entry["value_type"] == "krw_by_household":
            expected = {int(k): v for k, v in expected.items()}
        elif entry["value_type"] == "policy_id_order":
            expected = tuple(expected)
        assert mapping[entry["key"]] == expected, entry["key"]


def test_household_mapping_keys_are_ints_not_json_strings(store):
    """`LIVING_COST_BY_HOUSEHOLD[size]` 는 int 로 조회한다. 문자열 키면 KeyError 다.

    **불변식은 키의 타입이지 값이 아니다.** 값을 하드코딩하면 1-② 처럼 값이 갱신될 때마다
    무관한 이유로 빨간불이 나고, 그러면 진짜 불변식(int 키)이 가려진다. 값은 계약에서 읽는다.
    """
    seed_model_constants(store)
    value = store.model_constants.as_mapping()["affordability.living_cost_by_household"]

    entry = next(
        e for e in REGISTRY["entries"] if e["key"] == "affordability.living_cost_by_household"
    )
    assert value == {int(k): v for k, v in entry["frozen_current_value"].items()}
    assert all(isinstance(k, int) for k in value)


def test_normative_entries_are_seeded_as_our_choice(store):
    seed_model_constants(store)
    for entry in REGISTRY["entries"]:
        if entry["spec_class"] == "d":
            stored = store.model_constants.get(entry["key"])
            assert stored.provenance.verification == "our_choice", entry["key"]
            assert stored.provenance.source_kind == "normative", entry["key"]


# --------------------------------------------------------------------------
# 아직 unverified 인 (a)(b)(c) 상수 — **자기소거 목록**
#
# D-14 의 「1-① 은 (a)(b)(c) 전수를 unverified 로 등재」 국면은 끝났다
# (1-②, registryVersion 1.3.0 이 시장금리 4종과 생활비를 verified 로 올렸다).
# 그래서 고정 집합 단정을 버리고 목록을 둔다. 목록은 **양방향으로 조인다**:
#
#   · 목록에 없는 키가 unverified 다      -> 등재를 빠뜨렸다
#   · 목록에 있는 키가 verified 가 됐다   -> 실사가 끝났다. 목록에서 지워라  ★ 핵심
#
# 둘째 방향이 이 장치의 전부다. 없으면 실사가 끝나도 아무도 목록을 줄이지 않는다.
# **목록이 줄지 않는 것이 곧 실사가 멈춰 있다는 신호다** — SPEC 5.1.2 의 허용목록,
# crosscheck 의 PENDING_EXTERNALIZATION 과 같은 규율이다.
#
# 각 줄에 왜 아직인지 적는다. 근거 없는 유예는 유예가 아니다.
STILL_UNVERIFIED = {
    "affordability.net_income_from_annual":
        "근로소득 간이세액표 미확인. 4대보험 요율 4종은 원문확인됐으나 국세청이 간이세액표의 "
        "개정일·적용시점을 밝히지 않는다. **부분 산식을 만들지 않는다** — 4대보험만 공제하고 "
        "소득세를 빼먹으면 실수령액이 과대계산되고 그대로 지불능력 과대로 이어진다.",
    "affordability.living_cost_extra_per_person":
        "가구원수별 증분이 공표되지 않는다. 최대 구간이 「5인이상」 개방구간(평균 5.12명) "
        "하나뿐이라 인접 구간 뺄셈은 인용이 아니라 외삽이다 (FINDINGS-3.md).",
    "tco.jeonse_ltv":
        "승격 대상이 아니라 **삭제 대상**이다. 상품마다 다른 값이라 전역 상수 자체가 부적절하고, "
        "정책 데이터 필드로 옮긴 뒤 필드가 없는 정책은 판정에서 제외한다 (slated_for_removal).",
    "risk.metro_sido_code_prefixes":
        "「수도권 = 서울·인천·경기」의 1차 출처(수도권정비계획법 제2조 및 같은 법 시행령)를 "
        "원문으로 확인하지 못했다. HUG 가입요건 상한(수도권 7억 / 그 외 5억)이 이 분류로 갈리므로 "
        "정의가 곧 어느 상한을 쓰는지를 정한다. 1-③ F-4.",
}


def test_the_unverified_list_shrinks_as_diligence_lands(store):
    """아직 unverified 인 (a)(b)(c) 가 목록과 정확히 일치한다 (양방향).

    SPEC 10.2 의 1-② 완료 기준은 「(a)(b)(c) 상수의 verification 이 verified 이고
    observed_at 이 있다」이다. **1-② 는 그 기준을 완전히 충족하지 못한 채 닫힌다** —
    위 목록이 그 미충족분이고, 각 줄이 왜 못 채웠는지를 적고 있다. 목록이 비면 충족이다.
    """
    seed_model_constants(store)

    for key, reason in STILL_UNVERIFIED.items():
        assert isinstance(reason, str) and len(reason.strip()) >= 20, f"근거 없는 유예: {key}"

    observed = {
        entry["key"]
        for entry in REGISTRY["entries"]
        if entry["spec_class"] in ("a", "b", "c")
        and store.model_constants.get(entry["key"]).provenance.verification == "unverified"
    }
    listed = set(STILL_UNVERIFIED)

    assert not observed - listed, (
        "unverified 인데 목록에 없다 — 등재를 빠뜨렸거나 승격이 되돌아갔다: "
        f"{sorted(observed - listed)}"
    )
    assert not listed - observed, (
        "목록에 있는데 더 이상 unverified 가 아니다. 실사가 끝났다는 뜻이니 "
        f"STILL_UNVERIFIED 에서 지워라: {sorted(listed - observed)}"
    )


def test_no_pending_diligence_candidate_leaks_into_provenance(store):
    """실사 승인 전의 준거 후보를 계보에 적으면 심사에서 즉시 반박당한다 (Part 0-C)."""
    seed_model_constants(store)
    for entry in REGISTRY["entries"]:
        if "pending_diligence" not in entry:
            continue
        provenance = store.model_constants.get(entry["key"]).provenance
        assert provenance.source_name is None, entry["key"]
        assert provenance.source_ref is None, entry["key"]
        assert provenance.observed_at is None, entry["key"]


def test_seeded_provenance_is_byte_identical_to_the_contract(store):
    """계약이 적어둔 seed_provenance 를 저장소가 손대지 않았음을 통째로 비교한다."""
    seed_model_constants(store)
    for entry in REGISTRY["entries"]:
        stored = store.model_constants.get(entry["key"]).provenance
        assert stored.to_dict() == entry["seed_provenance"], entry["key"]


def test_registry_metadata_is_carried_over(store):
    seed_model_constants(store)
    for entry in REGISTRY["entries"]:
        stored = store.model_constants.get(entry["key"])
        assert stored.engine == entry["engine"]
        assert stored.legacy_symbol == entry["legacy_symbol"]
        assert stored.spec_class == entry["spec_class"]
        assert stored.value_type == entry["value_type"]


# --------------------------------------------------------------------------
# Region — 이관 후에도 판정 입력이 같아야 한다
# --------------------------------------------------------------------------


def test_every_region_is_seeded_in_file_order(store):
    seed_regions(store)
    assert [r.code for r in store.regions.list()] == [p["code"] for p in REGION_PAYLOADS]


def test_seeded_regions_reproduce_the_engine_input_exactly(store):
    """판정에 들어가는 dict 가 파일과 한 글자라도 다르면 숫자가 움직인다."""
    seed_regions(store)
    for stored, original in zip(store.regions.list(), REGION_PAYLOADS):
        assert stored.to_engine_dict() == original, original["code"]


# --------------------------------------------------------------------------
# 굳힌 시드의 계보 (계약 결정 #40 — 8단계가 집행했다)
# --------------------------------------------------------------------------
#
# 이 절이 붙들고 있는 것은 하나다: **8필드가 한 덩어리가 아니다.**
# 결정 #40 이 시드를 실수집으로 굳히면서 계보가 필드별로 갈렸고, 그 구분이 사라지면
# 실측값과 예시값이 같은 얼굴로 화면에 나간다 — SPEC 3.1 이 금지한 바로 그것이다.

#: 실거래가 원자료에 **대응물이 없는** 셋 (SPEC 3.1). 굳혀도 예시값 그대로다.
NO_COUNTERPART_FIELDS = ("maintenanceFeeKRW", "marketRisk", "guaranteeAvailable")

#: 실거래가에서 도출돼 실측으로 채워진 다섯.
MEASURED_FIELDS = tuple(f for f in REGION_FACT_FIELDS if f not in NO_COUNTERPART_FIELDS)


def test_measured_fields_are_verified_and_carry_both_timestamps(store):
    """실측 5필드는 `verified` 이고 관측 기준시점·취득 시각을 **둘 다** 갖는다."""
    seed_regions(store)
    for region in store.regions.list():
        for name in MEASURED_FIELDS:
            provenance = region.provenance_for(name)
            assert provenance.verification == "verified", f"{region.code} {name}"
            assert provenance.observed_at, f"{region.code} {name} 관측 기준시점 없음"
            assert provenance.fetched_at, f"{region.code} {name} 취득 시각 없음"
            assert "국토교통부" in (provenance.source_name or ""), f"{region.code} {name}"


def test_the_three_fields_without_a_counterpart_stay_unverified(store):
    """SPEC 3.1 — 출처가 특정되지 않은 필드는 `unverified` 다.

    ★ 굳히기가 가장 틀리기 쉬운 자리다. 실수집 결과를 넣으면서 이 셋에까지 국토부 이름을
    붙이면 예시값이 실데이터인 척하게 된다. **값이 실측으로 바뀐 것은 다섯뿐이다.**
    """
    seed_regions(store)
    for region in store.regions.list():
        for name in NO_COUNTERPART_FIELDS:
            provenance = region.provenance_for(name)
            assert provenance.verification == "unverified", f"{region.code} {name}"
            assert "국토교통부" not in (provenance.source_name or ""), f"{region.code} {name}"
            assert provenance.observed_at is None, f"{region.code} {name}"


def test_the_record_summary_stays_unverified_so_the_grade_stays_c(store):
    """결정 #40 의 「바뀌지 않는 것」 — 3필드가 남아 있으므로 등급은 여전히 `C` 다.

    요약이 `verified` 로 올라가면 `dataGrade` 가 좋아지고, 그것은 **굳히기가 등급을
    사들인 것**이 된다. 최악값 규칙(SPEC 2.4)은 저장소가 강제하지만, 그 규칙이 걸리는지는
    굳힌 파일이 실제로 섞여 있을 때만 뜻이 있으므로 여기서 값으로 확인한다.
    """
    seed_regions(store)
    for region in store.regions.list():
        assert region.provenance.verification == "unverified", region.code


def test_the_frozen_fetched_at_is_the_real_collection_time_not_the_demo_day(store):
    """결정 #40 — `fetched_at` 을 시연일로 위조하지 않는다.

    위조를 직접 잡을 수는 없다(우리는 진짜 시각을 모른다). 잡을 수 있는 것은 **한 배치의
    산출물이라는 사실**이다 — 실수집 한 번은 시계를 한 번만 읽으므로(`ingest.market` 의
    규율) 전 지역·전 실측필드의 `fetched_at` 이 한 값이어야 한다. 시연 때마다 "지금"으로
    다시 적으면 이 단정이 깨지지는 않지만, 그때는 `observed_at` 과의 간격이 사라진다 —
    그래서 둘째 단정을 함께 둔다.
    """
    seed_regions(store)
    stamps = {
        region.provenance_for(name).fetched_at
        for region in store.regions.list()
        for name in MEASURED_FIELDS
    }
    assert len(stamps) == 1, f"한 배치의 산출물이 아니다: {sorted(stamps)}"

    for region in store.regions.list():
        for name in MEASURED_FIELDS:
            provenance = region.provenance_for(name)
            observed = datetime.fromisoformat(provenance.observed_at)
            fetched = datetime.fromisoformat(provenance.fetched_at)
            assert observed < fetched, (
                f"{region.code} {name} — 관측 기준시점이 취득 시각보다 뒤다"
            )


# --------------------------------------------------------------------------
# Policy -> RuleVersion (계약 결정 #5 · #6)
# --------------------------------------------------------------------------


def test_every_policy_is_seeded_as_an_approved_rule_version(store):
    seed_policies(store, at=T0)
    versions = store.rule_versions.list()

    assert [v.policy_id for v in versions] == [p["id"] for p in POLICIES_JSON]
    assert all(v.status == "approved" for v in versions)


def test_seeded_rule_versions_reproduce_the_policy_payload_exactly(store):
    seed_policies(store, at=T0)
    for stored, original in zip(store.rule_versions.list(), POLICIES_JSON):
        assert stored.payload == original, original["id"]


def test_seeded_rule_versions_are_marked_as_seed_not_human_approval(store):
    """계약 결정 #5 — 가짜 승인자를 넣지 않는다."""
    seed_policies(store, at=T0)
    for version in store.rule_versions.list():
        assert version.origin == "seed"
        assert version.approved_by is None
        assert store.approvals.list_for(version.id) == []


def test_seeded_rule_versions_have_no_invented_effective_dates(store):
    """계약 결정 #6 — DB 를 만든 시각을 제도 시행 시각인 척하지 않는다."""
    seed_policies(store, at=T0)
    for version in store.rule_versions.list():
        assert version.effective_from is None
        assert version.effective_to is None


def test_seeded_rules_are_active_regardless_of_the_clock(store):
    """결정성 — 고정 클럭을 어디에 두든 판정에 참여하는 규칙 집합이 같아야 한다."""
    seed_policies(store, at=T0)
    expected = [p["id"] for p in POLICIES_JSON]

    for probe in (T0.replace(year=1999), T0, T0.replace(year=2099)):
        assert [v.policy_id for v in store.rule_versions.active(probe)] == expected


def test_seeding_leaves_a_system_seed_audit_trail(store):
    """계약 결정 #5 — 사람 승인이 아니라 시드였음이 감사로그에 드러난다."""
    seed_policies(store, at=T0)
    events = store.audit.list()

    assert events, "시드가 감사기록을 남기지 않았다"
    assert all(e.actor == "system:seed" for e in events)
    assert {e.target for e in events} >= {p["id"] for p in POLICIES_JSON}


# --------------------------------------------------------------------------
# 전체 · 멱등성
# --------------------------------------------------------------------------


def test_seed_all_populates_everything(store):
    seed_all(store, at=T0)

    assert len(store.model_constants.list()) == len(REGISTRY["entries"])
    assert len(store.regions.list()) == len(REGIONS_JSON)
    assert len(store.rule_versions.list()) == len(POLICIES_JSON)


def test_seeding_twice_changes_nothing(store):
    """시연 중 스크립트를 두 번 돌리는 일은 반드시 일어난다.
    RuleVersion 은 불변이므로 재시드가 중복 삽입이나 예외로 터지면 안 된다."""
    seed_all(store, at=T0)
    before = (
        {c.key: c.value for c in store.model_constants.list()},
        [r.code for r in store.regions.list()],
        [(v.id, v.policy_id) for v in store.rule_versions.list()],
        len(store.audit.list()),
    )

    seed_all(store, at=T0 + timedelta(days=1))

    after = (
        {c.key: c.value for c in store.model_constants.list()},
        [r.code for r in store.regions.list()],
        [(v.id, v.policy_id) for v in store.rule_versions.list()],
        len(store.audit.list()),
    )
    assert before == after


def test_seeding_requires_an_aware_timestamp(store):
    from firsthome.store.errors import StoreError

    with pytest.raises(StoreError):
        seed_all(store, at=T0.replace(tzinfo=None))


# --------------------------------------------------------------------------
# 시딩 충실도 — 저장소가 시드 파일을 그대로 담았는가
# --------------------------------------------------------------------------
#
# ★ **대조의 상대가 바뀌었다** (Wave 2 컷오버). 예전에는 오른쪽 변이
#   `engines.load_regions()` · `load_policies()` 였다. 그 둘은 컷오버로 사라졌다 —
#   `lru_cache` 로 데이터 파일을 읽던 경로이고, SPEC 2.3 이 금지하는 프로세스 수명
#   캐시였다. 엔진에 파일 I/O 를 남겨 두는 것은 SPEC 1.2 위반이므로, 테스트를 살리려고
#   그 함수를 남기지 않았다.
#
#   논지는 사라진 것이 아니라 **옮겨갔다.** 예전 논지가 「저장소 == 엔진이 읽던 것」
#   이었다면 지금은 「저장소 == 시드 파일」이며, 그것이 곧 **시딩 충실도** 검사다.
#   판정이 실제로 저장소를 보는지는 `api/test_store_cutover.py` 가 HTTP 계층에서 진다.


def _seed_file(name: str) -> list:
    """`store/seed.py` 가 읽는 그 파일을 같은 자리에서 읽는다.

    경로를 여기 다시 적지 않고 `SEED_DATA_DIR` 를 쓴다 — 두 벌이 되면 시드가 옮겨갈 때
    이 테스트만 옛 자리를 보며 조용히 통과한다.
    """
    key = name.removesuffix(".json")
    return json.loads((SEED_DATA_DIR / name).read_text(encoding="utf-8"))[key]


def test_store_holds_exactly_the_regions_the_seed_file_declares(store):
    seed_regions(store)
    declared = [entry["payload"] for entry in _seed_file("regions.json")]
    assert [r.to_engine_dict() for r in store.regions.list()] == declared


def test_store_holds_exactly_the_policies_the_seed_file_declares(store):
    seed_policies(store, at=T0)
    active = store.rule_versions.active(T0)
    assert [v.payload for v in active] == _seed_file("policies.json")
