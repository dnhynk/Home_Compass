"""저장소 계층의 예외.

전부 `StoreError` 아래에 둔다. 호출자가 백엔드별 예외(`sqlite3.IntegrityError` 등)를
알아야 한다면 그 순간 저장소는 교체 가능하지 않다 (부록 A).
"""

from __future__ import annotations


class StoreError(Exception):
    """저장소 계층에서 나오는 모든 오류의 뿌리."""


class ProvenanceError(StoreError):
    """`contracts/provenance.schema.json` 을 통과하지 못한 계보.

    저장 시점에 터진다. 응답 조립 시점으로 미루면 이미 들어온 잘못된 계보는 영원히 남는다.
    """


class RecordNotFoundError(StoreError):
    """참조 대상이 없다."""


class DraftAlreadyDecidedError(StoreError):
    """`pending` 이 아닌 초안에 결정을 걸었다 (SPEC 4.6).

    `RecordNotFoundError` 와 갈라 두는 이유는 호출자가 [없다](404)와 [이미 끝났다](409)를
    **다른 답으로** 내보내야 하기 때문이다. 하나로 뭉치면 API 가 둘을 가르려고 상태를 다시
    읽어야 하고, 그 재조회 자체가 4.6 이 없애려는 바로 그 경합 지점이 된다.
    """


class SpanOutOfRangeError(StoreError):
    """`RuleSpanMapping` 의 구간이 원문 밖이다 (SPEC 4.2.1)."""


class UnknownBackendError(StoreError):
    """설정 문자열이 가리키는 백엔드가 등록되어 있지 않다."""
