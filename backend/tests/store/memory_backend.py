"""부록 A 의 증명 도구 — store 인터페이스의 두 번째 구현체.

"SQLite ↔ 외부 DB 교체가 코드 변경 없이 설정으로 가능하다" 는 주장은 구현이 하나뿐이면
증명할 수 없다. 그래서 프로덕션 코드가 아닌 **테스트 쪽**에 완전히 다른 저장 매체(딕셔너리)를
쓰는 두 번째 구현체를 두고, SQLite 와 **같은 계약 테스트를 통과**시킨다.

여기서 증명되는 것은 둘이다.
  1. `create_store(url)` 의 스킴만 바꾸면 백엔드가 갈린다 — 호출자 코드는 그대로다
  2. SPEC 7.1 의 append-only 보장이 SQLite 트리거가 없는 백엔드에서도 유지된다
     (트리거는 두 겹 중 (b)일 뿐이고, (a)인 인터페이스가 매체와 무관하게 막는다)

이 파일은 배포물에 들어가지 않는다.
"""

from __future__ import annotations

import copy
import threading
from datetime import datetime

from firsthome.store.errors import DraftAlreadyDecidedError, RecordNotFoundError, StoreError
from firsthome.store.interfaces import (
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
from firsthome.store.models import (
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
from firsthome.store.validation import (
    normalize_text,
    require_aware,
    validate_approval,
    validate_draft_status,
    validate_provenance,
    validate_region,
    validate_report,
    validate_role,
    validate_rule_version_origin,
    validate_span,
)


class _NoClaimGate:
    """`claim_pending` 이 부르는 두 지점의 기본 구현 — 아무것도 하지 않는다.

    `test_draft_claim.py` 는 [읽기]와 [쓰기] 사이가 실제로 배타적인지를 **스케줄러에
    기대지 않고** 재야 한다. 그러려면 그 사이에 손을 넣을 자리가 있어야 하는데, 자리를
    SQLite 쪽(제품 코드)에 내면 저장소가 테스트를 알게 된다. 이 파일은 배포물에 들어가지
    않는 두 번째 구현체이므로 여기에만 낸다.

    자리를 내는 것과 자리를 쓰는 것은 다르다 — 기본값인 이 구현은 잠금을 그대로 돌려주고
    읽기 지점에서 아무것도 하지 않으므로, 압력을 걸지 않는 모든 테스트에서 동작이 같다.
    """

    def guard(self, lock):
        return lock

    def read(self) -> None:
        pass


NO_CLAIM_GATE = _NoClaimGate()


class _MemoryRegions(RegionRepository):
    def __init__(self) -> None:
        self._rows: dict[str, Region] = {}

    def upsert(self, region: Region) -> Region:
        # 필드별 계보(SPEC 2.1 · 3.1)의 검사도 같은 문을 지난다. 백엔드마다 다른 문을
        # 만들면 그때부터 두 저장소가 서로 다른 것을 보장한다.
        validate_region(region)
        self._rows[region.code] = region
        return region

    def get(self, code: str) -> Region | None:
        return self._rows.get(code)

    def list(self) -> list[Region]:
        return list(self._rows.values())


class _MemoryPolicySources(PolicySourceRepository):
    def __init__(self) -> None:
        self._rows: dict[str, PolicySource] = {}

    def add(self, source: PolicySource) -> PolicySource:
        require_aware(source.fetched_at, "fetched_at")
        stored = PolicySource(
            id=source.id,
            text=normalize_text(source.text),
            source_ref=source.source_ref,
            fetched_at=source.fetched_at,
            # 계약 결정 #15. 두 백엔드가 **같은 계약 테스트**를 통과하는 것이
            # 「저장소를 교체해도 같은 보장」의 근거다 — 여기서 빠지면 그 근거가 사라진다.
            attribution=source.attribution,
        )
        self._rows[stored.id] = stored
        return stored

    def get(self, source_id: str) -> PolicySource | None:
        return self._rows.get(source_id)

    def list(self) -> list[PolicySource]:
        return list(self._rows.values())


class _MemoryRuleDrafts(RuleDraftRepository):
    def __init__(self, sources: _MemoryPolicySources) -> None:
        self._sources = sources
        self._rows: dict[str, RuleDraft] = {}
        self._spans: list[RuleSpanMapping] = []
        #: SPEC 4.6 의 [단일 전이] 를 이 매체에서 지는 것. SQLite 는 DB 잠금이 하고,
        #: 여기서는 이 잠금이 한다. **GIL 에 기대지 않는다** — 검사와 쓰기 사이에
        #: 바이트코드 경계가 있고, 거기서 스레드가 갈리면 둘 다 이긴다.
        self._claim_lock = threading.Lock()
        #: 경합 시험이 [읽기와 쓰기 사이] 에 손을 넣는 자리. 기본값은 아무것도 하지 않는다.
        self.claim_gate = NO_CLAIM_GATE

    def add(self, draft: RuleDraft) -> RuleDraft:
        validate_draft_status(draft.status)
        require_aware(draft.created_at, "created_at")
        if draft.policy_source_id not in self._sources._rows:
            raise RecordNotFoundError(f"알 수 없는 PolicySource: {draft.policy_source_id}")
        if draft.id in self._rows:
            raise StoreError(f"이미 존재하는 RuleDraft: {draft.id}")
        self._rows[draft.id] = draft
        return draft

    def get(self, draft_id: str) -> RuleDraft | None:
        return self._rows.get(draft_id)

    def list(self, status: str | None = None) -> list[RuleDraft]:
        rows = list(self._rows.values())
        return [r for r in rows if status is None or r.status == status]

    def set_status(self, draft_id: str, status: str, failure_reason: str | None = None) -> RuleDraft:
        validate_draft_status(status)
        draft = self._rows.get(draft_id)
        if draft is None:
            raise RecordNotFoundError(f"알 수 없는 RuleDraft: {draft_id}")
        updated = RuleDraft(
            id=draft.id,
            policy_source_id=draft.policy_source_id,
            policy_id=draft.policy_id,
            status=status,
            payload=draft.payload,
            created_at=draft.created_at,
            failure_reason=failure_reason,
        )
        self._rows[draft_id] = updated
        return updated

    def claim_pending(
        self, draft_id: str, status: str, failure_reason: str | None = None
    ) -> RuleDraft:
        """SPEC 4.6 — 검사와 쓰기를 **한 임계구역**에 넣는다.

        SQLite 가 조건부 UPDATE 한 문장으로 하는 것을, 딕셔너리에는 그런 문장이 없으므로
        잠금으로 한다. 계약은 같다 — 동시에 여럿이 불러도 하나만 성공한다. 이것이 부록 A
        의 "매체가 달라도 같은 보장" 이 실제로 성립하는지의 두 번째 증거다.
        """
        validate_draft_status(status)
        if status == "pending":
            raise StoreError("claim_pending 은 pending 에서 빠져나오는 전이다 (SPEC 4.6)")
        with self.claim_gate.guard(self._claim_lock):
            draft = self._rows.get(draft_id)
            self.claim_gate.read()
            if draft is None:
                raise RecordNotFoundError(f"알 수 없는 RuleDraft: {draft_id}")
            if draft.status != "pending":
                raise DraftAlreadyDecidedError(
                    f"이미 처리된 RuleDraft 다 (현재 상태: {draft.status}): {draft_id}"
                )
            updated = RuleDraft(
                id=draft.id,
                policy_source_id=draft.policy_source_id,
                policy_id=draft.policy_id,
                status=status,
                payload=draft.payload,
                created_at=draft.created_at,
                failure_reason=failure_reason,
            )
            self._rows[draft_id] = updated
        return updated

    def add_span(self, span: RuleSpanMapping) -> RuleSpanMapping:
        draft = self._rows.get(span.draft_id)
        if draft is None:
            raise RecordNotFoundError(f"알 수 없는 RuleDraft: {span.draft_id}")
        source = self._sources.get(draft.policy_source_id)
        assert source is not None
        validate_span(source.text, span.start, span.end, span.field_path)
        self._spans.append(span)
        return span

    def spans_for(self, draft_id: str) -> list[RuleSpanMapping]:
        return [s for s in self._spans if s.draft_id == draft_id]

    def resolve_span(self, span: RuleSpanMapping) -> str:
        draft = self._rows[span.draft_id]
        source = self._sources.get(draft.policy_source_id)
        assert source is not None
        return source.text[span.start : span.end]


class _MemoryRuleVersions(RuleVersionRepository):
    def __init__(self, approvals: "_MemoryApprovals") -> None:
        self._approvals = approvals
        self._rows: dict[str, RuleVersion] = {}

    def add(self, version: RuleVersion) -> RuleVersion:
        validate_provenance(version.provenance)
        validate_rule_version_origin(
            origin=version.origin,
            approved_by=version.approved_by,
            has_approval_record=any(
                r.target_id == version.id and r.decision == "approved"
                for r in self._approvals.list()
            ),
        )
        if version.effective_from is not None:
            require_aware(version.effective_from, "effective_from")
        if version.effective_to is not None:
            require_aware(version.effective_to, "effective_to")
            if version.effective_from is not None and version.effective_to <= version.effective_from:
                raise StoreError("effective_to 는 effective_from 보다 뒤여야 한다")
        if version.status != "approved":
            raise StoreError("RuleVersion 은 승인된 규칙만 담는다 (SPEC 2.2)")
        if version.id in self._rows:
            raise StoreError(f"RuleVersion 은 불변이다 — 이미 존재: {version.id}")
        self._rows[version.id] = version
        return version

    def get(self, version_id: str) -> RuleVersion | None:
        return self._rows.get(version_id)

    def list(self) -> list[RuleVersion]:
        return list(self._rows.values())

    def supersede(self, previous_id: str, new_version: RuleVersion, at: datetime) -> RuleVersion:
        previous = self._rows.get(previous_id)
        if previous is None:
            raise RecordNotFoundError(f"알 수 없는 RuleVersion: {previous_id}")
        if previous.effective_to is not None:
            raise StoreError(f"이미 종료된 RuleVersion 이다: {previous_id}")
        require_aware(at, "at")
        if previous.effective_from is not None and at <= previous.effective_from:
            raise StoreError("effective_to 는 effective_from 보다 뒤여야 한다")
        added = self.add(new_version)
        self._rows[previous_id] = RuleVersion(
            id=previous.id,
            policy_id=previous.policy_id,
            payload=previous.payload,
            status=previous.status,
            origin=previous.origin,
            effective_from=previous.effective_from,
            effective_to=at,
            supersedes=previous.supersedes,
            approved_by=previous.approved_by,
            provenance=previous.provenance,
            created_at=previous.created_at,
        )
        return added

    def active(self, at: datetime) -> list[RuleVersion]:
        """SPEC 2.3. NULL 의 의미 — from=시작일 미상, to=무기한."""
        require_aware(at, "at")
        return [
            v
            for v in self._rows.values()
            if v.status == "approved"
            and (v.effective_from is None or v.effective_from <= at)
            and (v.effective_to is None or at < v.effective_to)
        ]


class _MemoryModelConstants(ModelConstantRepository):
    def __init__(self) -> None:
        self._rows: dict[str, ModelConstant] = {}

    def put(self, constant: ModelConstant) -> ModelConstant:
        validate_provenance(constant.provenance)
        self._rows[constant.key] = constant
        return constant

    def get(self, key: str) -> ModelConstant | None:
        return self._rows.get(key)

    def list(self) -> list[ModelConstant]:
        return list(self._rows.values())

    def as_mapping(self) -> dict[str, object]:
        return {k: copy.deepcopy(v.value) for k, v in self._rows.items()}


class _MemoryUsers(UserRepository):
    def __init__(self) -> None:
        self._rows: dict[str, User] = {}

    def add(self, user: User) -> User:
        validate_role(user.role)
        require_aware(user.created_at, "created_at")
        if user.id in self._rows:
            raise StoreError(f"이미 존재하는 User: {user.id}")
        if any(u.username == user.username for u in self._rows.values()):
            raise StoreError(f"이미 존재하는 username: {user.username}")
        self._rows[user.id] = user
        return user

    def get(self, user_id: str) -> User | None:
        return self._rows.get(user_id)

    def get_by_username(self, username: str) -> User | None:
        for user in self._rows.values():
            if user.username == username:
                return user
        return None

    def list(self) -> list[User]:
        return list(self._rows.values())


class _MemoryApprovals(ApprovalRecordRepository):
    def __init__(self) -> None:
        self._rows: list[ApprovalRecord] = []

    def add(self, record: ApprovalRecord) -> ApprovalRecord:
        require_aware(record.at, "at")
        validate_approval(record.decision, record.reason)
        if any(r.id == record.id for r in self._rows):
            raise StoreError(f"이미 존재하는 ApprovalRecord: {record.id}")
        self._rows.append(record)
        return record

    def list_for(self, target_id: str) -> list[ApprovalRecord]:
        return [r for r in self._rows if r.target_id == target_id]

    def list(self) -> list[ApprovalRecord]:
        return list(self._rows)


class _MemoryReports(AnomalyReportRepository):
    """SPEC 6.4 이상 신고. **`_MemoryRuleDrafts` 와 다른 딕셔너리다** (계약 결정 #38).

    같은 문(`validate_report`)을 지난다 — 대상 한정이 SQLite 의 CHECK 제약이 아니라
    파이썬 층에 있는 이유가 이것이다. 매체가 달라도 [자유 텍스트 대상은 안 된다]가
    남아야 7.1 의 방어가 저장소 교체 뒤에도 성립한다 (부록 A).
    """

    def __init__(self) -> None:
        self._rows: dict[str, AnomalyReport] = {}

    def add(self, report: AnomalyReport) -> AnomalyReport:
        validate_report(report)
        if report.id in self._rows:
            raise StoreError(f"이미 존재하는 AnomalyReport: {report.id}")
        self._rows[report.id] = report
        return report

    def get(self, report_id: str) -> AnomalyReport | None:
        return self._rows.get(report_id)

    def list(self, status: str | None = None) -> list[AnomalyReport]:
        return [r for r in self._rows.values() if status is None or r.status == status]


class _MemoryAuditLog(AuditLog):
    """SPEC 7.1 (a) — update·delete 를 노출하지 않는다. 매체와 무관하다."""

    def __init__(self) -> None:
        self._rows: list[AuditEvent] = []

    def append(self, event: AuditEvent) -> AuditEvent:
        require_aware(event.at, "at")
        if any(e.id == event.id for e in self._rows):
            raise StoreError(f"이미 존재하는 AuditEvent: {event.id}")
        self._rows.append(event)
        return event

    def list(self, action: str | None = None) -> list[AuditEvent]:
        # 계약은 `at` 오름차순 · 동시각은 기록순이다 (`interfaces.AuditLog.list`).
        # `sorted` 가 안정 정렬이므로 append 순서가 그대로 동률의 순서가 된다 —
        # SQLite 쪽 `ORDER BY at, rowid` 와 같은 뜻이며, 이 한 줄이 [순서는 계약이지
        # SQLite 의 성질이 아니다] 를 증명한다.
        rows = [e for e in self._rows if action is None or e.action == action]
        return sorted(rows, key=lambda e: e.at)


class MemoryStore(Store):
    """딕셔너리 기반 백엔드. `memory://<label>` 로 선택된다."""

    def __init__(self, label: str = "") -> None:
        self.label = label
        self._regions = _MemoryRegions()
        self._policy_sources = _MemoryPolicySources()
        self._rule_drafts = _MemoryRuleDrafts(self._policy_sources)
        self._approvals = _MemoryApprovals()
        self._rule_versions = _MemoryRuleVersions(self._approvals)
        self._model_constants = _MemoryModelConstants()
        self._users = _MemoryUsers()
        self._reports = _MemoryReports()
        self._audit = _MemoryAuditLog()

    @classmethod
    def open(cls, target: str) -> "MemoryStore":
        return cls(label=target)

    @property
    def regions(self) -> RegionRepository:
        return self._regions

    @property
    def policy_sources(self) -> PolicySourceRepository:
        return self._policy_sources

    @property
    def rule_drafts(self) -> RuleDraftRepository:
        return self._rule_drafts

    @property
    def rule_versions(self) -> RuleVersionRepository:
        return self._rule_versions

    @property
    def model_constants(self) -> ModelConstantRepository:
        return self._model_constants

    @property
    def users(self) -> UserRepository:
        return self._users

    @property
    def approvals(self) -> ApprovalRecordRepository:
        return self._approvals

    @property
    def reports(self) -> AnomalyReportRepository:
        return self._reports

    @property
    def audit(self) -> AuditLog:
        return self._audit

    def close(self) -> None:
        return None
