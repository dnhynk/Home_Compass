"""추출 파이프라인 테스트 — SPEC 4.1 #2·#4·#6 · 4.2.2 · 9.2.1 · 10.2 2단계.

**LLM 호출을 가짜로 주입해서 돈다.** 키가 없어도 전부 통과해야 한다 (SPEC 9.2.1) —
그것이 「LLM 호출은 파이프라인의 한 단계일 뿐」이라는 Part 0-B 주장의 증명이다.
진짜 프로바이더 호출을 검사하는 것은 이 파일의 일이 아니다.

여기서 붙드는 것은 저장소에 **무엇이 남는가**다. 검증기가 아무리 엄격해도 파이프라인이
실패한 초안을 `pending` 으로 남기면 그 초안은 사람 검토 큐에 올라가고, 결국 승인된다.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from firsthome.ingest.extraction import (
    EXTRACTION_ACTION,
    EXTRACTION_ACTOR,
    MAX_ATTEMPTS_KEY,
    extract_all,
    extract_one,
)
from firsthome.ingest.extraction_verify import RejectionCode
from firsthome.ingest.loader import load_policy_sources
from firsthome.llm.extraction import ExtractionCall, ExtractionCallFailed, ExtractionUnavailable
from firsthome.store.models import PolicySource

from extraction_fixtures import (  # noqa: E402
    FIXTURE_POLICY_ID,
    FIXTURE_SOURCE_ID,
    FIXTURE_TEXT,
    drop_span,
    span_for,
    valid_envelope,
)

KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 8, 14, 9, 0, 0, tzinfo=KST)

#: 재시도 횟수는 (d) 규범적 선택이라 **코드에 박지 않는다** (SPEC Part 0-E #4).
#: 테스트도 마찬가지다 — 여기서 박으면 계약이 바뀌어도 테스트가 눈치채지 못한다.
#: 대신 주입 매핑을 만들어 쓰고, 계약과의 일치는 `test_the_retry_count_comes_from_the_registry`
#: 가 계약 파일을 직접 읽어 확인한다.
def constants(max_attempts: int = 2) -> dict[str, object]:
    return {MAX_ATTEMPTS_KEY: max_attempts}


@pytest.fixture
def source(store) -> PolicySource:
    """픽스처 원문 1건이 적재된 저장소."""
    return store.policy_sources.add(
        PolicySource(
            id=FIXTURE_SOURCE_ID,
            text=FIXTURE_TEXT,
            source_ref="https://example.invalid/fixture",
            fetched_at=NOW,
            attribution="테스트 픽스처 「가상 제도 문서」 (픽스처) · 해당 없음",
        )
    )


def responder(*envelopes, fail_with: Exception | None = None):
    """호출될 때마다 다음 봉투를 내주는 가짜 LLM. 다 떨어지면 마지막 것을 되풀이한다."""
    calls: list[dict] = []

    def call(*, policy_id: str, text: str, schema: dict, repair=()):
        calls.append({"policy_id": policy_id, "repair": tuple(repair)})
        if fail_with is not None and len(calls) <= getattr(fail_with, "_times", 1):
            raise fail_with
        index = min(len(calls) - 1, len(envelopes) - 1)
        return ExtractionCall(
            envelope=envelopes[index],
            model="fake-model",
            latency_s=0.01,
            usage={"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        )

    call.calls = calls
    return call


# --------------------------------------------------------------------------
# 1. 성공 경로 — pending 으로 쌓인다 (SPEC 4.1 #6)
# --------------------------------------------------------------------------

def test_a_verified_extraction_is_stored_as_pending(store, source):
    outcome = extract_one(
        store, FIXTURE_SOURCE_ID, FIXTURE_POLICY_ID,
        constants=constants(), now=NOW, call=responder(valid_envelope()),
    )
    assert outcome.status == "pending"

    drafts = store.rule_drafts.list()
    assert len(drafts) == 1
    assert drafts[0].status == "pending"
    assert drafts[0].policy_id == FIXTURE_POLICY_ID
    assert drafts[0].policy_source_id == FIXTURE_SOURCE_ID
    assert drafts[0].failure_reason is None
    assert drafts[0].payload["criteria"]["ageMin"] == 19


def test_stored_spans_resolve_to_the_quoted_text(store, source):
    """★ 저장 왕복 뒤에도 4.2.1 의 등식이 성립하는가.

    검증기 안에서만 맞고 저장소에서 어긋나면 검토 화면(4.4 #1)이 엉뚱한 구간을 보여 준다.
    `resolve_span` 은 저장된 원문을 그대로 자르므로, 이 비교가 곧 왕복 검증이다.
    """
    envelope = valid_envelope()
    extract_one(
        store, FIXTURE_SOURCE_ID, FIXTURE_POLICY_ID,
        constants=constants(), now=NOW, call=responder(envelope),
    )
    draft = store.rule_drafts.list()[0]
    spans = store.rule_drafts.spans_for(draft.id)
    quoted = {s["field_path"]: s["quote"] for s in envelope["spans"]}

    assert {s.field_path for s in spans} == set(quoted)
    for span in spans:
        assert store.rule_drafts.resolve_span(span) == quoted[span.field_path]


def test_not_found_fields_get_no_span_and_that_is_not_a_failure(store, source):
    """SPEC 4.2.2 — `not_found` 는 실패가 아니다. 저장 결과로 확인한다."""
    outcome = extract_one(
        store, FIXTURE_SOURCE_ID, FIXTURE_POLICY_ID,
        constants=constants(), now=NOW, call=responder(valid_envelope()),
    )
    assert outcome.status == "pending"
    draft = store.rule_drafts.list()[0]
    assert "/criteria/assetMaxKRW" in draft.payload["not_found"]
    assert draft.payload["criteria"]["assetMaxKRW"] is None
    paths = {s.field_path for s in store.rule_drafts.spans_for(draft.id)}
    assert not [p for p in paths if p.startswith("/criteria/assetMaxKRW")]


def test_the_batch_records_an_audit_event(store, source):
    extract_one(
        store, FIXTURE_SOURCE_ID, FIXTURE_POLICY_ID,
        constants=constants(), now=NOW, call=responder(valid_envelope()),
    )
    events = store.audit.list(action=EXTRACTION_ACTION)
    assert len(events) == 1
    assert events[0].actor == EXTRACTION_ACTOR
    assert events[0].outcome == "pending"


# --------------------------------------------------------------------------
# 2. ★ 부분 저장 금지 — SPEC 4.2 · 10.2 2단계 「검증 실패 시 draft 가 생성되지 않는다」
# --------------------------------------------------------------------------

def test_a_forged_span_produces_no_pending_draft(store, source):
    """원문에 없는 인용을 심었다. **초안이 만들어지면 안 된다.**"""
    envelope = valid_envelope()
    span_for(envelope, "/criteria/ageMin")["quote"] = "만 18세 이상"  # 원문에 없다

    outcome = extract_one(
        store, FIXTURE_SOURCE_ID, FIXTURE_POLICY_ID,
        constants=constants(), now=NOW, call=responder(envelope),
    )

    assert outcome.status == "extraction_failed"
    assert RejectionCode.SPAN_NOT_IN_TEXT in outcome.codes
    assert store.rule_drafts.list(status="pending") == []


def test_a_failed_extraction_stores_no_rule_content(store, source):
    """실패 기록은 남기되 **규칙 내용은 남기지 않는다.**

    `extraction_failed` 행에 그럴듯한 payload 가 남아 있으면, 다음 사람이 그것을 열어
    「거의 맞는데」 하고 손으로 고쳐 승인 큐에 올릴 길이 열린다. 그 길을 만들지 않는다 —
    실패한 추출은 다시 돌리는 것이지 고쳐 쓰는 것이 아니다.
    """
    envelope = valid_envelope()
    envelope["draft"]["criteria"]["ageMax"] = 200  # 파수병 — 스키마가 거부한다

    extract_one(
        store, FIXTURE_SOURCE_ID, FIXTURE_POLICY_ID,
        constants=constants(), now=NOW, call=responder(envelope),
    )

    drafts = store.rule_drafts.list()
    assert len(drafts) == 1
    assert drafts[0].status == "extraction_failed"
    assert drafts[0].payload == {}
    assert store.rule_drafts.spans_for(drafts[0].id) == []


def test_the_failure_reason_names_every_code(store, source):
    """실패는 숨기지 않는다 (SPEC 4.2.2 · 7.2 추출 스키마 실패율)."""
    envelope = drop_span(valid_envelope(), "/maxAmountKRW")
    span_for(envelope, "/criteria/ageMin")["quote"] = "만 18세 이상"

    outcome = extract_one(
        store, FIXTURE_SOURCE_ID, FIXTURE_POLICY_ID,
        constants=constants(), now=NOW, call=responder(envelope),
    )

    draft = store.rule_drafts.list()[0]
    assert {RejectionCode.SPAN_MISSING, RejectionCode.SPAN_NOT_IN_TEXT} <= set(outcome.codes)
    for code in outcome.codes:
        assert code in draft.failure_reason


def test_no_span_survives_a_partially_good_extraction(store, source):
    """일곱은 맞고 하나가 틀렸다. **하나도 저장되지 않는다** (실패 단위는 draft 전체)."""
    envelope = valid_envelope()
    span_for(envelope, "/rateRangePct")["quote"] = "연 0.1%에서 0.2%로 한다"

    extract_one(
        store, FIXTURE_SOURCE_ID, FIXTURE_POLICY_ID,
        constants=constants(), now=NOW, call=responder(envelope),
    )
    draft = store.rule_drafts.list()[0]
    assert store.rule_drafts.spans_for(draft.id) == []


def test_a_failed_extraction_is_audited_too(store, source):
    envelope = valid_envelope()
    span_for(envelope, "/criteria/ageMin")["quote"] = "만 18세 이상"
    extract_one(
        store, FIXTURE_SOURCE_ID, FIXTURE_POLICY_ID,
        constants=constants(), now=NOW, call=responder(envelope),
    )
    events = store.audit.list(action=EXTRACTION_ACTION)
    assert [e.outcome for e in events] == ["extraction_failed"]


# --------------------------------------------------------------------------
# 3. 키 없이 — SPEC 9.2.1 「LLM 호출은 정상 실패」
# --------------------------------------------------------------------------

def test_without_a_key_the_call_fails_cleanly_and_stores_nothing_partial(store, source):
    """키 부재는 예외로 새어 나가지 않고 `extraction_failed` 로 **기록**된다."""
    def unavailable(**_kwargs):
        raise ExtractionUnavailable("API 키가 없다")

    outcome = extract_one(
        store, FIXTURE_SOURCE_ID, FIXTURE_POLICY_ID,
        constants=constants(), now=NOW, call=unavailable,
    )

    assert outcome.status == "extraction_failed"
    assert RejectionCode.LLM_UNAVAILABLE in outcome.codes
    assert store.rule_drafts.list(status="pending") == []
    assert store.rule_drafts.list()[0].payload == {}


def test_a_missing_key_is_not_retried(store, source):
    """키가 없는 것은 일시적 장애가 아니다. 같은 실패를 N 번 반복할 이유가 없다."""
    seen = []

    def unavailable(**_kwargs):
        seen.append(1)
        raise ExtractionUnavailable("API 키가 없다")

    outcome = extract_one(
        store, FIXTURE_SOURCE_ID, FIXTURE_POLICY_ID,
        constants=constants(max_attempts=5), now=NOW, call=unavailable,
    )
    assert len(seen) == 1
    assert outcome.attempts == 1


# --------------------------------------------------------------------------
# 4. 재시도 — SPEC 4.2.2. 횟수는 상수에서 온다
# --------------------------------------------------------------------------

def test_a_transient_failure_is_retried_and_can_succeed(store, source):
    flaky = ExtractionCallFailed("일시적 장애")
    flaky._times = 1
    call = responder(valid_envelope(), fail_with=flaky)

    outcome = extract_one(
        store, FIXTURE_SOURCE_ID, FIXTURE_POLICY_ID,
        constants=constants(max_attempts=2), now=NOW, call=call,
    )
    assert outcome.status == "pending"
    assert outcome.attempts == 2


def test_retries_are_capped_by_the_constant(store, source):
    envelope = valid_envelope()
    span_for(envelope, "/criteria/ageMin")["quote"] = "만 18세 이상"
    call = responder(envelope)

    outcome = extract_one(
        store, FIXTURE_SOURCE_ID, FIXTURE_POLICY_ID,
        constants=constants(max_attempts=3), now=NOW, call=call,
    )
    assert outcome.status == "extraction_failed"
    assert outcome.attempts == 3
    assert len(call.calls) == 3


def test_a_retry_carries_the_rejection_reasons_back_to_the_model(store, source):
    """두 번째 시도가 첫 번째와 같은 프롬프트면 같은 답이 온다. 무엇이 틀렸는지 알려준다."""
    bad = valid_envelope()
    span_for(bad, "/criteria/ageMin")["quote"] = "만 18세 이상"
    call = responder(bad, valid_envelope())

    outcome = extract_one(
        store, FIXTURE_SOURCE_ID, FIXTURE_POLICY_ID,
        constants=constants(max_attempts=2), now=NOW, call=call,
    )
    assert outcome.status == "pending"
    assert call.calls[0]["repair"] == ()
    assert any(RejectionCode.SPAN_NOT_IN_TEXT in r for r in call.calls[1]["repair"])


def test_the_retry_count_is_looked_up_fail_closed(store, source):
    """SPEC 5.1.1 — 조회 실패 시 기본값을 쓰지 않는다. 누락은 `KeyError` 로 터진다.

    기본값을 두면 계약이 아직 그 키를 등재하지 않았는데도 배치가 조용히 돌고,
    그 결과는 「정해진 횟수」가 아니라 워커가 코드에 박은 횟수로 나온 것이 된다.
    """
    with pytest.raises(KeyError) as caught:
        extract_one(
            store, FIXTURE_SOURCE_ID, FIXTURE_POLICY_ID,
            constants={}, now=NOW, call=responder(valid_envelope()),
        )
    assert MAX_ATTEMPTS_KEY in str(caught.value)
    assert store.rule_drafts.list() == []


def test_the_retry_count_key_is_the_one_the_registry_declares():
    """상수 키 이름이 계약과 어긋나면 기동은 되고 조회만 실패한다 — 가장 늦게 드러나는 종류다.

    ★ 코디네이터의 계약 PR 이 머지되기 전에는 이 테스트가 **실패한다.** 그것이 정상이다 —
      키가 등재되지 않았다는 사실이 빨간불로 보여야 한다 (fail-closed).
    """
    import json
    from pathlib import Path

    registry = json.loads(
        (Path(__file__).resolve().parents[3] / "contracts" / "model_constants.json")
        .read_text(encoding="utf-8")
    )
    assert MAX_ATTEMPTS_KEY in {entry["key"] for entry in registry["entries"]}


# --------------------------------------------------------------------------
# 5. 배치 — 적재된 원문 전수에 돈다 (SPEC 9.3 배치 작업)
# --------------------------------------------------------------------------

def test_the_batch_covers_every_loaded_source(store):
    """실제로 적재된 제도 문서 7건 위에서 돈다 — 픽스처 원문이 아니다.

    이것이 SPEC 9.2.1 마지막 줄의 실물이다: **저장된 원문**으로 후반부가 키 없이 돈다.
    """
    loaded = load_policy_sources(store, run_at=NOW)
    assert len(loaded) == 7, "적재 건수가 7 이 아니면 대장이 바뀐 것이다"

    def call(*, policy_id, text, schema, repair=()):
        # 원문에서 실제로 잘라낸 인용만 쓴다. 어떤 문서든 통과하는 최소 봉투다.
        quote = text[100:130]
        return ExtractionCall(
            envelope={
                "draft": {
                    "policy_id": policy_id,
                    "criteria": {
                        "ageMin": None, "ageMax": None, "annualIncomeMaxKRW": None,
                        "assetMaxKRW": None, "requireHomeless": None,
                        "requireNewlywed": None, "requireSME": None, "regionPrefixes": None,
                    },
                    "maxAmountKRW": None,
                    "rateRangePct": None,
                    "conditionalChecks": [],
                    "not_found": [
                        "/criteria/ageMin", "/criteria/ageMax", "/criteria/annualIncomeMaxKRW",
                        "/criteria/assetMaxKRW", "/criteria/requireHomeless",
                        "/criteria/requireNewlywed", "/criteria/requireSME",
                        "/maxAmountKRW",
                    ],
                    # regionPrefixes 하나만 「원문이 말했다」로 두어 span 이 실제로 생기게 한다
                },
                "spans": [{"field_path": "/criteria/regionPrefixes", "quote": quote},
                          {"field_path": "/rateRangePct", "quote": quote}],
            },
            model="fake-model", latency_s=0.01, usage={"total_tokens": 1},
        )

    outcomes = extract_all(store, constants=constants(), now=NOW, call=call)

    assert len(outcomes) == 7
    assert {o.status for o in outcomes} == {"pending"}
    assert len(store.rule_drafts.list(status="pending")) == 7
    for outcome in outcomes:
        expected = store.policy_sources.get(outcome.source_id).text[100:130]
        spans = store.rule_drafts.spans_for(outcome.draft_id)
        assert len(spans) == 2
        for span in spans:
            assert store.rule_drafts.resolve_span(span) == expected


def test_the_batch_does_not_stop_at_the_first_failure(store, source):
    """첫 건이 실패해도 **뒤의 건은 성공한다.** 배치가 멈추면 실패 분포를 셀 수 없다."""
    bad = valid_envelope()
    span_for(bad, "/criteria/ageMin")["quote"] = "만 18세 이상"
    second_text = FIXTURE_TEXT + "부칙 이 줄이 두 번째 문서를 구분한다.\n"
    second = store.policy_sources.add(
        PolicySource(id="src-second", text=second_text, source_ref=None,
                     fetched_at=NOW, attribution="두 번째 픽스처")
    )

    def call(*, policy_id, text, schema, repair=()):
        envelope = bad if text == FIXTURE_TEXT else valid_envelope()
        return ExtractionCall(envelope=envelope, model="fake-model", latency_s=0.01, usage={})

    outcomes = extract_all(
        store, constants=constants(max_attempts=1), now=NOW, call=call,
        targets=[(FIXTURE_SOURCE_ID, FIXTURE_POLICY_ID), (second.id, FIXTURE_POLICY_ID)],
    )
    assert [o.status for o in outcomes] == ["extraction_failed", "pending"]
    assert len(store.rule_drafts.list()) == 2
    assert len(store.rule_drafts.list(status="pending")) == 1


def test_success_is_reported_split_by_attempt(store, source):
    """성공률은 **1차 시도 / 재시도 후** 로 갈라서 낸다 (코디네이터 지시 2026-08-14).

    합치면 모델이 검증을 얼마나 자주 통과 못 하는지가 숨는다. 보고자가 손으로 나누면
    다음 사람이 합치므로, 코드가 나눠서 낸다.
    """
    from firsthome.ingest.extraction import success_breakdown

    flaky = ExtractionCallFailed("일시적 장애")
    flaky._times = 1
    bad = valid_envelope()
    span_for(bad, "/criteria/ageMin")["quote"] = "만 18세 이상"
    second = store.policy_sources.add(
        PolicySource(id="src-second", text=FIXTURE_TEXT, source_ref=None,
                     fetched_at=NOW, attribution="두 번째 픽스처")
    )
    third = store.policy_sources.add(
        PolicySource(id="src-third", text=FIXTURE_TEXT, source_ref=None,
                     fetched_at=NOW, attribution="세 번째 픽스처")
    )

    # 세 원문 모두 같은 정책을 대상으로 둔다 — 여기서 재는 것은 시도 횟수이지 정체성이 아니다.
    first_try = extract_one(
        store, FIXTURE_SOURCE_ID, FIXTURE_POLICY_ID,
        constants=constants(), now=NOW, call=responder(valid_envelope()))
    retried = extract_one(
        store, second.id, FIXTURE_POLICY_ID,
        constants=constants(), now=NOW, call=responder(valid_envelope(), fail_with=flaky))
    failed = extract_one(
        store, third.id, FIXTURE_POLICY_ID,
        constants=constants(), now=NOW, call=responder(bad))

    assert (first_try.attempts, retried.attempts) == (1, 2)
    assert success_breakdown([first_try, retried, failed]) == {
        "total": 3, "first_try_success": 1, "after_retry_success": 1, "failed": 1,
    }


def test_a_span_the_store_rejects_does_not_leave_a_pending_draft(store, source):
    """검증은 통과했는데 저장소가 span 을 거부한 경우.

    실제로는 닿지 않는 길이다 — 검증기가 이미 범위와 포인터를 봤다. 그래도 고정한다:
    닿았을 때 초안이 `pending` 으로 남으면 **근거가 절반만 붙은 초안이 사람 검토 큐에
    올라간다.** 검토자는 근거가 갖춰졌다고 가정하므로 그것이 곧 거수기다.
    """
    from firsthome.store.errors import StoreError

    class HalfWritingDrafts:
        def __init__(self, inner):
            self._inner = inner
            self.writes = 0

        def __getattr__(self, name):
            return getattr(self._inner, name)

        def add_span(self, span):
            self.writes += 1
            if self.writes == 2:
                raise StoreError("저장소가 두 번째 span 을 거부했다 (시험용)")
            return self._inner.add_span(span)

    class Wrapped:
        def __init__(self, inner):
            self._inner = inner
            self.rule_drafts = HalfWritingDrafts(inner.rule_drafts)

        def __getattr__(self, name):
            return getattr(self._inner, name)

    wrapped = Wrapped(store)
    outcome = extract_one(
        wrapped, FIXTURE_SOURCE_ID, FIXTURE_POLICY_ID,
        constants=constants(), now=NOW, call=responder(valid_envelope()),
    )

    assert outcome.status == "extraction_failed"
    assert RejectionCode.SPAN_STORE_REJECTED in outcome.codes
    assert store.rule_drafts.list(status="pending") == []
    assert store.rule_drafts.list()[0].status == "extraction_failed"


def test_drafts_never_reach_the_judgement_path(store, source):
    """SPEC 2.3 · 원칙 2 — 추출 결과는 승인 전 어떤 판정에도 참여하지 않는다.

    저장소가 그것을 구조로 보장한다. 여기서는 **추출이 그 보장을 깨지 않는지**만 본다:
    배치가 만드는 것은 `pending` 초안뿐이고 `RuleVersion` 은 하나도 늘지 않는다 (SPEC 4.6).
    """
    before = store.rule_versions.list()
    active_before = store.rule_versions.active(NOW)

    outcome = extract_one(
        store, FIXTURE_SOURCE_ID, FIXTURE_POLICY_ID,
        constants=constants(), now=NOW, call=responder(valid_envelope()),
    )

    assert outcome.status == "pending"
    assert store.rule_versions.list() == before
    assert store.rule_versions.active(NOW) == active_before
