"""저장소 인터페이스 (부록 A).

> **주의 — 첫 항목은 문서가 아니라 코드 결정이다.** "인터페이스 뒤에 둔다"는 `store` 의
> 설계 자체이며 0단계 산출물이다. 부록으로 미루면 0단계가 인터페이스 없이 지어지고,
> 그때 부록 A는 사후 증명이 불가능해진다. 7.1의 append-only 보장도 이 인터페이스가 지고 있다.

여기 없는 것이 곧 보장이다. `AuditLog` 에는 `append` 와 `list` 밖에 없고,
`RuleVersionRepository` 에는 일반 `update` 가 없다. 없는 메서드는 백엔드를 바꿔도 생기지 않는다.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from .models import (
    AnomalyReport,
    ApprovalRecord,
    AuditEvent,
    ModelConstant,
    PolicySource,
    Region,
    RuleDraft,
    RuleSpanMapping,
    RuleVersion,
    User,
)


class RegionRepository(ABC):
    @abstractmethod
    def upsert(self, region: Region) -> Region:
        """지역 시세를 등재·갱신한다. 배치가 같은 날 다시 돌아도 결과가 같아야 한다 (SPEC 3)."""

    @abstractmethod
    def get(self, code: str) -> Region | None:
        """없으면 `None`. 알 수 없는 지역 코드는 오류가 아니라 부재다."""

    @abstractmethod
    def list(self) -> list[Region]:
        """등재 순서를 유지한다."""


class PolicySourceRepository(ABC):
    @abstractmethod
    def add(self, source: PolicySource) -> PolicySource:
        """`text` 를 NFC 정규화해 저장한다 (계약 결정 #7). 반환값이 정규화된 형태다."""

    @abstractmethod
    def get(self, source_id: str) -> PolicySource | None: ...

    @abstractmethod
    def list(self) -> list[PolicySource]: ...


class RuleDraftRepository(ABC):
    """초안. **여기 있는 것은 어떤 경로로도 판정에 참여하지 않는다** (SPEC 2.3)."""

    @abstractmethod
    def add(self, draft: RuleDraft) -> RuleDraft: ...

    @abstractmethod
    def get(self, draft_id: str) -> RuleDraft | None: ...

    @abstractmethod
    def list(self, status: str | None = None) -> list[RuleDraft]: ...

    @abstractmethod
    def set_status(self, draft_id: str, status: str, failure_reason: str | None = None) -> RuleDraft:
        """`pending -> approved / rejected / extraction_failed`.

        draft 의 `approved` 는 **판정 참여를 뜻하지 않는다.** 승인은 별도의 `RuleVersion`
        을 낳는 사건이고, 그 전까지 판정은 이 테이블을 보지 않는다.

        **조건이 없는 설정자다.** 사람의 결정(승인·반려)에는 쓰지 않는다 — 그 경로는
        `claim_pending` 이다. 여기 남겨 두는 것은 조건 없이 상태를 되돌려야 하는 자리
        (추출 실패 표시, 선점 원복, 시드·시연 준비) 때문이다.
        """

    @abstractmethod
    def claim_pending(
        self, draft_id: str, status: str, failure_reason: str | None = None
    ) -> RuleDraft:
        """`pending -> status` 를 **단일 전이**로 실행한다 (SPEC 4.6).

        승인은 판정을 바꾸는 유일한 경로이고, 여기서 둘이 동시에 이기면 같은 초안에서
        `RuleVersion` 이 둘 생기거나 `ApprovalRecord` 만 둘 남는다. 그래서 결정은
        [읽고 나서 쓴다] 가 아니라 **[pending 인 것을 조건으로 쓴다]** 여야 한다.

        조건을 API 계층에 두면 저장소를 바꾸는 순간 보장이 사라지므로(부록 A) 이 메서드가
        계약을 진다. **여러 호출자가 동시에 불러도 정확히 하나만 성공한다.** 진 쪽은
        `DraftAlreadyDecidedError`, 초안이 아예 없으면 `RecordNotFoundError` 다.
        `status='pending'` 은 전이가 아니므로 거부한다.
        """

    @abstractmethod
    def add_span(self, span: RuleSpanMapping) -> RuleSpanMapping:
        """구간이 원문 밖이면 거부한다 (SPEC 4.2.1)."""

    @abstractmethod
    def spans_for(self, draft_id: str) -> list[RuleSpanMapping]: ...

    @abstractmethod
    def resolve_span(self, span: RuleSpanMapping) -> str:
        """`text[start:end]`. 정규화된 원문을 그대로 자른다 — 여기서 다시 주무르지 않는다."""


class RuleVersionRepository(ABC):
    """승인된 규칙. 불변이다 (SPEC 2.2).

    일반 `update` · `delete` 가 **없다.** 규칙을 바꾸는 유일한 경로는 `supersede` 다.
    """

    @abstractmethod
    def add(self, version: RuleVersion) -> RuleVersion:
        """계약 결정 #5 의 `origin` 불변식을 통과해야 들어간다."""

    @abstractmethod
    def get(self, version_id: str) -> RuleVersion | None: ...

    @abstractmethod
    def list(self) -> list[RuleVersion]:
        """관리 화면용 전수 조회. **판정은 이것을 쓰지 않는다** — `active` 를 쓴다."""

    @abstractmethod
    def supersede(self, previous_id: str, new_version: RuleVersion, at: datetime) -> RuleVersion:
        """이전 버전을 `at` 에 닫고 새 버전을 연다. 한 트랜잭션이다.

        새 버전이 거부되면 이전 버전도 닫히지 않는다 — 그 사이에 활성 규칙이 0개가 되는
        순간이 생기면 판정이 통째로 비어버린다.
        """

    @abstractmethod
    def active(self, at: datetime) -> list[RuleVersion]:
        """SPEC 2.3 — 판정에 참여하는 규칙. **판정 경로가 부르는 유일한 조회다.**

            status = 'approved'
            AND (effective_from IS NULL OR effective_from <= at)
            AND (effective_to   IS NULL OR at < effective_to)

        NULL 의 의미는 계약 결정 #6 — from=시작일 미상, to=무기한.
        """


class ModelConstantRepository(ABC):
    @abstractmethod
    def put(self, constant: ModelConstant) -> ModelConstant: ...

    @abstractmethod
    def get(self, key: str) -> ModelConstant | None: ...

    @abstractmethod
    def list(self) -> list[ModelConstant]: ...

    @abstractmethod
    def as_mapping(self) -> dict[str, Any]:
        """SPEC 5.1.1 의 주입 형태 — `Mapping[str, ConstantValue]`.

        호출자가 돌려받은 매핑을 고쳐도 저장소는 변하지 않는다. 매번 새 사본이다.
        """


class UserRepository(ABC):
    @abstractmethod
    def add(self, user: User) -> User: ...

    @abstractmethod
    def get(self, user_id: str) -> User | None: ...

    @abstractmethod
    def get_by_username(self, username: str) -> User | None: ...

    @abstractmethod
    def list(self) -> list[User]: ...


class ApprovalRecordRepository(ABC):
    @abstractmethod
    def add(self, record: ApprovalRecord) -> ApprovalRecord:
        """사유 없는 반려는 거부된다 (SPEC 10.2 5단계)."""

    @abstractmethod
    def list_for(self, target_id: str) -> list[ApprovalRecord]: ...

    @abstractmethod
    def list(self) -> list[ApprovalRecord]: ...


class AnomalyReportRepository(ABC):
    """상담원 이상 신고 (SPEC 6.4 · 계약 결정 #38). **`RuleDraft` 와 별개다.**

    ★ **결정 메서드가 없다.** `RuleDraftRepository` 에는 `set_status` 와 `claim_pending`
      이 있지만 여기에는 없다 — 초안의 승인은 규칙을 낳는 사건이고, 신고의 「승인」은
      뜻이 없기 때문이다. 신고는 제안이지 변경이 아니다 (SoD 유지).

      SPEC 6.4 는 신고를 받은 뒤 규칙관리자가 「수동으로 입력하거나 재추출을 지시한다」
      고만 적었고 자동 처리를 배정하지 않았다. 없는 동작을 인터페이스에 미리 뚫어 두면
      그것이 곧 신고가 규칙으로 넘어가는 경로다 — 여기 없는 것이 곧 보장이다.
    """

    @abstractmethod
    def add(self, report: AnomalyReport) -> AnomalyReport:
        """대상이 정책·시세 **항목** 목록 밖이면 거부한다 (SPEC 7.1 · 계약 결정 #38)."""

    @abstractmethod
    def get(self, report_id: str) -> AnomalyReport | None: ...

    @abstractmethod
    def list(self, status: str | None = None) -> list[AnomalyReport]:
        """등재 순서를 유지한다. 대기 큐가 이것을 그대로 그린다 (SPEC 6.4)."""


class AuditLog(ABC):
    """SPEC 7.1 append-only 의 **첫 번째 겹**.

    수정·삭제 메서드가 존재하지 않는다. 이것은 규율이 아니라 구조다 — 백엔드를 바꿔도
    없는 메서드는 생기지 않는다. 두 번째 겹(SQLite 트리거)은 DB 를 직접 여는 경로를 막는다.
    """

    @abstractmethod
    def append(self, event: AuditEvent) -> AuditEvent: ...

    @abstractmethod
    def list(self, action: str | None = None) -> list[AuditEvent]:
        """`at` 오름차순. **같은 `at` 안에서만** 기록 순서를 유지한다.

        ★ 「기록 순서」 하나로는 부족하다. append-only 는 [행을 고치는 것]을 막지
          [지난 시각의 행을 나중에 붙이는 것]을 막지 않으므로 기록 순서와 시각 순서는
          갈릴 수 있고, 그때 이 목록의 **마지막 원소**를 「마지막 사건」이라 부르는
          호출자가 실재한다 (`main.build_batch_status` 의 `lastRunAt`).

          순서를 정하는 것은 백엔드가 아니라 이 계약이다 — 여기 적지 않으면 백엔드를
          바꿀 때 그 호출자가 조용히 다른 답을 받는다.
        """


class Store(ABC):
    """저장소 하나. 백엔드는 `create_store(url)` 이 설정만 보고 고른다."""

    @property
    @abstractmethod
    def regions(self) -> RegionRepository: ...

    @property
    @abstractmethod
    def policy_sources(self) -> PolicySourceRepository: ...

    @property
    @abstractmethod
    def rule_drafts(self) -> RuleDraftRepository: ...

    @property
    @abstractmethod
    def rule_versions(self) -> RuleVersionRepository: ...

    @property
    @abstractmethod
    def model_constants(self) -> ModelConstantRepository: ...

    @property
    @abstractmethod
    def users(self) -> UserRepository: ...

    @property
    @abstractmethod
    def approvals(self) -> ApprovalRecordRepository: ...

    @property
    @abstractmethod
    def reports(self) -> AnomalyReportRepository: ...

    @property
    @abstractmethod
    def audit(self) -> AuditLog: ...

    @abstractmethod
    def close(self) -> None: ...

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
