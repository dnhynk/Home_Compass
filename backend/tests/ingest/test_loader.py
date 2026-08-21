"""적재 경로. 핵심은 첫 테스트다 — **이용조건을 확인하지 못한 문서는 들어가지 않는다.**"""

from __future__ import annotations

import unicodedata

from home_compass.ingest import load_policy_sources
from home_compass.ingest import sources as manifest


def test_sources_without_a_confirmed_licence_are_not_stored(store, run_at):
    """SPEC 잔여 실사 [확인하지 않은 채 저장·배포하지 않는다] 의 기계적 강제.

    이 테스트가 이 모듈에서 가장 중요하다. 나머지가 다 통과해도 이것이 깨지면
    저장소에 이용조건 미확인 저작물이 들어간 것이다.
    """
    load_policy_sources(store, run_at=run_at)

    stored_ids = {s.id for s in store.policy_sources.list()}
    blocked = [s for s in manifest.SOURCES if s.secured and not s.loadable]
    assert blocked, "차단 대상이 0건이면 이 테스트는 아무것도 지키지 않는다"
    for source in blocked:
        assert source.source_id not in stored_ids, source.policy_id


def test_only_the_loadable_sources_are_stored(store, run_at):
    load_policy_sources(store, run_at=run_at)

    expected = {s.source_id for s in manifest.SOURCES if s.loadable}
    assert {s.id for s in store.policy_sources.list()} == expected


def test_stored_codepoint_count_matches_the_ledger(store, run_at):
    """대장의 숫자가 **저장소에 실제로 들어간 텍스트**의 숫자와 같아야 한다.

    NFC 정규화는 저장 시 저장소가 한 번 한다 (계약 결정 #7). 정규화가 길이를 바꾸면
    여기서 갈라진다 — span 오프셋의 기준은 저장된 쪽이다.
    """
    loaded = load_policy_sources(store, run_at=run_at)
    by_id = {s.source_id: s for s in manifest.SOURCES}

    assert loaded
    for stored in loaded:
        assert len(stored.text) == by_id[stored.id].codepoints, stored.id
        assert unicodedata.is_normalized("NFC", stored.text), stored.id


def test_stored_text_round_trips_through_the_store(store, run_at):
    """조회해서 나온 텍스트가 적재한 것과 같아야 한다 — 저장 경로의 인코딩 손실 검사."""
    loaded = load_policy_sources(store, run_at=run_at)
    for stored in loaded:
        fetched = store.policy_sources.get(stored.id)
        assert fetched is not None
        assert fetched.text == stored.text
        assert fetched.source_ref == stored.source_ref


def test_reloading_is_idempotent(store, run_at):
    """같은 수집을 다시 돌려도 저장소 상태가 같아야 한다 (SPEC 3 멱등성과 같은 이유)."""
    first = load_policy_sources(store, run_at=run_at)
    before = [(s.id, s.text, s.source_ref, s.fetched_at) for s in store.policy_sources.list()]

    second = load_policy_sources(store, run_at=run_at)
    after = [(s.id, s.text, s.source_ref, s.fetched_at) for s in store.policy_sources.list()]

    assert [s.id for s in first] == [s.id for s in second]
    assert before == after


def test_fetched_at_comes_from_the_manifest_not_the_wall_clock(store, run_at):
    """취득 시각은 **기록된 수집 시각**이다. 적재를 다시 돌렸다고 신선해지지 않는다."""
    loaded = load_policy_sources(store, run_at=run_at)
    for stored in loaded:
        assert stored.fetched_at == manifest.COLLECTION_RUN_AT
        assert stored.fetched_at != run_at


def test_load_is_audited(store, run_at):
    """SPEC 7.1 — 저장소를 바꾼 배치는 흔적을 남긴다."""
    loaded = load_policy_sources(store, run_at=run_at)

    events = store.audit.list(action=manifest.INGEST_ACTION)
    assert len(events) == len(loaded)
    assert {e.target for e in events} == {s.id for s in loaded}
    for event in events:
        assert event.actor == manifest.INGEST_ACTOR
        assert event.at == run_at
        assert event.outcome == "stored"


def test_blocked_sources_are_reported_not_silently_dropped(store, run_at):
    """건너뛴 것이 조용히 사라지면 [적재 0건]과 [전부 적재]가 구분되지 않는다."""
    report = manifest.collection_report()

    assert report["policies"] == len(manifest.SOURCES)
    assert report["secured"] == manifest.SECURED_COUNT
    assert report["loaded"] == len([s for s in manifest.SOURCES if s.loadable])
    assert report["unidentified"] == len([s for s in manifest.SOURCES if not s.identified])
    assert report["retained"] == manifest.RETAINED_COUNT
    assert report["blocked_by_licence"] == len(
        [s for s in manifest.SOURCES if s.secured and not s.loadable]
    )
    assert report["secured"] == report["loaded"] + report["blocked_by_licence"]
