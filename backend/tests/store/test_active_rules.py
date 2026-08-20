"""SPEC 2.3 — 판정에 무엇이 참여하는가를 **쿼리 계층에서** 강제한다.

    판정은 RuleVersion 중 approved 이고 effective_from <= now < effective_to 인 것만 쓴다.
    RuleDraft 는 어떤 경로로도 판정에 참여할 수 없다.

NULL 의 의미 (코디네이터 8.2 결정) — effective_from NULL = 시작일 미상,
effective_to NULL = 무기한. 시드 규칙은 시행 시점을 모르므로 from 이 NULL 이다.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from conftest import KST, T0, make_draft, make_policy_source, make_rule_version

from firsthome.store.models import RuleDraft, RuleVersion


# --------------------------------------------------------------------------
# 시간 창
# --------------------------------------------------------------------------


def test_rule_outside_its_window_is_not_active(store):
    store.rule_versions.add(
        make_rule_version("rv-1", effective_from=T0, effective_to=T0 + timedelta(days=10))
    )

    assert store.rule_versions.active(T0 - timedelta(seconds=1)) == []
    assert [v.id for v in store.rule_versions.active(T0)] == ["rv-1"]
    assert [v.id for v in store.rule_versions.active(T0 + timedelta(days=9))] == ["rv-1"]
    assert store.rule_versions.active(T0 + timedelta(days=10)) == [], "effective_to 는 반열린 끝이다"


def test_effective_from_is_inclusive_and_effective_to_is_exclusive(store):
    """경계가 어느 쪽으로 열렸는지가 판정 결과를 가른다 — 한 초 차이로 고정한다."""
    end = T0 + timedelta(days=1)
    store.rule_versions.add(make_rule_version("rv-1", effective_from=T0, effective_to=end))

    assert len(store.rule_versions.active(T0)) == 1, "from 은 포함이다 (<=)"
    assert len(store.rule_versions.active(end - timedelta(microseconds=1))) == 1
    assert len(store.rule_versions.active(end)) == 0, "to 는 제외다 (<)"


def test_null_bounds_mean_unknown_start_and_open_ended(store):
    """시드 규칙은 시행 시점을 모른다. 벽시계 시각을 지어내지 않았음이 여기서 드러난다."""
    store.rule_versions.add(make_rule_version("rv-seed", effective_from=None, effective_to=None))

    far_past = T0.replace(year=1999)
    far_future = T0.replace(year=2099)
    assert [v.id for v in store.rule_versions.active(far_past)] == ["rv-seed"]
    assert [v.id for v in store.rule_versions.active(far_future)] == ["rv-seed"]


def test_active_query_compares_instants_not_strings(store):
    """같은 순간을 다른 오프셋으로 물어도 같은 답이 나와야 한다.

    RFC 3339 문자열을 그대로 비교하면 '2026-08-13T09:00+09:00' 과
    '2026-08-13T00:00+00:00' 이 다른 시각으로 취급된다 — 둘은 같은 순간이다.
    """
    from datetime import timezone

    store.rule_versions.add(make_rule_version("rv-1", effective_from=T0, effective_to=None))

    same_instant_utc = T0.astimezone(timezone.utc)
    assert T0 == same_instant_utc
    assert [v.id for v in store.rule_versions.active(same_instant_utc)] == ["rv-1"]

    just_before_utc = (T0 - timedelta(seconds=1)).astimezone(timezone.utc)
    assert store.rule_versions.active(just_before_utc) == []


def test_active_requires_an_aware_timestamp(store):
    from firsthome.store.errors import StoreError

    with pytest.raises(StoreError):
        store.rule_versions.active(T0.replace(tzinfo=None))


# --------------------------------------------------------------------------
# RuleDraft 누수 — 원칙 2의 기계적 강제
# --------------------------------------------------------------------------


def test_approved_draft_never_leaks_into_the_active_rule_set(store):
    """가장 위험한 경우: draft 의 status 도 'approved' 가 될 수 있다 (SPEC 2.2).

    상태 글자만 보고 거르는 구현이면 여기서 샌다.
    """
    store.policy_sources.add(make_policy_source("src-1"))
    store.rule_drafts.add(make_draft("draft-1", status="pending"))
    store.rule_drafts.set_status("draft-1", "approved")

    assert store.rule_drafts.get("draft-1").status == "approved"
    assert store.rule_versions.active(T0) == [], "approved 인 draft 가 판정에 새어들었다"


@pytest.mark.parametrize("status", ["pending", "approved", "rejected", "extraction_failed"])
def test_no_draft_status_whatsoever_reaches_the_active_rule_set(store, status):
    store.policy_sources.add(make_policy_source("src-1"))
    store.rule_drafts.add(make_draft("draft-1"))
    store.rule_drafts.set_status("draft-1", status)

    active = store.rule_versions.active(T0)
    assert active == []
    assert all(isinstance(v, RuleVersion) for v in active)
    assert not any(isinstance(v, RuleDraft) for v in active)


def test_active_returns_only_rule_versions_even_when_both_tables_are_full(store):
    store.policy_sources.add(make_policy_source("src-1"))
    for i in range(3):
        store.rule_drafts.add(make_draft(f"draft-{i}", status="approved"))
    store.rule_versions.add(make_rule_version("rv-1"))

    active = store.rule_versions.active(T0)
    assert [v.id for v in active] == ["rv-1"]
    assert all(type(v) is RuleVersion for v in active)


def test_rule_version_rejects_a_non_approved_status(store):
    """RuleVersion 은 '승인된 규칙' 이다 (SPEC 2.2). 다른 상태는 아예 들어갈 수 없다."""
    from firsthome.store.errors import StoreError

    with pytest.raises(StoreError):
        store.rule_versions.add(make_rule_version("rv-x", status="pending"))

    assert store.rule_versions.active(T0) == []


# --------------------------------------------------------------------------
# 이력 연결
# --------------------------------------------------------------------------


def test_supersede_closes_the_previous_version_and_opens_the_next(store):
    store.rule_versions.add(make_rule_version("rv-1", effective_from=T0, effective_to=None))
    cutover = T0 + timedelta(days=30)

    store.rule_versions.supersede(
        "rv-1",
        make_rule_version("rv-2", effective_from=cutover, supersedes="rv-1"),
        at=cutover,
    )

    assert [v.id for v in store.rule_versions.active(cutover - timedelta(seconds=1))] == ["rv-1"]
    assert [v.id for v in store.rule_versions.active(cutover)] == ["rv-2"]
    assert store.rule_versions.get("rv-2").supersedes == "rv-1"


def test_exactly_one_version_per_policy_is_active_across_a_cutover(store):
    """겹치거나 비는 순간이 있으면 판정이 두 규칙을 동시에 보거나 아무것도 못 본다."""
    store.rule_versions.add(make_rule_version("rv-1", effective_from=None))
    cutover = T0 + timedelta(days=30)
    store.rule_versions.supersede(
        "rv-1",
        make_rule_version("rv-2", effective_from=cutover, supersedes="rv-1"),
        at=cutover,
    )

    for probe in (T0, cutover - timedelta(microseconds=1), cutover, cutover + timedelta(days=365)):
        active = [v for v in store.rule_versions.active(probe) if v.policy_id == "buttress_youth"]
        assert len(active) == 1, f"{probe} 시점에 활성 규칙이 {len(active)}개다"
