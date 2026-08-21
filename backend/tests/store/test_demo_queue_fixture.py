"""굳힌 시연 대기 큐 (계약 결정 #42 — #40 의 연장).

**이 파일이 붙드는 것은 초안의 존재가 아니라 계보다.** 초안을 만드는 것은 쉽고,
「어떤 모델로 · 언제 · 어떤 원문에서 뽑혔는지」를 남기는 것이 어렵다. 직전 시연이 기준
상태로 쓰던 `rehearsal-baseline.db` 는 유실된 세션이 만든 파일이라 그 셋을 아무도 몰랐고
(REHEARSAL.md Part 5-⑤), 계보가 이 제품의 논지인데 시연의 중심 산출물이 계보 불명이었다.
그 상태로 되돌아가지 못하게 하는 것이 아래 단정들이다.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest
from conftest import T0

from home_compass.store.errors import StoreError
from home_compass.store.provenance import validate_provenance_dict
from home_compass.store.seed import (
    DEMO_QUEUE_ACTION,
    REPO_ROOT,
    load_demo_queue,
    seed_all,
    seed_demo_queue,
)

FIXTURE = load_demo_queue()
RUN = FIXTURE["extractionRun"]
DRAFTS = FIXTURE["drafts"]
SOURCES = FIXTURE["policySources"]


def _seed_events(store):
    return [e for e in store.audit.list() if e.action == DEMO_QUEUE_ACTION]


# --------------------------------------------------------------------------
# 큐가 실제로 선다 — 이 과업의 출발점
# --------------------------------------------------------------------------


def test_the_queue_is_not_empty_after_seeding(store):
    """핵심 시연 장면에는 **승인할 초안이 큐에 있어야** 한다.

    이 단정이 깨지는 상태가 결정 #42 를 부른 그 상태다 — 클론 후 시드만 돌리면 큐가
    비어 있고, 승인 → 시민 화면 변화를 보일 수 없다.
    """
    seed_demo_queue(store, at=T0)
    assert store.rule_drafts.list(status="pending"), "대기 큐가 비었다"


def test_the_seeded_counts_are_what_the_frozen_run_produced(store):
    """숫자를 여기 박지 않는다 — 픽스처가 적어 둔 그 배치의 결과와 대조한다."""
    seed_demo_queue(store, at=T0)
    assert len(store.rule_drafts.list(status="pending")) == RUN["pending"]
    assert len(store.rule_drafts.list(status="extraction_failed")) == RUN["extractionFailed"]
    assert len(store.policy_sources.list()) == len(SOURCES)


def test_failed_drafts_are_seeded_too_and_carry_their_reason(store):
    """★ **통과한 것만 고르지 않는다.**

    실패를 빼면 큐가 「추출은 늘 성공한다」고 말하게 되고, 그것은 SPEC 4.2 가 세운 주장
    (부분 저장 금지 · 실패를 숨기지 않는다)의 정반대다. 실패한 초안은 규칙 내용이 비어
    있고 사유를 들고 있으며, 승인 대상이 아니다.
    """
    seed_demo_queue(store, at=T0)
    failed = store.rule_drafts.list(status="extraction_failed")
    assert failed, "실패한 초안이 하나도 시드되지 않았다"
    for draft in failed:
        assert draft.payload == {}, draft.id
        assert draft.failure_reason, draft.id
        assert store.rule_drafts.spans_for(draft.id) == []


# --------------------------------------------------------------------------
# 계보 — 이 과업의 본체
# --------------------------------------------------------------------------


def test_every_draft_records_which_model_extracted_it(store):
    """★ 「어떤 모델로」. 이것이 없으면 이 과업은 실패한 것이다.

    `RuleDraft` 에는 계보 칸이 없으므로(SPEC 2.2) 남을 자리는 감사기록이다.
    파일에만 적으면 **돌아가는 시스템에게 물어볼 수 없고**, 그 상태가 곧
    `rehearsal-baseline.db` 가 계보 불명이 된 경위다.
    """
    seed_demo_queue(store, at=T0)
    events = _seed_events(store)
    assert len(events) == len(DRAFTS)

    # 기록되는 것은 **프로바이더가 답한 이름**이지 우리가 요청한 별칭이 아니다.
    # (굳힐 때 관측된 값: 요청 `gpt-5.4-mini` -> 응답 `gpt-5.4-mini-2026-03-17`.
    #  별칭만 적으면 어느 판이 뽑았는지가 사라진다. 그 형태를 여기서 단정하지는 않는다 —
    #  이름 짓는 규칙은 프로바이더의 것이고, 그것을 붙들면 무관한 이유로 빨간불이 난다.)
    for event in events:
        model = event.after["extraction"]["model"]
        assert model, f"{event.target} 에 모델이 적혀 있지 않다"
        # 한 배치의 산출물이므로 전 건이 같은 모델이어야 한다. 갈리면 굳힌 것이 한 회차가
        # 아니라 여러 회차를 기운 것이고, 그때 `extractionRun` 은 거짓을 말한다.
        assert model == RUN["modelReported"], event.target


def test_every_draft_records_when_it_was_extracted(store):
    """★ 「언제」. 시드를 돌린 시각이 아니라 **추출이 일어난 시각**이다.

    시드 시각을 적으면 시연할 때마다 초안이 방금 뽑힌 것처럼 보인다. 결정 #40 이 시세에
    대해 못박은 것과 같다 — 시연일과 벌어지는 것이 정상이고 계보가 그것을 드러낸다.
    """
    seed_at = T0 + timedelta(days=365)
    seed_demo_queue(store, at=seed_at)

    started = datetime.fromisoformat(RUN["startedAt"])
    finished = datetime.fromisoformat(RUN["finishedAt"])
    for draft in store.rule_drafts.list():
        assert draft.created_at != seed_at, f"{draft.id} 가 시드 시각을 달고 있다"
        assert started <= draft.created_at <= finished, (
            f"{draft.id} 의 추출 시각이 그 배치의 창 밖이다: {draft.created_at.isoformat()}"
        )


def test_every_draft_records_which_source_text_it_came_from(store):
    """★ 「어떤 원문에서」. id 만으로는 부족하다 — **그 파일이 그 파일인지**까지 붙든다."""
    seed_demo_queue(store, at=T0)
    for event in _seed_events(store):
        source_id = event.after["policySourceId"]
        assert store.policy_sources.get(source_id) is not None, source_id
    declared = {s["id"] for s in SOURCES}
    assert {s.id for s in store.policy_sources.list()} == declared


def test_the_recorded_lineage_satisfies_the_provenance_contract(store):
    """SPEC 2.1 을 **말로만** 만족시키지 않는다 — 계약 스키마에 직접 통과시킨다."""
    seed_demo_queue(store, at=T0)
    for event in _seed_events(store):
        provenance = event.after["provenance"]
        validate_provenance_dict(provenance)
        assert provenance["source_kind"] == "statute"
        assert provenance["fetched_at"], event.target
        # 제도 문서는 공표 기준시점을 밝히지 않는다. 기준시점 없이 `verified` 를 적는 것이
        # Part 0-C 가 「심사에서 즉시 반박당한다」고 경고한 그것이다 (main.py 승인 경로와 같은 판단).
        assert provenance["observed_at"] is None
        assert provenance["verification"] == "unverified"


def test_the_frozen_run_discloses_the_repeats_it_was_chosen_from(store):
    """★ 한 회차를 굳혔다는 사실 자체가 계보다.

    3회를 돌려 놓고 그중 하나를 굳혔다는 것을 적지 않으면, 남은 사람은 이 결과가 유일한
    관측이라고 읽는다. 그리고 **굳힌 회차가 첫 회차여야 한다** — 「원하는 결과가 나온
    회차」를 고르는 순간 이 픽스처가 사려던 정직성이 사라진다.
    """
    repeats = RUN["repeatedRuns"]
    assert len(repeats) >= 2, "반복 관측이 기록되지 않았다"
    frozen = [r for r in repeats if r["frozen"]]
    assert len(frozen) == 1
    assert frozen[0]["startedAt"] == RUN["startedAt"]
    assert frozen[0]["startedAt"] == min(r["startedAt"] for r in repeats), (
        "첫 회차가 아닌 회차를 굳혔다 — 결과를 보고 고른 것이 아닌지 PR 본문에 적어라"
    )


# --------------------------------------------------------------------------
# 근거 — span 이 실제로 원문을 가리키는가 (SPEC 4.2.1 · 4.4 #1)
# --------------------------------------------------------------------------


def test_spans_resolve_to_the_quotes_the_run_recorded(store):
    """굳힌 오프셋이 굳힌 인용과 한 글자도 다르지 않아야 한다.

    어긋나면 검토 화면(SPEC 4.4 #1)이 **다른 조항을 근거로 보여 준다.** 승인자는 그것을
    읽고 승인하므로, 여기서 어긋나면 사람 게이트가 거수기가 된다.
    """
    seed_demo_queue(store, at=T0)
    checked = 0
    for entry in DRAFTS:
        stored = {s.field_path: s for s in store.rule_drafts.spans_for(entry["id"])}
        assert len(stored) == len(entry["spans"]), entry["id"]
        for span in entry["spans"]:
            resolved = store.rule_drafts.resolve_span(stored[span["fieldPath"]])
            assert resolved == span["quote"], f"{entry['id']} {span['fieldPath']}"
            checked += 1
    assert checked, "대조한 span 이 하나도 없다"


def test_a_changed_source_text_stops_the_seed_instead_of_shifting_the_spans(store, monkeypatch):
    """★ 원문이 바뀌면 **터진다.**

    조용히 넘어가면 span 이 가리키는 자리가 다른 글자가 되고, 화면은 그것을 근거라고
    보여 준다. 계보가 거짓이 되는 자리는 언제나 「조용히 넘어간 자리」다.
    """
    import home_compass.store.seed as seed_module

    tampered = json.loads(json.dumps(FIXTURE))
    tampered["policySources"][0]["sha256Nfc"] = "0" * 64
    monkeypatch.setattr(seed_module, "load_demo_queue", lambda: tampered)

    with pytest.raises(StoreError) as exc:
        seed_demo_queue(store, at=T0)
    assert "원문이 굳힐 때와 다르다" in str(exc.value)


def test_the_fixture_points_at_the_canonical_text_and_does_not_copy_it():
    """텍스트 정본은 `data/policy_sources/*.txt` 하나뿐이다.

    픽스처가 사본을 들면 span 오프셋이 어느 텍스트 기준인지가 둘로 갈리고, 갈린 뒤에는
    어느 쪽이 근거인지 아무도 모른다. 그래서 여기는 **경로와 해시만** 든다.
    """
    for entry in SOURCES:
        assert "text" not in entry, f"{entry['id']} 가 원문 사본을 들고 있다"
        assert (REPO_ROOT / entry["textFile"]).is_file(), entry["textFile"]


# --------------------------------------------------------------------------
# 시드로서의 성질
# --------------------------------------------------------------------------


def test_the_demo_queue_is_off_unless_asked_for(store):
    """기동에 필요한 것과 시연에 필요한 것은 다르다.

    켜 두면 `seed_all` 을 부르는 모든 시험이 초안을 안고 시작하고, 빈 큐를 전제한 단정이
    **무관한 이유로** 깨진다. 켜는 것은 시연 저장소를 만드는 쪽의 선택이다.
    """
    seed_all(store, at=T0)
    assert store.rule_drafts.list() == []
    assert store.policy_sources.list() == []


def test_seed_all_can_stand_the_queue_up(store):
    counts = seed_all(store, at=T0, demo_queue=True)
    assert counts["rule_drafts"] == len(DRAFTS)
    assert counts["policy_sources"] == len(SOURCES)


def test_seeding_twice_changes_nothing(store):
    """시연 중 스크립트를 두 번 돌리는 일은 반드시 일어난다.

    `RuleDraft.add` 는 upsert 가 아니므로 재시드가 그대로 터진다. 그리고 같은 초안을 다시
    만들면 그것은 「다시 일어난 추출」인 척하는 것이 된다 — 재추출은 새 행이어야 한다.
    """
    seed_demo_queue(store, at=T0)
    before = (
        sorted((d.id, d.status, d.created_at) for d in store.rule_drafts.list()),
        len(store.audit.list()),
    )

    seed_demo_queue(store, at=T0 + timedelta(days=1))

    after = (
        sorted((d.id, d.status, d.created_at) for d in store.rule_drafts.list()),
        len(store.audit.list()),
    )
    assert before == after


def test_a_pending_draft_still_cannot_reach_a_decision(store):
    """SPEC 2.3 — 큐를 채운 것이 판정을 바꾸지 않는다.

    이 과업이 건드린 것은 **검토 큐**이지 판정 입력이 아니다. 둘이 섞이면 승인 없이 규칙이
    바뀌는 길이 생기고, 그러면 시연의 논지 자체가 무너진다.
    """
    seed_all(store, at=T0)
    before = [v.id for v in store.rule_versions.active(T0)]

    seed_demo_queue(store, at=T0)
    assert [v.id for v in store.rule_versions.active(T0)] == before
    assert all(v.origin == "seed" for v in store.rule_versions.list())
