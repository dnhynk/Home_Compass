"""`ingest` — 배치 (SPEC 1.1 · 9.4 소유 경로).

이 모듈이 다루는 것은 **정책 규칙 추출 파이프라인의 1단계(수집)** 다 (SPEC 4.1 #1).
**시세 수집(SPEC Part 3)은 `ingest.market` 하위 패키지**에 따로 있다 — 두 배치는 출처도
실패 양상도 다르고, 섞으면 「어느 수집이 실패했는가」가 한 진입점 뒤로 숨는다.

    python -m firsthome.ingest            # 임시 DB 에 적재하고 조회 결과를 출력
    python -m firsthome.ingest --db ./var/collect.db
    python -m firsthome.ingest.market     # 시세 수집 배치 (SPEC Part 3)

이 패키지가 지고 있는 것 —
  - 대상은 **현행 `policies.json` 전수**다. 못 찾은 것은 `[출처 미특정]` 으로 남기고
    비슷한 다른 상품으로 대체하지 않는다
  - **이용조건이 확인된 원문만 적재한다** (SPEC 잔여 실사 — 확인하지 않은 채 저장·배포하지 않는다)
  - 원문의 정본은 `data/policy_sources/*.txt` 의 텍스트다. 원본 PDF·HTML 을 다시 파싱하는
    경로를 만들지 않는다 (SPEC 4.1)

여기 **없는 것**이 곧 경계다 — LLM 추출, `RuleDraft`, `RuleSpanMapping`, 배치 스케줄링.
"""

from __future__ import annotations

from .loader import load_policy_sources
from .sources import (
    COLLECTION_RUN_AT,
    DOC_KIND_LABELS,
    DOC_KINDS,
    INGEST_ACTION,
    INGEST_ACTOR,
    LICENCE_BASIS_COPYRIGHT_ACT,
    LICENCE_BASIS_KOGL_TYPE_4,
    LICENCES,
    LICENCES_CLEARED,
    RETRIEVED_ON,
    SECURED_COUNT,
    SOURCES,
    CollectedSource,
    collection_report,
    loadable_sources,
    text_dir,
)

__all__ = [
    "load_policy_sources",
    "CollectedSource",
    "SOURCES",
    "SECURED_COUNT",
    "DOC_KINDS",
    "DOC_KIND_LABELS",
    "LICENCES",
    "LICENCES_CLEARED",
    "LICENCE_BASIS_COPYRIGHT_ACT",
    "LICENCE_BASIS_KOGL_TYPE_4",
    "COLLECTION_RUN_AT",
    "RETRIEVED_ON",
    "INGEST_ACTOR",
    "INGEST_ACTION",
    "collection_report",
    "loadable_sources",
    "text_dir",
]
