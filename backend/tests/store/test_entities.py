"""SPEC 2.2 엔티티 9종이 저장소에 실제로 왕복하는지.

두 백엔드 모두에서 돈다 — 계약이 매체에 기대고 있지 않음을 그 자체로 보인다.
"""

from __future__ import annotations

import unicodedata

import pytest
from conftest import (
    T0,
    make_approval,
    make_audit_event,
    make_constant,
    make_draft,
    make_policy_source,
    make_region,
    make_rule_version,
    make_user,
)

from firsthome.store.errors import RecordNotFoundError, SpanOutOfRangeError, StoreError
from firsthome.store.models import RuleSpanMapping


# --------------------------------------------------------------------------
# 1. Region
# --------------------------------------------------------------------------


def test_region_round_trips_with_its_provenance(store):
    store.regions.upsert(make_region("11440"))
    region = store.regions.get("11440")

    assert region.name == "서울 마포구"
    assert region.jeonse_ratio_pct == 71.2
    assert region.guarantee_available is True
    assert region.provenance.verification == "unverified"


def test_region_upsert_replaces_rather_than_duplicates(store):
    store.regions.upsert(make_region("11440", monthly_rent_krw=850_000))
    store.regions.upsert(make_region("11440", monthly_rent_krw=900_000))

    assert len(store.regions.list()) == 1
    assert store.regions.get("11440").monthly_rent_krw == 900_000


def test_unknown_region_is_none_not_an_error(store):
    assert store.regions.get("99999") is None


def test_region_booleans_survive_the_round_trip(store):
    """SQLite 에는 boolean 이 없다. 0/1 이 True/False 로 되돌아오지 않으면
    `guaranteeAvailable` 이 조용히 문자열·정수가 되어 리스크 판정이 바뀐다."""
    store.regions.upsert(make_region("11440", guarantee_available=False))
    value = store.regions.get("11440").guarantee_available
    assert value is False and isinstance(value, bool)


# --------------------------------------------------------------------------
# 2. PolicySource
# --------------------------------------------------------------------------


def test_policy_source_round_trips(store):
    store.policy_sources.add(make_policy_source("src-1", text="만 19세 이상"))
    source = store.policy_sources.get("src-1")

    assert source.text == "만 19세 이상"
    assert source.source_ref == "https://example.invalid/notice/1"
    assert source.fetched_at == T0


def test_policy_source_attribution_round_trips(store):
    """계약 결정 #15 — 출처표시 문구는 저장 경로를 **통과**해야 한다.

    `source_ref` 는 기계가 쓰는 참조(URL)이고 `attribution` 은 사람이 읽는 출처표시
    문장이다. 둘을 한 필드로 합치면 화면이 URL 만 뽑아내지 못한다 (코디네이터 결정
    2026-08-14). 저장소는 두 칸을 **따로** 보존한다.

    ★ 저장소는 `attribution` 을 **요구하지 않는다** — 그것은 원자료가 아니라 이용조건에서
      오는 의무이므로 강제는 적재 경로(`ingest`)의 몫이다. 여기서 보는 것은 보존뿐이다.
    """
    attribution = "서울특별시 주택정책과 「공고」 (제2026-1호) · 공공누리 제4유형"
    store.policy_sources.add(make_policy_source("src-1", attribution=attribution))

    assert store.policy_sources.get("src-1").attribution == attribution
    assert [s.attribution for s in store.policy_sources.list()] == [attribution]
    # 참조는 참조대로 남는다. 합쳐지지 않는다.
    assert store.policy_sources.get("src-1").source_ref == "https://example.invalid/notice/1"


def test_policy_source_without_an_attribution_is_still_storable(store):
    """저장소 계층은 출처표시를 강제하지 않는다. 강제 지점이 어디인지를 못박아 둔다.

    강제하면 `PolicySource` 를 쓰는 다른 경로(시드·픽스처)가 전부 이용조건을 아는
    척해야 한다. 의무는 **무엇을 적재하는가**에서 오므로 게이트는 `ingest` 에 있다.
    """
    store.policy_sources.add(make_policy_source("src-1"))
    assert store.policy_sources.get("src-1").attribution is None


def test_policy_source_text_is_nfc_normalised_once_at_write_time(store):
    """계약 결정 #7 — 정규화는 저장 시 한 번. 검증 시점에 다시 주무르지 않는다.

    한글은 NFD(자모 분해)와 NFC(완성형)의 코드포인트 길이가 다르다. 정규화하지 않으면
    같은 글자에 대해 span 오프셋이 두 벌 생긴다.
    """
    decomposed = unicodedata.normalize("NFD", "청년 전세자금")
    assert decomposed != "청년 전세자금"

    store.policy_sources.add(make_policy_source("src-1", text=decomposed))
    stored = store.policy_sources.get("src-1").text

    assert stored == unicodedata.normalize("NFC", decomposed)
    assert unicodedata.is_normalized("NFC", stored)


def test_policy_source_normalisation_is_idempotent(store):
    store.policy_sources.add(make_policy_source("src-1", text=unicodedata.normalize("NFD", "청년")))
    once = store.policy_sources.get("src-1").text
    store.policy_sources.add(make_policy_source("src-2", text=once))
    assert store.policy_sources.get("src-2").text == once


# --------------------------------------------------------------------------
# 3. RuleDraft
# --------------------------------------------------------------------------


def test_rule_draft_round_trips_with_an_opaque_payload(store):
    """계약 결정 #7 — 0단계의 규칙 본문은 불투명 JSON 이다. 스키마를 발명하지 않는다."""
    store.policy_sources.add(make_policy_source("src-1"))
    store.rule_drafts.add(make_draft("draft-1", payload={"criteria": {"ageMin": 19}, "임의필드": [1, 2]}))

    assert store.rule_drafts.get("draft-1").payload == {"criteria": {"ageMin": 19}, "임의필드": [1, 2]}


@pytest.mark.parametrize("status", ["pending", "approved", "rejected", "extraction_failed"])
def test_every_spec_draft_status_is_accepted(store, status):
    store.policy_sources.add(make_policy_source("src-1"))
    store.rule_drafts.add(make_draft("draft-1"))
    store.rule_drafts.set_status("draft-1", status)
    assert store.rule_drafts.get("draft-1").status == status


def test_an_unknown_draft_status_is_rejected(store):
    store.policy_sources.add(make_policy_source("src-1"))
    with pytest.raises(StoreError):
        store.rule_drafts.add(make_draft("draft-1", status="probably_fine"))


def test_a_draft_must_point_at_a_real_policy_source(store):
    """원문이 없으면 span 검증이 성립하지 않는다 (SPEC 4.2.1)."""
    with pytest.raises(RecordNotFoundError):
        store.rule_drafts.add(make_draft("draft-1", policy_source_id="src-missing"))


def test_extraction_failure_keeps_its_reason(store):
    """실패는 숨기지 않는다 (SPEC 4.2.2)."""
    store.policy_sources.add(make_policy_source("src-1"))
    store.rule_drafts.add(make_draft("draft-1"))
    store.rule_drafts.set_status("draft-1", "extraction_failed", failure_reason="span 검증 실패")

    failed = store.rule_drafts.list(status="extraction_failed")
    assert [d.id for d in failed] == ["draft-1"]
    assert failed[0].failure_reason == "span 검증 실패"


# --------------------------------------------------------------------------
# 4. RuleSpanMapping
# --------------------------------------------------------------------------

TEXT = "만 19세 이상 34세 이하인 무주택 청년"


@pytest.fixture
def drafted(store):
    store.policy_sources.add(make_policy_source("src-1", text=TEXT))
    store.rule_drafts.add(make_draft("draft-1"))
    return store


def test_span_resolves_to_the_quoted_slice(drafted):
    span = RuleSpanMapping(id="sp-1", draft_id="draft-1", field_path="/criteria/ageMin", start=2, end=5)
    drafted.rule_drafts.add_span(span)

    assert drafted.rule_drafts.resolve_span(span) == "19세"
    assert [s.field_path for s in drafted.rule_drafts.spans_for("draft-1")] == ["/criteria/ageMin"]


def test_span_offsets_are_code_points_not_bytes(drafted):
    """계약 결정 #7. 한글은 UTF-8 로 3바이트다 — 바이트 오프셋이면 여기서 어긋난다."""
    span = RuleSpanMapping(id="sp-1", draft_id="draft-1", field_path="/x", start=0, end=1)
    drafted.rule_drafts.add_span(span)

    assert drafted.rule_drafts.resolve_span(span) == "만"
    assert len(TEXT.encode("utf-8")) != len(TEXT)


def test_span_is_half_open(drafted):
    span = RuleSpanMapping(id="sp-1", draft_id="draft-1", field_path="/x", start=0, end=len(TEXT))
    drafted.rule_drafts.add_span(span)
    assert drafted.rule_drafts.resolve_span(span) == TEXT


@pytest.mark.parametrize(
    "start, end",
    [(-1, 3), (0, 0), (5, 2), (0, len(TEXT) + 1), (len(TEXT), len(TEXT) + 5)],
)
def test_an_out_of_range_span_is_rejected(drafted, start, end):
    with pytest.raises(SpanOutOfRangeError):
        drafted.rule_drafts.add_span(
            RuleSpanMapping(id="sp-1", draft_id="draft-1", field_path="/x", start=start, end=end)
        )
    assert drafted.rule_drafts.spans_for("draft-1") == []


def test_field_path_must_be_an_rfc6901_json_pointer(drafted):
    """계약 결정 #7 — 지금 파싱하지 않아도 의미는 지금 고정한다."""
    with pytest.raises(StoreError):
        drafted.rule_drafts.add_span(
            RuleSpanMapping(id="sp-1", draft_id="draft-1", field_path="criteria.ageMin", start=0, end=1)
        )


def test_the_empty_json_pointer_addresses_the_draft_root(drafted):
    drafted.rule_drafts.add_span(
        RuleSpanMapping(id="sp-1", draft_id="draft-1", field_path="", start=0, end=1)
    )
    assert len(drafted.rule_drafts.spans_for("draft-1")) == 1


# --------------------------------------------------------------------------
# 5. RuleVersion — 창·불변성은 test_active_rules / test_rule_version_immutability
# --------------------------------------------------------------------------


def test_rule_version_round_trips(store):
    store.rule_versions.add(make_rule_version("rv-1"))
    version = store.rule_versions.get("rv-1")

    assert version.policy_id == "buttress_youth"
    assert version.payload["maxAmountKRW"] == 200_000_000
    assert version.origin == "seed"


# --------------------------------------------------------------------------
# 6. ModelConstant
# --------------------------------------------------------------------------


#: 계약 `valueTypeVocabulary` 의 각 항목을 대표하는 값.
REPRESENTATIVE_VALUES = {
    "ratio": 0.30,
    "percent_rate": 3.0,
    "percent_level": 71.2,
    "krw": 30_000_000,
    "years": 5,
    "score_points": 34.0,
    "krw_by_household": {1: 1_200_000, 2: 1_900_000, 3: 2_500_000, 4: 3_000_000},
    "policy_id_order": ("sme_youth_deposit", "buttress_youth"),
    "guarantee_rate_table": [
        {"depositMaxKRW": 100_000_000, "housingType": "apartment",
         "debtRatioMaxPct": 70, "ratePct": 0.097},
    ],
    "lookup_rule": "bracket_max",
    "sido_code_prefixes": ["11", "28", "41"],
    "attempts": 2,
    "multiple": 3.0,
    "count": 10,
    "months": 3,
    "sqm": 85,
    "seconds": 20,
}


def test_the_representative_set_covers_the_whole_contract_vocabulary():
    """계약에 새 `value_type` 이 생기면 여기서 **먼저 터진다.**

    아래 왕복 테스트를 손으로 적은 목록으로 돌리면, 계약이 어휘를 늘려도 조용히
    지나가고 새 타입은 검증 없이 저장소를 통과한다. 실제로 `percent` 가
    `percent_rate` / `percent_level` 로 갈렸을 때 그 일이 일어날 뻔했다.
    """
    import json
    from pathlib import Path

    contracts = Path(__file__).resolve().parents[3] / "contracts"
    registry = json.loads((contracts / "model_constants.json").read_text(encoding="utf-8"))
    assert set(REPRESENTATIVE_VALUES) == set(registry["valueTypeVocabulary"])


@pytest.mark.parametrize("value_type", sorted(REPRESENTATIVE_VALUES))
def test_every_registry_value_type_round_trips_with_its_python_type(store, value_type):
    """계약의 `valueTypeVocabulary` 전종. 타입이 바뀌면 곱셈 한 번에 판정 숫자가 바뀐다."""
    value = REPRESENTATIVE_VALUES[value_type]
    store.model_constants.put(make_constant("x.y", value_type=value_type, value=value))
    stored = store.model_constants.get("x.y").value

    assert stored == value
    assert type(stored) is type(value)
    if value_type == "krw_by_household":
        assert all(isinstance(k, int) for k in stored), "가구원수 키가 문자열로 되돌아왔다"


def test_int_valued_constants_do_not_come_back_as_float(store):
    """`krw` 가 float 이 되면 통화 반올림 경로가 달라진다 (계약 #3)."""
    store.model_constants.put(make_constant("x.krw", value_type="krw", value=30_000_000))
    value = store.model_constants.get("x.krw").value
    assert isinstance(value, int) and not isinstance(value, bool)


def test_a_constant_that_never_had_a_code_symbol_stores_a_null(store):
    """인라인 리터럴로만 존재하던 값은 외부화 전에 **이름이 없었다** (레지스트리 41키).
    없는 이름을 빈 문자열이나 키 이름으로 메우면 '원래 심볼명' 이 거짓이 된다."""
    store.model_constants.put(
        make_constant("risk.jeonse_ratio_weight_1", legacy_symbol=None, value_type="score_points", value=4.0)
    )
    assert store.model_constants.get("risk.jeonse_ratio_weight_1").legacy_symbol is None


def test_as_mapping_is_keyed_by_the_contract_key(store):
    store.model_constants.put(make_constant("affordability.buffer_ratio", value=0.10))
    store.model_constants.put(make_constant("tco.horizon_years", value_type="years", value=5))

    mapping = store.model_constants.as_mapping()
    assert mapping == {"affordability.buffer_ratio": 0.10, "tco.horizon_years": 5}


def test_mutating_the_returned_mapping_does_not_touch_the_store(store):
    """주입 매핑은 사본이어야 한다. 엔진이 넘겨받은 dict 를 고치면 다음 판정이 달라진다."""
    store.model_constants.put(
        make_constant("a.by_household", value_type="krw_by_household", value={1: 100})
    )
    mapping = store.model_constants.as_mapping()
    mapping["a.by_household"][1] = 999
    mapping["injected"] = 1

    assert store.model_constants.as_mapping() == {"a.by_household": {1: 100}}


# --------------------------------------------------------------------------
# 7. User / Role
# --------------------------------------------------------------------------


@pytest.mark.parametrize("role", ["citizen", "counselor", "rule_manager"])
def test_the_three_spec_roles_are_accepted(store, role):
    store.users.add(make_user("u-1", username=f"user_{role}", role=role))
    assert store.users.get("u-1").role == role


def test_an_unknown_role_is_rejected(store):
    with pytest.raises(StoreError):
        store.users.add(make_user("u-1", role="superuser"))


def test_users_are_looked_up_by_username(store):
    store.users.add(make_user("u-1", username="admin_1"))
    assert store.users.get_by_username("admin_1").id == "u-1"
    assert store.users.get_by_username("nobody") is None


def test_duplicate_usernames_are_rejected(store):
    store.users.add(make_user("u-1", username="admin_1"))
    with pytest.raises(StoreError):
        store.users.add(make_user("u-2", username="admin_1"))


def test_the_store_ships_no_seeded_account(store):
    """SPEC 6.3 — 시드 계정 비밀번호는 커밋하지 않는다. 저장소는 계정을 만들지 않는다."""
    from firsthome.store.seed import seed_all

    seed_all(store)
    assert store.users.list() == []


# --------------------------------------------------------------------------
# 8. ApprovalRecord
# --------------------------------------------------------------------------


def test_approval_record_keeps_who_when_what_why(store):
    store.approvals.add(
        make_approval("ap-1", actor_user_id="u-1", target_id="draft-1", decision="approved")
    )
    record = store.approvals.list_for("draft-1")[0]

    assert (record.actor_user_id, record.at, record.target_id, record.decision) == (
        "u-1", T0, "draft-1", "approved",
    )


def test_a_rejection_without_a_reason_is_refused(store):
    """SPEC 10.2 5단계 — 사유 없이 반려할 수 없다."""
    for reason in (None, "", "   "):
        with pytest.raises(StoreError):
            store.approvals.add(make_approval("ap-1", decision="rejected", reason=reason))
    assert store.approvals.list() == []


def test_a_rejection_with_a_reason_is_accepted(store):
    store.approvals.add(
        make_approval("ap-1", decision="rejected", reason="소득 상한이 원문과 다릅니다")
    )
    assert store.approvals.list_for("draft-1")[0].reason == "소득 상한이 원문과 다릅니다"


def test_an_unknown_decision_is_rejected(store):
    with pytest.raises(StoreError):
        store.approvals.add(make_approval("ap-1", decision="maybe"))


# --------------------------------------------------------------------------
# 9. AuditEvent — append-only 는 test_audit_append_only
# --------------------------------------------------------------------------


def test_audit_event_keeps_before_and_after(store):
    store.audit.append(
        make_audit_event("ae-1", before={"status": "pending"}, after={"status": "approved"})
    )
    event = store.audit.list()[0]

    assert event.before == {"status": "pending"}
    assert event.after == {"status": "approved"}
    assert (event.actor, event.action, event.target, event.outcome) == (
        "u-1", "rule.approve", "draft-1", "success",
    )


# --------------------------------------------------------------------------
# 백엔드 동등성 — 두 구현이 같은 자리에서 같은 이유로 거부해야 한다
# --------------------------------------------------------------------------


def test_a_duplicate_draft_id_is_rejected(store):
    """같은 id 로 다시 넣는 것이 조용한 덮어쓰기가 되면 초안 이력이 사라진다."""
    store.policy_sources.add(make_policy_source("src-1"))
    store.rule_drafts.add(make_draft("draft-1", payload={"v": 1}))

    with pytest.raises(StoreError):
        store.rule_drafts.add(make_draft("draft-1", payload={"v": 2}))
    assert store.rule_drafts.get("draft-1").payload == {"v": 1}


def test_a_duplicate_user_id_is_rejected(store):
    store.users.add(make_user("u-1", username="a"))
    with pytest.raises(StoreError):
        store.users.add(make_user("u-1", username="b"))
    assert store.users.get("u-1").username == "a"


def test_a_duplicate_audit_event_id_is_rejected(store):
    """감사기록을 덮어쓰는 것은 삭제와 같다 (SPEC 7.1)."""
    store.audit.append(make_audit_event("ae-1", outcome="success"))
    with pytest.raises(StoreError):
        store.audit.append(make_audit_event("ae-1", outcome="tampered"))
    assert [e.outcome for e in store.audit.list()] == ["success"]


def test_a_duplicate_approval_record_id_is_rejected(store):
    store.approvals.add(make_approval("ap-1", decision="approved"))
    with pytest.raises(StoreError):
        store.approvals.add(make_approval("ap-1", decision="rejected", reason="사유"))
    assert [r.decision for r in store.approvals.list()] == ["approved"]
