"""실기동 — `python -m firsthome.ingest.extract_cli`.

SPEC 9.3 #3 의 **배치 작업** 대응물이다: 배치를 실제로 실행하고 **저장소 변화 전후**를 찍는다.

    python -m firsthome.ingest.extract_cli --offline-only     # 키 없이 후반부만 (9.2.1)
    python -m firsthome.ingest.extract_cli --db ./var/x.db    # 실제 LLM 호출까지
    python -m firsthome.ingest.extract_cli --from-env --model gpt-5.4-mini

두 모드가 **같은 코드 경로**를 쓴다는 것이 요점이다. `--offline-only` 는 LLM 호출 단계만
건너뛰고, 스키마 검증 · span 검증 · 위조 거부 · `not_found` 처리는 전부 실제로 돈다.
그것이 SPEC 9.2.1 마지막 줄이 요구하는 것이고, Part 0-B 주장의 기계적 증명이다.

성공하면 0, 하나라도 어긋나면 1로 끝난다.

★ **표준출력을 UTF-8 로 고정한다.** 콘솔 코덱(cp949)에 맡기면 한글·전각 문자가
  `UnicodeEncodeError` 로 죽는다 — 커밋 4d740ad 가 다섯 스크립트에서 닫은 것과 같은 결함이다.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ._console import force_utf8_stdout

force_utf8_stdout()  # 아래 import 보다 먼저 — 그 뒤로는 전부 한국어를 찍는다

from ..llm.extraction import extraction_provider
from ..store import create_store
from ..store.factory import DEFAULT_STORE_URL, STORE_URL_ENV
from ..store.seed import seed_model_constants
from .extraction import (
    EXTRACTION_ACTION,
    MAX_ATTEMPTS_KEY,
    ExtractionOutcome,
    default_targets,
    extract_all,
    failure_distribution,
    first_attempt_distribution,
    success_breakdown,
)
from .extraction_verify import (
    ExtractionRejected,
    RejectionCode,
    rule_draft_schema,
    verify,
)
from .loader import load_policy_sources
from .sources import SOURCES

KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 8, 14, 9, 0, 0, tzinfo=KST)

_failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    mark = "OK  " if condition else "FAIL"
    print(f"  [{mark}] {label}" + (f" - {detail}" if detail else ""))
    if not condition:
        _failures.append(label)


def section(title: str) -> None:
    print(f"\n{title}")
    print("-" * len(title))


def snapshot(store) -> dict[str, int]:
    """저장소의 지금 상태. **전후를 같은 함수로 찍는다** — 다른 함수로 찍으면 비교가 흔들린다."""
    drafts = store.rule_drafts.list()
    return {
        "policy_source": len(store.policy_sources.list()),
        "rule_draft": len(drafts),
        "rule_draft_pending": len(store.rule_drafts.list(status="pending")),
        "rule_draft_failed": len(store.rule_drafts.list(status="extraction_failed")),
        "rule_span_mapping": sum(len(store.rule_drafts.spans_for(d.id)) for d in drafts),
        "rule_version": len(store.rule_versions.list()),
        "audit": len(store.audit.list()),
    }


# --------------------------------------------------------------------------
# 키 없이 도는 후반부 (SPEC 9.2.1) — **저장된 실제 원문으로** 돈다
# --------------------------------------------------------------------------

def probe_envelope(policy_id: str, quote: str, *, offsets: tuple[int, int] | None = None) -> dict:
    """근거가 한 곳뿐인 최소 봉투. 나머지 필드는 정직하게 `not_found` 다.

    이것으로 검증기를 찔러 보는 이유는 **실제 저장된 원문**을 대상 텍스트로 쓰기 때문이다
    (SPEC 4.2.1 이 고정한 대상). 합성 문자열로 확인하면 저장 경로가 빠진다.
    """
    span: dict = {"field_path": "/criteria/regionPrefixes", "quote": quote}
    if offsets is not None:
        span["start"], span["end"] = offsets
    return {
        "draft": {
            "policy_id": policy_id,
            "criteria": {
                "ageMin": None, "ageMax": None, "annualIncomeMaxKRW": None,
                "assetMaxKRW": None, "requireHomeless": None, "requireNewlywed": None,
                "requireSME": None, "regionPrefixes": None,
            },
            "maxAmountKRW": None,
            "rateRangePct": None,
            "conditionalChecks": [],
            "not_found": [
                "/criteria/ageMin", "/criteria/ageMax", "/criteria/annualIncomeMaxKRW",
                "/criteria/assetMaxKRW", "/criteria/requireHomeless",
                "/criteria/requireNewlywed", "/criteria/requireSME",
                "/maxAmountKRW", "/rateRangePct",
            ],
        },
        "spans": [span],
    }


def rejected_codes(envelope: dict, *, policy_id: str, text: str) -> tuple[str, ...]:
    try:
        verify(envelope, policy_id=policy_id, text=text)
    except ExtractionRejected as exc:
        return exc.codes
    return ()


def run_offline_half(store) -> None:
    """★ SPEC 9.2.1 — 「정책 추출의 **후반부**는 전부 동작해야 한다」.

    키가 있든 없든 돈다. 여기서 쓰는 원문은 픽스처가 아니라 **저장소에 적재된 제도 문서**다.
    """
    section("4. ★ 키 없이 도는 후반부 — 저장된 제도 문서 원문으로 검증기를 찔러 본다")
    print("  대상 텍스트 = PolicySource 에 저장된 NFC 정규화 텍스트 (SPEC 4.2.1)")
    print(f"  현재 프로바이더 = {extraction_provider()} (이 절은 프로바이더와 무관하다)\n")

    ledger = {s.source_id: s for s in SOURCES if s.loadable}
    for source in store.policy_sources.list():
        policy_id = ledger[source.id].policy_id
        text = source.text
        # 원문 한가운데에서 실제로 잘라낸 인용. 어떤 문서에서든 반드시 존재한다.
        genuine = text[200:230]

        accepted = verify(
            probe_envelope(policy_id, genuine), policy_id=policy_id, text=text
        )
        span = accepted.spans[0]
        check(
            f"{source.id}: 진짜 인용이 통과하고 text[start:end] 가 인용과 같다",
            text[span.start : span.end] == genuine,
            f"[{span.start}, {span.end})",
        )

        # ① 원문에 없는 인용 — SPEC 10.2 2단계 완료 기준의 첫 줄
        forged = "본 사업의 지원대상은 만 12세 이하 아동이다"
        check(
            f"{source.id}: ★ 위조 인용이 거부된다",
            RejectionCode.SPAN_NOT_IN_TEXT
            in rejected_codes(probe_envelope(policy_id, forged), policy_id=policy_id, text=text),
        )

        # ② 인용은 진짜인데 오프셋이 딴 곳
        check(
            f"{source.id}: ★ 위조 오프셋이 거부된다",
            RejectionCode.SPAN_OFFSET_MISMATCH
            in rejected_codes(
                probe_envelope(policy_id, genuine, offsets=(0, len(genuine))),
                policy_id=policy_id, text=text,
            ),
        )

        # ③ 검증 시점 정규화 금지 — 공백 하나를 더한 「거의 맞는」 인용
        check(
            f"{source.id}: ★ 공백 하나가 달라도 거부된다 (정규화하지 않는다)",
            RejectionCode.SPAN_NOT_IN_TEXT
            in rejected_codes(
                probe_envelope(policy_id, genuine + " "), policy_id=policy_id, text=text
            ),
        )

        # ④ not_found 는 실패가 아니다 — 위 accepted 가 이미 그것이다
        check(
            f"{source.id}: not_found {len(accepted.draft['not_found'])}건이 실패로 처리되지 않는다",
            len(accepted.draft["not_found"]) == 9 and len(accepted.spans) == 1,
        )

        # ⑤ 스키마 강제 — 파수병
        sentinel = probe_envelope(policy_id, genuine)
        sentinel["draft"]["criteria"]["ageMax"] = 200
        sentinel["draft"]["not_found"].remove("/criteria/ageMax")
        check(
            f"{source.id}: 파수병 200 이 스키마에서 거부된다",
            RejectionCode.SCHEMA_VIOLATION
            in rejected_codes(sentinel, policy_id=policy_id, text=text),
        )

        # ⑥ 추정 금지 — not_found 라면서 값이 있다
        guessed = probe_envelope(policy_id, genuine)
        guessed["draft"]["criteria"]["annualIncomeMaxKRW"] = 50000000
        check(
            f"{source.id}: ★ not_found 인데 값이 채워지면 거부된다",
            RejectionCode.NOT_FOUND_VALUE_PRESENT
            in rejected_codes(guessed, policy_id=policy_id, text=text),
        )

    print("\n  ※ 위 절은 API 키 없이 전부 실행된다. LLM 호출은 파이프라인의 한 단계일 뿐이다")
    print("     (SPEC 9.2.1 · Part 0-B).")


# --------------------------------------------------------------------------
# 보고
# --------------------------------------------------------------------------

def report(store, outcomes: list[ExtractionOutcome]) -> None:
    section("6. 건별 결과")
    print(f"    {'policy_id':<24} {'상태':<18} {'시도':>4} {'span':>5} {'다중':>4} "
          f"{'지연(s)':>8} {'토큰':>7}  1차 시도 사유 / 최종 사유")
    for outcome in outcomes:
        first = ",".join(outcome.first_attempt_codes) or "통과"
        final = ",".join(outcome.codes) or "-"
        print(
            f"    {outcome.policy_id:<24} {outcome.status:<18} {outcome.attempts:>4} "
            f"{outcome.span_count:>5} {outcome.ambiguous_spans:>4} {outcome.latency_s:>8.2f} "
            f"{outcome.usage.get('total_tokens', 0):>7}  {first} / {final}"
        )

    section("7. 성공률 — ★ 1차 시도와 재시도 후를 나눈다")
    breakdown = success_breakdown(outcomes)
    print(f"  {json.dumps(breakdown, ensure_ascii=False)}")
    print("  ※ 합쳐서 「N건 성공」으로 적지 않는다 — 재시도는 같은 입력에 주사위를 다시")
    print("     굴리는 것이므로, 합치면 모델이 검증을 얼마나 자주 통과 못 하는지가 숨는다.")

    section("8-a. ★ 1차 시도 거부 사유 분포 — 재시도가 가린 것까지 센다")
    first = first_attempt_distribution(outcomes)
    if first:
        for code, count in first.items():
            print(f"    {code:<28} {count}건")
    else:
        print("    (1차 시도 전건 통과)")
    print("  ※ 여기가 「모델이 검증을 얼마나 자주 통과 못 하는가」다. 아래 8-b 는 최종 실패만")
    print("     세므로 재시도로 건진 건의 1차 거부가 보이지 않는다.")

    section("8-b. 최종 실패 사유 분포 (SPEC 7.2 추출 스키마 실패율)")
    distribution = failure_distribution(outcomes)
    if distribution:
        for code, count in distribution.items():
            print(f"    {code:<28} {count}건")
    else:
        print("    (실패 없음)")
    print("  ※ 한 건이 여러 사유로 실패할 수 있어 합계가 실패 건수와 다르다.")
    for outcome in outcomes:
        for reason in outcome.reasons:
            print(f"    - {outcome.policy_id}: {reason[:220]}")

    section("9. 실측 — 추출 1건당 지연과 토큰 (SPEC 8.3 이 2단계에 남긴 측정)")
    latencies = sorted(o.latency_s for o in outcomes)
    tokens = [o.usage.get("total_tokens", 0) for o in outcomes]
    if latencies:
        print(f"    지연 min {latencies[0]:.2f}s / 중위 {latencies[len(latencies) // 2]:.2f}s "
              f"/ max {latencies[-1]:.2f}s / 합계 {sum(latencies):.2f}s")
        print(f"    토큰 합계 {sum(tokens):,} / 건당 평균 {sum(tokens) / len(tokens):,.0f}")
    ambiguous = sum(o.ambiguous_spans for o in outcomes)
    spans = sum(o.span_count for o in outcomes)
    print(f"    ★ 인용이 원문에 2회 이상 나타난 span: {ambiguous} / {spans}")
    print("       실패가 아니다 — 문자열은 실재하지만 **어느 조항인지는 확정되지 않았다.**")
    print("       5단계 대조 표시(SPEC 4.4 #1)의 선결 과제이며, 첫 등장을 결정적으로 고른다.")
    print("    ※ **금액으로 환산하지 않는다.** 검증된 단가표를 확인하지 않았고,")
    print("       확인하지 않은 값을 확인한 값과 같은 형태로 적는 것이 SPEC 8.3 #1 위반이다.")
    print("       환산이 필요하면 단가를 원문확인한 뒤 코디네이터가 계약에 싣는다.")

    section("10. span 왕복 — 저장된 오프셋이 저장된 원문과 맞는가")
    total = 0
    for draft in store.rule_drafts.list(status="pending"):
        source = store.policy_sources.get(draft.policy_source_id)
        for span in store.rule_drafts.spans_for(draft.id):
            resolved = store.rule_drafts.resolve_span(span)
            total += 1
            check(
                f"{draft.id} {span.field_path}",
                resolved == source.text[span.start : span.end] and bool(resolved),
                f"«{resolved[:40]}»",
            )
    if total == 0:
        print("    (pending 초안이 없어 대조할 span 이 없다)")

    section("11. 배치가 만든 것은 pending 뿐인가 (SPEC 4.6)")
    check(
        "RuleVersion 이 늘지 않았다",
        all(v.origin == "seed" for v in store.rule_versions.list()),
        f"RuleVersion {len(store.rule_versions.list())}건 전부 seed",
    )


# --------------------------------------------------------------------------
# 실행
# --------------------------------------------------------------------------

def run(url: str, *, offline_only: bool, model: str | None, timeout: float | None,
        limit: int | None) -> int:
    print(f"저장소 URL: {url}")
    print(f"프로바이더: {extraction_provider()}  ·  모드: "
          f"{'offline-only (LLM 호출 건너뜀)' if offline_only else '실제 LLM 호출'}")

    with create_store(url) as store:
        section("1. 전제 — 원문 적재 · 모델 상수")
        if not store.policy_sources.list():
            loaded = load_policy_sources(store, run_at=NOW)
            print(f"  원문을 적재했다: {len(loaded)}건")
        constants = store.model_constants.as_mapping()
        if not constants:
            print(f"  모델 상수를 시드했다: {seed_model_constants(store)}건")
            constants = store.model_constants.as_mapping()
        check("적재된 원문이 있다", bool(store.policy_sources.list()),
              f"{len(store.policy_sources.list())}건")

        section("2. 저장소 변화 — **전**")
        before = snapshot(store)
        print(f"  {json.dumps(before, ensure_ascii=False)}")

        section("3. 계약 — RuleDraft 스키마")
        schema = rule_draft_schema()
        print(f"  {schema['title']} · {len(schema['properties'])} 최상단 필드 · "
              f"additionalProperties={schema['additionalProperties']}")
        print(f"  criteria {len(schema['properties']['criteria']['properties'])}종")

        run_offline_half(store)

        section("5. 배치 실행 — extract_all()")
        if offline_only:
            print("  건너뛴다 (--offline-only). 위 4절이 후반부 전 과정을 이미 돌렸다.")
            outcomes: list[ExtractionOutcome] = []
        elif MAX_ATTEMPTS_KEY not in constants:
            # ★ fail-closed 가 작동하는 모습이다. 고장이 아니다 (SPEC 5.1.1).
            print(f"  차단됨 — 저장소에 {MAX_ATTEMPTS_KEY} 가 없다.")
            print("  이것은 설계대로다: 재시도 횟수는 (d) 규범적 선택이므로 계약 레지스트리에")
            print("  등재되기 전에는 배치가 돌지 않는다. 코드에 기본값을 두지 않았다.")
            _failures.append(f"{MAX_ATTEMPTS_KEY} 미등재")
            outcomes = []
        else:
            targets = default_targets(store)
            if limit is not None:
                targets = targets[:limit]
            options = {}
            if model:
                options["model"] = model
            if timeout is not None:
                options["timeout_seconds"] = timeout
            print(f"  대상 {len(targets)}건 · 최대 시도 {constants[MAX_ATTEMPTS_KEY]}회"
                  f"{' · model=' + model if model else ''}"
                  f"{' · timeout=' + str(timeout) + 's' if timeout else ''}")
            outcomes = extract_all(
                store, constants=constants, now=NOW,
                call_options=options or None, targets=targets,
            )

        if outcomes:
            report(store, outcomes)

        section("12. 저장소 변화 — **후**")
        after = snapshot(store)
        for key in before:
            arrow = "->" if before[key] != after[key] else "=="
            print(f"    {key:<22} {before[key]:>4} {arrow} {after[key]:>4}")
        check(
            "감사기록이 추출 건수만큼 늘었다",
            after["audit"] - before["audit"] == len(outcomes),
            f"{EXTRACTION_ACTION} {len(store.audit.list(action=EXTRACTION_ACTION))}건",
        )
        check(
            "extraction_failed 초안에는 규칙 내용이 없다 (부분 저장 금지)",
            all(d.payload == {} for d in store.rule_drafts.list(status="extraction_failed")),
        )
        check(
            "extraction_failed 초안에는 span 이 없다",
            all(
                not store.rule_drafts.spans_for(d.id)
                for d in store.rule_drafts.list(status="extraction_failed")
            ),
        )

    section("결과")
    if _failures:
        print(f"  실패 {len(_failures)}건: {_failures}")
        return 1
    print("  전 항목 통과")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="추출 파이프라인 실기동 (SPEC 4.1 #2~#6)")
    parser.add_argument("--db", help="SQLite 파일 경로. 없으면 임시 파일에 실행한다")
    parser.add_argument("--from-env", action="store_true", help=f"{STORE_URL_ENV} 를 쓴다")
    parser.add_argument(
        "--offline-only", action="store_true",
        help="LLM 호출을 건너뛰고 후반부만 돌린다 (SPEC 9.2.1 — 키 없이 도는 범위)",
    )
    parser.add_argument("--model", help="이 실행에 쓸 모델. 기본값은 OPENAI_MODEL")
    parser.add_argument(
        "--timeout", type=float,
        help="이 실행의 HTTP 타임아웃(초). **제품 상수가 아니다** — SPEC 8.3 #1 은 "
             "타임아웃을 측정에서 유도하라고 하고, 그 측정이 이 과업의 산출물이다",
    )
    parser.add_argument("--limit", type=int, help="앞 N 건만 추출한다 (비용 확인용)")
    args = parser.parse_args(argv)

    options = dict(
        offline_only=args.offline_only, model=args.model,
        timeout=args.timeout, limit=args.limit,
    )
    if args.from_env:
        return run(os.environ.get(STORE_URL_ENV) or DEFAULT_STORE_URL, **options)
    if args.db:
        return run(f"sqlite://{args.db}", **options)
    with tempfile.TemporaryDirectory() as tmp:
        return run(f"sqlite://{Path(tmp) / 'extract.db'}", **options)


if __name__ == "__main__":
    sys.exit(main())
