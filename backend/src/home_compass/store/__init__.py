"""`store` — 저장소 계층. SQLite 기본, 교체 가능 (SPEC 1.1 · 부록 A).

    from home_compass.store import store_from_env
    with store_from_env() as store:
        rules = store.rule_versions.active(datetime.now(timezone.utc))

호출자는 어떤 백엔드가 붙었는지 모른다. 백엔드는 `HOME_COMPASS_STORE_URL` 하나가 정한다.

이 패키지가 지고 있는 보장 셋 —
  - `AuditEvent` append-only (SPEC 7.1). 인터페이스에 수정·삭제가 **없고**, SQLite 는
    트리거로 한 겹 더 건다
  - 판정에 나가는 규칙은 `rule_versions.active(at)` 하나뿐이다 (SPEC 2.3).
    `RuleDraft` 는 어떤 경로로도 거기 실리지 않는다
  - **프로세스 수명 캐시가 없다** (SPEC 2.3). 승인·배치 반영이 재기동 없이 보인다
"""

from __future__ import annotations

from .errors import (
    DraftAlreadyDecidedError,
    ProvenanceError,
    RecordNotFoundError,
    SpanOutOfRangeError,
    StoreError,
    UnknownBackendError,
)
from .factory import (
    DEFAULT_STORE_URL,
    STORE_URL_ENV,
    available_backends,
    create_store,
    register_backend,
    store_from_env,
)
from .interfaces import (
    AnomalyReportRepository,
    ApprovalRecordRepository,
    AuditLog,
    ModelConstantRepository,
    PolicySourceRepository,
    RegionRepository,
    RuleDraftRepository,
    RuleVersionRepository,
    Store,
    UserRepository,
)
from .models import (
    AnomalyReport,
    ApprovalRecord,
    AuditEvent,
    ModelConstant,
    PolicySource,
    Provenance,
    Region,
    RuleDraft,
    RuleSpanMapping,
    RuleVersion,
    User,
)
from .sqlite_store import SQLiteStore as _SQLiteStore

#: SQLite 는 기본 백엔드일 뿐이다. 외부 DB 는 `register_backend` 로 같은 자리에 붙는다.
register_backend("sqlite", _SQLiteStore.open)

__all__ = [
    # 설정 · 생성
    "create_store",
    "store_from_env",
    "register_backend",
    "available_backends",
    "STORE_URL_ENV",
    "DEFAULT_STORE_URL",
    # 인터페이스
    "Store",
    "RegionRepository",
    "PolicySourceRepository",
    "RuleDraftRepository",
    "RuleVersionRepository",
    "ModelConstantRepository",
    "UserRepository",
    "ApprovalRecordRepository",
    "AnomalyReportRepository",
    "AuditLog",
    # 엔티티
    "Provenance",
    "Region",
    "PolicySource",
    "RuleDraft",
    "RuleSpanMapping",
    "RuleVersion",
    "ModelConstant",
    "User",
    "ApprovalRecord",
    "AnomalyReport",
    "AuditEvent",
    # 오류
    "StoreError",
    "ProvenanceError",
    "RecordNotFoundError",
    "DraftAlreadyDecidedError",
    "SpanOutOfRangeError",
    "UnknownBackendError",
]
