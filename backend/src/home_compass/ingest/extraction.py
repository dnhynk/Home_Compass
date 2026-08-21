"""추출 파이프라인 — SPEC 4.1 의 2·3·4·6 단계. **본선의 기술적 중심.**

    2. 추출      LLM. 입력=저장된 원문 -> 출력=RuleDraft (JSON Schema 강제)
    3. 근거 매핑  각 필드마다 원문 span
    4. 자동 검증  스키마 · span 실재 · 필수 필드 · 값 범위
    6. 대기 큐    pending

**올바른 비유는 에이전트가 아니라 컴파일러다** (Part 0-B). 이 모듈은 결정적 파이프라인이고
LLM 호출은 그 안의 한 단계다. 그래서 이 모듈은 호출 함수를 **인자로 받는다** (`call`) —
키 없는 환경에서 픽스처를 주입해 후반부 전체를 돌릴 수 있어야 하기 때문이다 (SPEC 9.2.1).

## 저장 규율 — 셋을 지킨다

  **부분 저장 금지** (SPEC 4.2). 검증을 통과하지 못하면 규칙 내용을 저장하지 않는다.
      실패는 `extraction_failed` **한 행으로** 기록되고 `payload` 는 비어 있다.
      실패 사유는 `failure_reason` 에 코드와 함께 남는다 — 실패를 숨기지 않는다.

  **실패 단위는 draft 전체** (SPEC 4.2.2). span 하나가 어긋나면 나머지 일곱도 저장되지
      않는다. 필드 단위 부분 저장은 부분 저장 금지와 직접 충돌한다.

  **pending 만 만든다** (SPEC 4.6). 배치는 승인된 `RuleVersion` 을 건드리지 않는다.
      승인 흐름은 이 모듈의 일이 아니다.

## `extraction_failed` 를 왜 한 행으로 남기는가

SPEC 4.2 는 「draft 를 만들지 않고 `extraction_failed` 로 기록한다」고 적었다. 기록할 자리는
`RuleDraft` 뿐이다 — `DRAFT_STATUSES` 에 `extraction_failed` 가 있고 `failure_reason` 칸이
있는 것이 그 설계다 (SPEC 2.2 · 4.2.2 「소진되면 `extraction_failed` 로 기록하고 사람 큐로
올린다」). 따라서 「만들지 않는다」의 대상은 **검토 큐에 오르는 초안**(`pending`)이고,
실패 행은 그 큐에 오르지 않는다.

`payload` 를 비워 두는 것은 그보다 한 걸음 더 나간 선택이다. 거부된 규칙 내용을 남겨 두면
다음 사람이 그것을 열어 「거의 맞는데」 하고 손으로 고쳐 승인 큐에 올릴 길이 생긴다.
그 길을 만들지 않는다 — 실패한 추출은 **다시 돌리는 것**이지 고쳐 쓰는 것이 아니다.
진단에 필요한 것은 규칙 내용이 아니라 **무엇이 왜 틀렸는가**이고, 그것은 사유에 남는다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Mapping, Sequence

from ..llm.extraction import (
    ExtractionCall,
    ExtractionCallFailed,
    ExtractionUnavailable,
    call_extraction,
)
from ..store.errors import StoreError
from ..store.interfaces import Store
from ..store.models import AuditEvent, RuleDraft, RuleSpanMapping
from .extraction_verify import (
    ExtractionRejected,
    Rejection,
    RejectionCode,
    VerifiedExtraction,
    rule_draft_schema,
)
from .sources import loadable_sources

#: 무엇이 저장소를 바꿨는지가 감사로그에 드러난다 (`system:seed` · `system:ingest` 와 같은 자리).
EXTRACTION_ACTOR = "system:extract"
EXTRACTION_ACTION = "rule_draft.extract"

#: ★ 재시도 횟수는 (d) 규범적 선택이므로 `ModelConstant` 에서 온다
#: (SPEC 4.2.2 · Part 0-E #4, 코디네이터 확정 2026-08-14).
#: **코드에 숫자를 박지 않는다.** 박으면 SPEC 이 「정해진 횟수」라고 부른 것이
#: 워커가 감으로 고른 횟수가 된다.
MAX_ATTEMPTS_KEY = "extraction.max_attempts"


@dataclass(frozen=True)
class ExtractionOutcome:
    """한 건의 결과. **실측치를 함께 들고 있다** (SPEC 8.3 이 2단계에 남긴 측정)."""

    policy_id: str
    source_id: str
    draft_id: str
    status: str
    codes: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    attempts: int = 0
    latency_s: float = 0.0
    span_count: int = 0
    model: str | None = None
    usage: dict[str, int] = field(default_factory=dict)

    #: ★ **시도마다의 거부 사유**. 마지막 시도만 남기면 재시도로 건진 건의 1차 실패
    #: 사유가 사라진다 — 그것이 바로 「모델이 검증을 얼마나 자주 통과 못 하는가」이며
    #: SPEC 4.2.2 가 재려는 값이다. 실측에서 이 구멍을 발견해 채웠다.
    #: 성공한 시도는 빈 튜플이다.
    attempt_codes: tuple[tuple[str, ...], ...] = ()

    #: 인용이 원문에 **2회 이상** 나타난 span 의 수 (코디네이터 지시 2026-08-14).
    #: 실패가 아니다 — 「문자열은 실재하지만 어느 조항인지는 확정되지 않았다」는 뜻이며,
    #: 5단계 대조 표시(SPEC 4.4 #1)의 선결 과제다. 조용히 넘기지 않으려고 세어서 낸다.
    ambiguous_spans: int = 0

    @property
    def ok(self) -> bool:
        return self.status == "pending"

    @property
    def first_attempt_codes(self) -> tuple[str, ...]:
        return self.attempt_codes[0] if self.attempt_codes else ()


#: 호출 규약. 진짜 프로바이더도, 픽스처도 이 모양이다.
CallFn = Callable[..., ExtractionCall]


def extract_one(
    store: Store,
    source_id: str,
    policy_id: str,
    *,
    constants: Mapping[str, Any],
    now: datetime,
    call: CallFn = call_extraction,
    call_options: Mapping[str, Any] | None = None,
) -> ExtractionOutcome:
    """저장된 원문 하나에서 초안 하나를 만든다. **예외를 밖으로 내지 않는다.**

    LLM 실패든 검증 실패든 `extraction_failed` 로 **기록**하고 돌아온다 (SPEC 9.2.1).
    배치가 한 건 때문에 멈추면 실패 분포를 셀 수 없다 (SPEC 7.2).

    다만 **두 경우는 예외로 터진다** — 상수 부재(`KeyError`)와 원문 부재. 둘은
    「이 문서를 추출하지 못했다」가 아니라 **배치를 돌릴 조건이 안 됐다**는 뜻이므로,
    실패 건수에 섞으면 성공률이 조용히 나빠 보인다.
    """
    # ★ fail-closed (SPEC 5.1.1). `constants.get(key, 2)` 를 쓰지 않는다 — 기본값을 두면
    #   계약이 그 키를 등재하기 전에도 배치가 조용히 돌고, 그 결과는 「정해진 횟수」가
    #   아니라 이 파일에 박힌 횟수로 나온 것이 된다.
    #   ★★ 어떤 저장소 쓰기보다 **먼저** 조회한다. 뒤에 두면 실패한 배치가 흔적을 남긴다.
    max_attempts = int(constants[MAX_ATTEMPTS_KEY])
    if max_attempts < 1:
        raise ValueError(f"{MAX_ATTEMPTS_KEY} 는 1 이상이어야 한다: {max_attempts}")

    source = store.policy_sources.get(source_id)
    if source is None:
        raise StoreError(
            f"원문이 적재되지 않았다: {source_id} — 먼저 `python -m home_compass.ingest` 를 돌려라"
        )

    # ★ 대상 텍스트는 **저장소에 저장된 NFC 정규화 텍스트**다 (SPEC 4.2.1).
    #   파일을 다시 읽는 경로를 만들지 않는다 — 파서·읽기 방식이 바뀌면 오프셋이 어긋난다.
    text = source.text
    schema = rule_draft_schema()
    options = dict(call_options or {})

    repair: tuple[str, ...] = ()
    rejections: list[Rejection] = []
    attempt_codes: list[tuple[str, ...]] = []
    verified: VerifiedExtraction | None = None
    attempts = 0
    latency = 0.0
    usage: dict[str, int] = {}
    model: str | None = None

    for attempt in range(1, max_attempts + 1):
        attempts = attempt
        try:
            result = call(
                policy_id=policy_id, text=text, schema=schema, repair=repair, **options
            )
        except ExtractionUnavailable as exc:
            # 키·SDK 부재는 일시적 장애가 아니다. 되풀이하지 않는다 (SPEC 9.2.1).
            rejections = [Rejection(RejectionCode.LLM_UNAVAILABLE, str(exc))]
            attempt_codes.append((RejectionCode.LLM_UNAVAILABLE,))
            break
        except ExtractionCallFailed as exc:
            rejections = [Rejection(RejectionCode.LLM_CALL_FAILED, str(exc))]
            attempt_codes.append((RejectionCode.LLM_CALL_FAILED,))
            repair = tuple(str(r) for r in rejections)
            continue

        latency += result.latency_s
        model = result.model
        for key, value in (result.usage or {}).items():
            usage[key] = usage.get(key, 0) + value

        try:
            verified = _verified(result, policy_id=policy_id, text=text)
        except ExtractionRejected as exc:
            rejections = list(exc.rejections)
            attempt_codes.append(exc.codes)
            # 같은 프롬프트를 다시 보내면 같은 답이 온다. 무엇이 틀렸는지 알려준다.
            repair = tuple(str(r) for r in exc.rejections)
            continue

        rejections = []
        attempt_codes.append(())
        break

    common = {
        "policy_id": policy_id,
        "source_id": source_id,
        "attempts": attempts,
        "latency_s": latency,
        "usage": usage,
        "model": model,
        "attempt_codes": tuple(attempt_codes),
    }

    if verified is None:
        return _store_failure(store, rejections, now=now, **common)
    return _store_success(store, verified, now=now, **common)


def _verified(
    result: ExtractionCall, *, policy_id: str, text: str
) -> VerifiedExtraction:
    """검증기를 부른다. **이 모듈 안에서 검증을 다시 구현하지 않는다.**

    한 줄짜리 우회처럼 보이지만 경계를 지키는 일이다 — 검증 규칙이 두 곳에 생기면
    한쪽만 느슨해지고, 느슨한 쪽이 이긴다.
    """
    from .extraction_verify import verify

    return verify(result.envelope, policy_id=policy_id, text=text)


# --------------------------------------------------------------------------
# 저장
# --------------------------------------------------------------------------

def _draft_id(store: Store, policy_id: str) -> str:
    """실행마다 늘어나는 번호를 붙인다.

    같은 원문을 다시 추출하면 **새 행**이 생긴다. 덮어쓰지 않는 이유는 재추출이
    「같은 초안의 갱신」이 아니라 **다시 일어난 사건**이기 때문이다 — 앞 초안이 왜
    실패했는지가 지워지면 4.2.2 의 실패율을 사후에 셀 수 없다.
    """
    return f"draft-{len(store.rule_drafts.list()) + 1:06d}-{policy_id}"


def _audit(
    store: Store,
    *,
    now: datetime,
    draft_id: str,
    policy_id: str,
    source_id: str,
    outcome: str,
    after: dict[str, Any],
) -> None:
    store.audit.append(
        AuditEvent(
            id=f"audit-{len(store.audit.list()) + 1:06d}-{EXTRACTION_ACTION}-{policy_id}",
            actor=EXTRACTION_ACTOR,
            at=now,
            action=EXTRACTION_ACTION,
            target=draft_id,
            outcome=outcome,
            after={"policy_id": policy_id, "policy_source_id": source_id, **after},
        )
    )


def _store_success(
    store: Store,
    verified: VerifiedExtraction,
    *,
    now: datetime,
    policy_id: str,
    source_id: str,
    attempts: int,
    latency_s: float,
    usage: dict[str, int],
    model: str | None,
    attempt_codes: tuple[tuple[str, ...], ...],
) -> ExtractionOutcome:
    draft_id = _draft_id(store, policy_id)
    store.rule_drafts.add(
        RuleDraft(
            id=draft_id,
            policy_source_id=source_id,
            policy_id=policy_id,
            # ★ SPEC 4.1 #6 — 추출 결과는 **pending** 으로 쌓인다. 승인 전에는 어떤
            #   판정에도 참여하지 않는다 (SPEC 2.3 · 원칙 2).
            status="pending",
            payload=verified.draft,
            created_at=now,
        )
    )

    try:
        for index, span in enumerate(verified.spans, start=1):
            store.rule_drafts.add_span(
                RuleSpanMapping(
                    id=f"{draft_id}-span-{index:02d}",
                    draft_id=draft_id,
                    field_path=span.field_path,
                    start=span.start,
                    end=span.end,
                )
            )
    except StoreError as exc:
        # 검증을 통과했는데 저장소가 거부했다. `validate_span` 이 보는 것(범위·포인터)은
        # 검증기가 이미 봤으므로 실제로는 닿지 않는 길이다. 그래도 남겨 둔다 —
        # 닿았을 때 `pending` 으로 남는 것이 최악이기 때문이다. 사람 검토 큐에 올라간
        # 초안은 근거가 갖춰졌다고 가정되므로, 절반만 붙은 근거는 거수기를 만든다.
        #
        # ⚠️ 이미 들어간 span 행은 남는다. `store` 에 span 삭제나 교차 저장소 트랜잭션이
        #    없기 때문이다. 초안이 `extraction_failed` 라 검토 큐에는 오르지 않지만
        #    완전한 원복은 아니다 — 저장소 계층 변경이 필요하므로 코디네이터에게 올린다.
        reasons = (str(Rejection(RejectionCode.SPAN_STORE_REJECTED, str(exc))),)
        store.rule_drafts.set_status(
            draft_id, "extraction_failed", failure_reason=" / ".join(reasons)
        )
        _audit(
            store, now=now, draft_id=draft_id, policy_id=policy_id, source_id=source_id,
            outcome="extraction_failed",
            after={"codes": [RejectionCode.SPAN_STORE_REJECTED], "attempts": attempts,
                   "latency_s": round(latency_s, 3)},
        )
        return ExtractionOutcome(
            policy_id=policy_id, source_id=source_id, draft_id=draft_id,
            status="extraction_failed", codes=(RejectionCode.SPAN_STORE_REJECTED,),
            reasons=reasons, attempts=attempts, latency_s=latency_s,
            span_count=0, model=model, usage=usage, attempt_codes=attempt_codes,
        )

    _audit(
        store, now=now, draft_id=draft_id, policy_id=policy_id, source_id=source_id,
        outcome="pending",
        after={
            "spans": len(verified.spans),
            "not_found": list(verified.draft["not_found"]),
            "attempts": attempts,
            # SPEC 7.2 「LLM 호출 성공률과 **지연**」. 지금까지 `ExtractionOutcome` 에만
            # 있어 배치 프로세스가 끝나면 사라졌다 — 상태 화면이 읽을 수 있는 곳은
            # 저장소뿐이라 여기 함께 남긴다. **내용은 남기지 않는다** (SPEC 7.1).
            "latency_s": round(latency_s, 3),
            # 재시도로 건진 건은 1차 시도가 왜 거부됐는지가 여기 남는다.
            "attempt_codes": [list(c) for c in attempt_codes],
            # 인용이 원문에 여러 번 나타난 근거. 5단계 대조 표시가 어느 조항을 보여야
            # 하는지가 확정되지 않은 자리이며, 감사기록에 남겨 두어야 나중에 찾을 수 있다.
            "ambiguous_spans": [
                {"field_path": s.field_path, "occurrences": s.occurrences}
                for s in verified.spans if s.ambiguous
            ],
        },
    )
    return ExtractionOutcome(
        policy_id=policy_id, source_id=source_id, draft_id=draft_id, status="pending",
        attempts=attempts, latency_s=latency_s, span_count=len(verified.spans),
        model=model, usage=usage, attempt_codes=attempt_codes,
        ambiguous_spans=sum(1 for s in verified.spans if s.ambiguous),
    )


def _store_failure(
    store: Store,
    rejections: Sequence[Rejection],
    *,
    now: datetime,
    policy_id: str,
    source_id: str,
    attempts: int,
    latency_s: float,
    usage: dict[str, int],
    model: str | None,
    attempt_codes: tuple[tuple[str, ...], ...],
) -> ExtractionOutcome:
    codes = tuple(dict.fromkeys(r.code for r in rejections))
    reasons = tuple(str(r) for r in rejections)
    draft_id = _draft_id(store, policy_id)

    store.rule_drafts.add(
        RuleDraft(
            id=draft_id,
            policy_source_id=source_id,
            policy_id=policy_id,
            status="extraction_failed",
            # ★ 규칙 내용을 남기지 않는다 (모듈 최상단 주석). 진단은 사유가 진다.
            payload={},
            created_at=now,
            failure_reason=" / ".join(reasons) or "사유가 기록되지 않았다",
        )
    )
    _audit(
        store, now=now, draft_id=draft_id, policy_id=policy_id, source_id=source_id,
        outcome="extraction_failed",
        after={"codes": list(codes), "attempts": attempts,
               "attempt_codes": [list(c) for c in attempt_codes],
               "latency_s": round(latency_s, 3)},
    )
    return ExtractionOutcome(
        policy_id=policy_id, source_id=source_id, draft_id=draft_id,
        status="extraction_failed", codes=codes, reasons=reasons, attempts=attempts,
        latency_s=latency_s, span_count=0, model=model, usage=usage,
        attempt_codes=attempt_codes,
    )


# --------------------------------------------------------------------------
# 배치
# --------------------------------------------------------------------------

def default_targets(store: Store) -> list[tuple[str, str]]:
    """적재된 원문 전수. 수집 대장이 `(source_id, policy_id)` 의 정본이다.

    적재되지 않은 행은 **조용히 빠지지 않는다** — `extract_one` 이 터진다. 조용히 빠지면
    「추출 0건 성공」과 「추출할 것이 없었다」가 구분되지 않는다.
    """
    return [(s.source_id, s.policy_id) for s in loadable_sources()]


def extract_all(
    store: Store,
    *,
    constants: Mapping[str, Any],
    now: datetime,
    call: CallFn = call_extraction,
    call_options: Mapping[str, Any] | None = None,
    targets: Sequence[tuple[str, str]] | None = None,
) -> list[ExtractionOutcome]:
    """대상 전수에 추출을 돌린다. **한 건이 실패해도 멈추지 않는다.**

    멈추면 실패 사유의 분포를 볼 수 없고, 분포가 없으면 SPEC 4.2.2 의 실패율은
    「몇 건 실패」에서 끝난다.
    """
    chosen = list(targets) if targets is not None else default_targets(store)
    return [
        extract_one(
            store, source_id, policy_id,
            constants=constants, now=now, call=call, call_options=call_options,
        )
        for source_id, policy_id in chosen
    ]


def success_breakdown(outcomes: Sequence[ExtractionOutcome]) -> dict[str, int]:
    """성공을 **1차 시도 성공 / 재시도 후 성공** 으로 가른다 (코디네이터 지시 2026-08-14).

    합쳐서 「7건 중 N건 성공」으로 적으면 **모델이 검증을 얼마나 자주 통과 못 하는지가
    숨는다.** 재시도는 같은 입력에 주사위를 다시 굴리는 것이므로, 재시도로 건진 건수는
    1차 성공과 같은 사실이 아니다. 그것이 SPEC 4.2.2 가 재려는 값이다.

    보고에서 이 구분을 손으로 계산하지 않도록 코드가 낸다 — 손으로 하면 다음 사람이 합친다.
    """
    first_try = sum(1 for o in outcomes if o.ok and o.attempts == 1)
    after_retry = sum(1 for o in outcomes if o.ok and o.attempts > 1)
    return {
        "total": len(outcomes),
        "first_try_success": first_try,
        "after_retry_success": after_retry,
        "failed": sum(1 for o in outcomes if not o.ok),
    }


def first_attempt_distribution(outcomes: Sequence[ExtractionOutcome]) -> dict[str, int]:
    """**1차 시도**에서 거부된 사유 분포. 재시도로 건진 건도 여기서 세어진다.

    `failure_distribution` 은 최종 실패만 세므로 재시도가 가린 것을 보지 못한다. 둘을 같이
    내는 이유는 재려는 값이 「최종 몇 건 실패」가 아니라 **모델이 검증을 얼마나 자주 통과
    못 하는가**이기 때문이다 (코디네이터 지시 2026-08-14).
    """
    counts: dict[str, int] = {}
    for outcome in outcomes:
        for code in outcome.first_attempt_codes:
            counts[code] = counts.get(code, 0) + 1
    return dict(sorted(counts.items()))


def failure_distribution(outcomes: Sequence[ExtractionOutcome]) -> dict[str, int]:
    """사유별 건수. SPEC 7.2 의 **추출 스키마 실패율**이 세는 것이 이것이다.

    한 건이 여러 사유로 실패할 수 있으므로 합계가 실패 건수와 다르다. 그 편이 정직하다 —
    사유를 하나로 접으면 「무엇을 고쳐야 하는가」가 사라진다.
    """
    counts: dict[str, int] = {}
    for outcome in outcomes:
        for code in outcome.codes:
            counts[code] = counts.get(code, 0) + 1
    return dict(sorted(counts.items()))
