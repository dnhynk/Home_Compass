"""출처표시(attribution) — 계약 결정 #15 의 **유일하게 남는 의무**를 기계로 고정한다.

결정 #15 는 서울시 2건의 공공누리 제4유형 조건 넷 중 셋(상업적이용금지 · 변경금지 ·
AI유형)을 「해당 없음」으로 판단했고 **출처표시만 남겼다.** 그리고 그 의무를 문서에
적는 것으로 끝내지 말라고 못 박았다:

    「전달되는지를 테스트로 고정한다. **계보가 끊기면 의무가 문서에만 남는다**」

그래서 여기서 세 가지를 건다 —
  1. 적재되는 모든 원문이 출처표시 4요소를 갖는가
  2. 저장·조회 **왕복**에서 그것이 보존되는가 (한쪽만 통과하면 계보가 저장 경로에서 끊긴다)
  3. 출처표시 없이 적재하려 하면 **거부**되는가 (음성)

★ **자유이용 5건에도 출처표시는 필요하다.** 근거가 공공누리가 아니라 저작권법 제24조의2 일
  뿐이다. 그래서 7건 전부에 같은 형식을 쓰고, **근거 문자열로 두 갈래를 구분**한다 —
  제4유형 2건과 24조의2 5건은 지켜야 할 조건이 다르므로 나중에 조건별로 다르게 다뤄야
  할 수 있다.
"""

from __future__ import annotations

import dataclasses

import pytest

from home_compass.ingest import load_policy_sources
from home_compass.ingest import sources as manifest


def _loadable() -> list[manifest.CollectedSource]:
    return [s for s in manifest.SOURCES if s.loadable]


# --------------------------------------------------------------------------
# 1. 적재 대상 전부가 출처표시를 갖는다
# --------------------------------------------------------------------------


def test_every_loadable_source_carries_an_attribution():
    """적재되는데 출처표시가 없는 행이 하나라도 있으면 그 건은 의무를 못 지킨다."""
    sources = _loadable()
    assert sources, "적재 대상이 0건이면 이 테스트는 아무것도 지키지 않는다"
    for source in sources:
        assert source.attribution, source.policy_id


def test_attribution_carries_all_four_required_elements():
    """결정 #15 — 「기관 · 공고번호 · URL · 공공누리 유형」이 전부 들어간다.

    URL 은 `PolicySource.source_ref` 가 들고 나머지 셋은 `attribution` 이 든다.
    **한 필드에 말아 넣지 않는다** — 그러면 화면이 URL 만 뽑아낼 수 없다 (코디네이터 결정
    2026-08-14). 그래서 이 테스트는 두 필드를 **함께** 본다.
    """
    for source in _loadable():
        attribution = source.attribution
        assert attribution is not None

        # ① 기관
        assert source.authority, source.policy_id
        assert source.authority in attribution, source.policy_id

        # ② 공고번호 — 공고문이 아니면 그 자리에 문서종류가 들어간다
        qualifier = source.notice_no or manifest.DOC_KIND_LABELS[source.doc_kind]
        assert qualifier in attribution, source.policy_id

        # ③ URL — 계보의 다른 한 필드다
        assert source.url, source.policy_id

        # ④ 이용근거 (공공누리 유형 또는 저작권법 조문)
        assert source.licence_basis, source.policy_id
        assert source.licence_basis in attribution, source.policy_id


def test_notices_are_attributed_with_their_notice_number():
    """공고문인데 공고번호가 없으면 4요소 중 하나가 문서종류로 대체돼 버린다.

    공고번호는 **원문 첫 줄의 표기 그대로** 적는다. ⑧ 의 번호는 붙임표가 아니라
    EN DASH(U+2013) 인데, 출처표시는 원문이 쓴 이름을 인용하는 것이므로 고쳐 쓰지 않는다.
    """
    notices = [s for s in _loadable() if s.doc_kind == "notice"]
    assert notices, "적재된 공고문이 0건이면 이 테스트는 아무것도 지키지 않는다"
    for source in notices:
        assert source.notice_no, source.policy_id
        assert source.notice_no in (source.attribution or ""), source.policy_id


# --------------------------------------------------------------------------
# 2. 두 갈래가 계보에서 구분된다
# --------------------------------------------------------------------------


def test_the_licence_basis_separates_kogl_type_4_from_the_copyright_act():
    """제4유형 2건과 저작권법 24조의2 5건은 **지켜야 할 조건이 다르다.**

    출처표시 형식은 7건 공통이지만, 형식이 같다고 조건까지 같아지면 안 된다.
    나중에 조건별로 다르게 다뤄야 할 때 계보만 보고 갈래를 나눌 수 있어야 한다.
    """
    by_basis: dict[str, set[str]] = {}
    for source in _loadable():
        by_basis.setdefault(source.licence_basis or "", set()).add(source.policy_id)

    assert by_basis == {
        manifest.LICENCE_BASIS_KOGL_TYPE_4: {"seoul_youth_rent", "seoul_deposit_interest"},
        manifest.LICENCE_BASIS_COPYRIGHT_ACT: {
            "buttress_youth",
            "youth_monthly_loan",
            "newlywed_jeonse",
            "housing_dream_savings",
            "hug_deposit_guarantee",
        },
    }


def test_the_licence_basis_is_not_the_ledger_display_string():
    """`kogl_type` 은 **대장 표기용**이라 마크다운 강조(`**`)가 섞여 있다.

    화면이 그대로 인용하는 문자열에 그것이 새어 나가면 안 되므로 인용되는 값은
    `licence_basis` 에만 둔다. 두 칸을 하나로 합치면 이 구분이 사라진다.
    """
    for source in _loadable():
        assert "*" not in (source.licence_basis or ""), source.policy_id
        assert "*" not in (source.attribution or ""), source.policy_id


# --------------------------------------------------------------------------
# 3. 저장·조회 왕복에서 보존된다
# --------------------------------------------------------------------------


def test_attribution_survives_the_store_round_trip(store, run_at):
    """★ 결정 #15 의 핵심. **계보가 끊기면 의무가 문서에만 남는다.**

    `add()` 의 반환값만 보면 저장 경로를 통과했는지 알 수 없다 — 저장소가 값을 버려도
    반환값에는 남을 수 있다. 그래서 **다시 조회해서** 대조한다.
    """
    loaded = load_policy_sources(store, run_at=run_at)
    by_id = {s.source_id: s for s in manifest.SOURCES}
    assert loaded

    for stored in loaded:
        fetched = store.policy_sources.get(stored.id)
        assert fetched is not None, stored.id
        assert fetched.attribution == by_id[stored.id].attribution, stored.id
        assert fetched.attribution, stored.id
        # URL 은 다른 한 필드다. 둘이 함께 있어야 4요소가 성립한다.
        assert fetched.source_ref == by_id[stored.id].url, stored.id


def test_every_stored_source_is_attributed_after_a_list_query(store, run_at):
    """`list()` 경로도 같은 보장을 준다. `get()` 만 통과하면 목록 화면에서 계보가 끊긴다."""
    load_policy_sources(store, run_at=run_at)
    listed = store.policy_sources.list()

    assert len(listed) == len(_loadable())
    for stored in listed:
        assert stored.attribution, stored.id
        assert stored.source_ref, stored.id


# --------------------------------------------------------------------------
# 4. 음성 — 출처표시 없이는 적재되지 않는다
# --------------------------------------------------------------------------


def test_loading_a_source_without_an_attribution_is_refused(store, run_at):
    """★ 음성 테스트. 출처표시가 비면 **적재 자체가 거부**된다.

    조용히 `None` 으로 넣으면 저장소에는 들어가고 의무만 사라진다 — 그것이
    「계보가 끊긴다」의 실제 모습이다. 여기서는 이용조건 게이트를 통과한
    (`loadable == True`) 행에서 출처표시만 지운다. 게이트에 걸려서가 아니라
    **출처표시가 없어서** 거부되는지를 봐야 하기 때문이다.
    """
    victim = next(s for s in manifest.SOURCES if s.loadable)
    unattributed = dataclasses.replace(victim, authority=None)

    assert unattributed.loadable, "이용조건 게이트에 걸려 버리면 이 테스트가 다른 것을 재고 있다"
    assert unattributed.attribution is None

    with pytest.raises(ValueError, match="출처표시"):
        load_policy_sources(store, run_at=run_at, only=(unattributed,))

    assert store.policy_sources.list() == [], "거부됐는데 저장소에 들어갔다"


def test_a_missing_licence_basis_also_removes_the_attribution(store, run_at):
    """이용근거가 비어도 출처표시가 성립하지 않는다 — 4요소 중 하나가 빠진 것이다."""
    victim = next(s for s in manifest.SOURCES if s.loadable)
    unattributed = dataclasses.replace(victim, licence_basis=None)

    assert unattributed.attribution is None
    with pytest.raises(ValueError, match="출처표시"):
        load_policy_sources(store, run_at=run_at, only=(unattributed,))


# --------------------------------------------------------------------------
# 5. 적재 대상이 5건 -> 7건이 됐다
# --------------------------------------------------------------------------


def test_the_seoul_notices_are_now_loaded(store, run_at):
    """결정 #15 로 열린 문. ⑥⑧ 이 실제로 저장소에 들어간다."""
    load_policy_sources(store, run_at=run_at)
    stored_ids = {s.id for s in store.policy_sources.list()}

    assert len(stored_ids) == 7
    for policy_id in ("seoul_youth_rent", "seoul_deposit_interest"):
        assert f"src-{policy_id}" in stored_ids


def test_bokjiro_stays_out():
    """⑤ 복지로는 여전히 **확인 실패**다. 결정 #15 는 그 건을 열지 않았다."""
    bokjiro = next(s for s in manifest.SOURCES if s.policy_id == "youth_rent_support")

    assert bokjiro.licence == manifest.LICENCE_UNCONFIRMED
    assert not bokjiro.loadable
    assert bokjiro.text_file is None
    assert not (manifest.text_dir() / "youth_rent_support.txt").exists()
