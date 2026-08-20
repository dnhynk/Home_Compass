"""SPEC 6.4 · 7.1 · 계약 결정 #38 — 이상 신고는 `RuleDraft` 가 아니다.

이 파일이 재는 것은 「신고를 저장할 수 있는가」가 아니라 **「신고와 초안이 실제로 갈려
있는가」** 다. 결정 #38 이 든 이유가 그대로 검사가 된다 —

    |            | `RuleDraft`                  | 이상 신고        |
    |------------|------------------------------|------------------|
    | 만든 주체  | 기계 (LLM 추출)              | **사람** (상담원) |
    | 걸리는 방어 | 스키마 · span · 부분 저장 금지 | 없다             |
    | 승인의 뜻  | 규칙이 된다                   | **아무것도 되지 않는다** |

한 엔티티로 합치면 둘 중 하나의 방어가 반드시 헐거워진다. 그래서 여기서 고정하는 것은
**섞이지 않는다**는 사실이다 — 신고를 아무리 만들어도 `rule_drafts` 도 `rule_versions` 도
움직이지 않고, 판정에 참여하는 `active()` 도 그대로다.

## 신고에 거는 방어는 딱 하나다 — **대상**

SPEC 7.1 의 표가 6.4 를 콕 집어 적었다. 사유는 자유 입력이라 고객 상황이 섞일 수 있으므로,
**대상만은 정책·시세 항목으로 한정한다.** 자유 텍스트로 대상을 받으면 그 칸이 두 번째
자유 입력이 되고 7.1 이 통째로 무력화된다. 그 한정이 화면 문구가 아니라 **저장소의 문**
이어야 한다는 것이 이 파일의 두 번째 주제다 — 화면 문구는 규율이고, 이 문은 구조다.

두 백엔드로 파라미터화된 `store` 픽스처를 쓴다. 매체가 달라도 같은 문을 지나야 한다 (부록 A).
"""

from __future__ import annotations

import pytest
from conftest import T0, make_draft, make_policy_source, make_report, make_rule_version

from firsthome.store.errors import RecordNotFoundError, StoreError
from firsthome.store.models import (
    POLICY_REPORT_FIELDS,
    REGION_FACT_FIELDS,
    REPORT_STATUSES,
    REPORT_TARGET_KINDS,
    AnomalyReport,
)


# ==========================================================================
# 1. 저장하고 되읽는다 — 최소 필드 다섯 (신고자 · 시각 · 대상 · 사유 · 상태)
# ==========================================================================

class TestAReportRoundTrips:
    def test_it_comes_back_with_every_field_intact(self, store):
        stored = store.reports.add(make_report("rep-1"))
        assert stored.id == "rep-1"

        read = store.reports.get("rep-1")
        assert read is not None
        assert read.reporter == "counselor"
        assert read.at == T0
        assert read.target_kind == "policy"
        assert read.target_id == "buttress_youth"
        assert read.target_field == "status"
        assert read.reason == "고객이 이 제도가 지난달에 없어졌다고 한다"
        assert read.status == "open"

    def test_an_unknown_id_is_absence_not_an_error(self, store):
        assert store.reports.get("nope") is None

    def test_the_listing_keeps_the_order_it_was_written_in(self, store):
        for index in range(3):
            store.reports.add(make_report(f"rep-{index}"))
        assert [r.id for r in store.reports.list()] == ["rep-0", "rep-1", "rep-2"]

    def test_the_same_id_cannot_be_filed_twice(self, store):
        store.reports.add(make_report("rep-1"))
        with pytest.raises(StoreError):
            store.reports.add(make_report("rep-1"))

    def test_the_listing_can_be_filtered_by_status(self, store):
        store.reports.add(make_report("rep-open"))
        store.reports.add(make_report("rep-closed", status="closed"))
        assert [r.id for r in store.reports.list(status="open")] == ["rep-open"]
        assert [r.id for r in store.reports.list(status="closed")] == ["rep-closed"]
        assert len(store.reports.list()) == 2


# ==========================================================================
# 2. ★ 대상은 닫힌 목록이다 (SPEC 7.1 · 계약 결정 #38)
# ==========================================================================
#
# 「신고 대상은 정책·시세 **항목**으로 한정한다 (자유 텍스트로 대상을 받지 않는다).」
# 그 한정을 저장소가 진다. API 계층에만 두면 저장소를 바꾸는 순간 보장이 사라지고
# (부록 A), 무엇보다 **자유 텍스트 칸이 하나 더 생기는 것**이 7.1 이 막으려던 그것이다.

class TestTheTargetIsRestrictedToPolicyAndMarketItems:
    def test_an_unknown_target_kind_is_refused(self, store):
        with pytest.raises(StoreError):
            store.reports.add(make_report("rep-1", target_kind="customer"))

    @pytest.mark.parametrize("free_text", [
        "고객 김OO 님이 말씀하신 내용",
        "그냥 이상함",
        "",
    ])
    def test_a_free_text_target_field_is_refused(self, store, free_text):
        """★ 이 케이스가 이 파일의 존재 이유다 — 대상 칸이 두 번째 자유 입력이 되면 안 된다."""
        with pytest.raises(StoreError):
            store.reports.add(make_report("rep-1", target_field=free_text))

    def test_a_market_field_outside_the_eight_fact_fields_is_refused(self, store):
        with pytest.raises(StoreError):
            store.reports.add(
                make_report("rep-1", target_kind="region", target_id="11440",
                            target_field="jeonseMedianKRW_2")
            )

    def test_a_policy_field_name_is_not_accepted_for_a_market_target(self, store):
        """종류가 다르면 항목 목록도 다르다. 섞이면 한정이 사실상 합집합이 된다."""
        with pytest.raises(StoreError):
            store.reports.add(
                make_report("rep-1", target_kind="region", target_id="11440",
                            target_field="maxAmountKRW")
            )

    @pytest.mark.parametrize("field_name", REGION_FACT_FIELDS)
    def test_every_market_fact_field_is_reportable(self, store, field_name):
        """시세는 **저장소가 아는 사실 필드 8종 그대로**다 — 목록을 두 벌 만들지 않는다."""
        store.reports.add(
            make_report(f"rep-{field_name}", target_kind="region", target_id="11440",
                        target_field=field_name)
        )

    @pytest.mark.parametrize("field_name", POLICY_REPORT_FIELDS)
    def test_every_policy_item_on_the_screen_is_reportable(self, store, field_name):
        store.reports.add(make_report(f"rep-{field_name}", target_field=field_name))

    def test_an_empty_target_id_is_refused(self, store):
        with pytest.raises(StoreError):
            store.reports.add(make_report("rep-1", target_id="  "))


# ==========================================================================
# 3. 나머지 최소 조건 — 사유 · 시각 · 상태
# ==========================================================================

class TestTheRemainingFieldsCarryTheirOwnMinimum:
    @pytest.mark.parametrize("blank", ["", "   ", "\n"])
    def test_a_report_without_a_reason_is_refused(self, store, blank):
        """사유가 신고의 내용 전부다. 비어 있으면 규칙관리자가 볼 것이 남지 않는다."""
        with pytest.raises(StoreError):
            store.reports.add(make_report("rep-1", reason=blank))

    def test_a_naive_timestamp_is_refused(self, store):
        import datetime as _dt

        with pytest.raises(StoreError):
            store.reports.add(make_report("rep-1", at=_dt.datetime(2026, 8, 15, 9, 0)))

    def test_an_anonymous_report_is_refused_at_the_store_too(self, store):
        """SPEC 6.4 — 신고자를 남긴다. **익명은 안 된다.**

        API 가 이미 401 로 막지만(6.1), 저장소가 빈 신고자를 받으면 어떤 경로로든 들어온
        신고 하나가 [누가 올렸는지 모르는 기록]이 된다. 감사추적이 그 자리에서 끊긴다.
        """
        with pytest.raises(StoreError):
            store.reports.add(make_report("rep-1", reporter=""))

    def test_an_unknown_status_is_refused(self, store):
        with pytest.raises(StoreError):
            store.reports.add(make_report("rep-1", status="approved"))

    def test_the_status_vocabulary_does_not_borrow_the_draft_one(self):
        """★ 초안의 상태어를 빌려 쓰지 않는다. `approved` 인 신고는 뜻이 없다 —
        신고는 승인의 대상이 아니라 제안이다 (계약 결정 #38 의 표 셋째 행)."""
        assert set(REPORT_STATUSES).isdisjoint({"approved", "rejected", "extraction_failed"})
        assert set(REPORT_TARGET_KINDS) == {"policy", "region"}


# ==========================================================================
# 4. ★★ 신고는 규칙을 바꾸지 않는다 (SPEC 6.4 SoD · 10.2 6-A)
# ==========================================================================

class TestAReportChangesNoRule:
    def test_filing_reports_creates_no_draft_and_no_rule_version(self, store):
        before_drafts = len(store.rule_drafts.list())
        before_versions = len(store.rule_versions.list())

        for index in range(5):
            store.reports.add(make_report(f"rep-{index}"))

        assert len(store.rule_drafts.list()) == before_drafts
        assert len(store.rule_versions.list()) == before_versions

    def test_a_report_does_not_enter_the_active_rule_set(self, store):
        """SPEC 2.3 — 판정에 참여하는 것은 `active()` 뿐이고 신고는 거기 없다."""
        store.rule_versions.add(make_rule_version("rv-1"))
        before = [v.id for v in store.rule_versions.active(T0)]

        store.reports.add(make_report("rep-1"))

        assert [v.id for v in store.rule_versions.active(T0)] == before

    def test_the_report_repository_exposes_no_way_to_decide_anything(self, store):
        """★ 「여기 없는 것이 곧 보장이다」 — 승인·반려·상태전이 메서드가 **없다**.

        SPEC 은 6-A 에 [신고를 처리하는] 동작을 배정하지 않았다. 규칙관리자가 수동으로
        입력하거나 재추출을 지시한다고만 적혀 있다. 없는 기능을 저장소에 미리 뚫어 두면
        그것이 곧 신고가 규칙이 되는 경로다.
        """
        surface = {name for name in dir(store.reports) if not name.startswith("_")}
        assert surface == {"add", "get", "list"}, surface

    def test_the_two_entities_do_not_share_a_table(self, store):
        """신고 id 와 초안 id 가 같아도 서로를 덮지 않는다 — 다른 저장소다."""
        store.policy_sources.add(make_policy_source("src-1"))
        store.rule_drafts.add(make_draft("same-id"))
        store.reports.add(make_report("same-id"))

        assert store.rule_drafts.get("same-id").status == "pending"
        assert store.reports.get("same-id").status == "open"
        assert isinstance(store.reports.get("same-id"), AnomalyReport)

    def test_a_report_needs_no_policy_source(self, store):
        """초안은 원문이 없으면 들어가지 못한다 (`RecordNotFoundError`). 신고는 다르다 —
        **사람이 낸 것이므로 원문 인용도 span 도 없다.** 그 비대칭이 결정 #38 그 자체다."""
        with pytest.raises(RecordNotFoundError):
            store.rule_drafts.add(make_draft("draft-1"))
        store.reports.add(make_report("rep-1"))
        assert store.reports.get("rep-1") is not None
