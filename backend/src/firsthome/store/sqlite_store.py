"""SQLite 구현체. `sqlite://<path>` 또는 `sqlite://:memory:` 로 선택된다.

캐시가 없다. 모든 조회가 매번 DB 를 친다 — SPEC 2.3 이 금지한 것은 "프로세스가 사는 동안
다시 읽지 않는" 구조이고, 그 결함이 승인->시민화면 시연을 무너뜨린다. 저장소 계층에서
무효화 없는 캐시를 두지 않으면 상류가 그것을 흉내낼 이유도 없어진다.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .errors import DraftAlreadyDecidedError, RecordNotFoundError, StoreError
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
from .sqlite_schema import SCHEMA, TRIGGERS
from .validation import (
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

MEMORY_TARGET = ":memory:"


# --------------------------------------------------------------------------
# 직렬화 — 시각은 UTC 정규화 RFC 3339 로 적어 문자열 비교가 시각 비교와 일치하게 한다.
# --------------------------------------------------------------------------


def _dt_out(value: datetime | None) -> str | None:
    return None if value is None else value.astimezone(timezone.utc).isoformat()


def _dt_in(value: str | None) -> datetime | None:
    return None if value is None else datetime.fromisoformat(value)


def _json_out(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=False)


def _provenance_out(provenance: Provenance) -> str:
    return _json_out(provenance.to_dict())


def _provenance_in(raw: str) -> Provenance:
    return Provenance.from_dict(json.loads(raw))


def _constant_value_in(raw: str, value_type: str) -> Any:
    """JSON 은 int 키도 튜플도 모른다. 계약의 `value_type` 이 그 둘을 되살린다."""
    value = json.loads(raw)
    if value_type == "krw_by_household":
        return {int(k): v for k, v in value.items()}
    if value_type == "policy_id_order":
        return tuple(value)
    return value


def _translate(exc: sqlite3.Error) -> StoreError:
    """백엔드 예외를 밖으로 흘리지 않는다 (부록 A)."""
    return StoreError(str(exc))


# --------------------------------------------------------------------------
# 리포지터리
# --------------------------------------------------------------------------


class _Base:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def _write(self, sql: str, params: tuple = ()) -> None:
        self._write_all([(sql, params)])

    def _write_all(self, statements: list[tuple[str, tuple]]) -> None:
        """여러 문을 **한 트랜잭션**으로 쓴다.

        지역 값과 그 계보가 따로 커밋되면 그 사이에 「값은 새것인데 계보는 이전 배치」인
        레코드가 존재하게 된다. 그 상태가 무엇을 뜻하는지 아무도 말할 수 없다.
        """
        try:
            with self._conn:
                for sql, params in statements:
                    self._conn.execute(sql, params)
        except sqlite3.Error as exc:
            raise _translate(exc) from exc


class _Regions(_Base, RegionRepository):
    _COLUMNS = (
        "code, name, jeonse_median_krw, monthly_deposit_krw, monthly_rent_krw,"
        " maintenance_fee_krw, jeonse_ratio_pct, conversion_rate_pct, market_risk,"
        " guarantee_available, provenance_json"
    )

    def upsert(self, region: Region) -> Region:
        validate_region(region)
        # ON CONFLICT DO UPDATE 는 rowid 를 보존한다. INSERT OR REPLACE 는 행을 지웠다
        # 다시 넣어 등재 순서를 흐트러뜨린다.
        statements: list[tuple[str, tuple]] = [(
            f"INSERT INTO region ({self._COLUMNS}) VALUES (?,?,?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(code) DO UPDATE SET"
            "   name=excluded.name,"
            "   jeonse_median_krw=excluded.jeonse_median_krw,"
            "   monthly_deposit_krw=excluded.monthly_deposit_krw,"
            "   monthly_rent_krw=excluded.monthly_rent_krw,"
            "   maintenance_fee_krw=excluded.maintenance_fee_krw,"
            "   jeonse_ratio_pct=excluded.jeonse_ratio_pct,"
            "   conversion_rate_pct=excluded.conversion_rate_pct,"
            "   market_risk=excluded.market_risk,"
            "   guarantee_available=excluded.guarantee_available,"
            "   provenance_json=excluded.provenance_json",
            (
                region.code,
                region.name,
                region.jeonse_median_krw,
                region.monthly_deposit_krw,
                region.monthly_rent_krw,
                region.maintenance_fee_krw,
                region.jeonse_ratio_pct,
                region.conversion_rate_pct,
                region.market_risk,
                int(region.guarantee_available),
                _provenance_out(region.provenance),
            ),
        )]
        # 계보는 **집합째** 갈아 끼운다. 지우지 않고 덮어쓰기만 하면 이전 배치가 남긴
        # 항목이 새 배치의 항목과 섞여, 그 레코드의 계보가 무엇인지 말할 수 없게 된다.
        statements.append(
            ("DELETE FROM region_field_provenance WHERE region_code = ?", (region.code,))
        )
        statements.extend(
            (
                "INSERT INTO region_field_provenance (region_code, field_name, provenance_json)"
                " VALUES (?,?,?)",
                (region.code, name, _provenance_out(provenance)),
            )
            for name, provenance in region.field_provenance.items()
        )
        self._write_all(statements)
        return region

    def _field_provenance(self, codes: list[str]) -> dict[str, dict[str, Provenance]]:
        """지역별 계보를 **한 번의 조회**로 모은다. 지역마다 따로 물으면 목록 조회가 N+1 이 된다."""
        if not codes:
            return {}
        placeholders = ",".join("?" * len(codes))
        rows = self._conn.execute(
            "SELECT region_code, field_name, provenance_json FROM region_field_provenance"
            f" WHERE region_code IN ({placeholders})",
            tuple(codes),
        ).fetchall()
        grouped: dict[str, dict[str, Provenance]] = {code: {} for code in codes}
        for row in rows:
            grouped[row["region_code"]][row["field_name"]] = _provenance_in(row["provenance_json"])
        return grouped

    @staticmethod
    def _row(row: sqlite3.Row, field_provenance: dict[str, Provenance]) -> Region:
        return Region(
            code=row["code"],
            name=row["name"],
            jeonse_median_krw=row["jeonse_median_krw"],
            monthly_deposit_krw=row["monthly_deposit_krw"],
            monthly_rent_krw=row["monthly_rent_krw"],
            maintenance_fee_krw=row["maintenance_fee_krw"],
            jeonse_ratio_pct=row["jeonse_ratio_pct"],
            conversion_rate_pct=row["conversion_rate_pct"],
            market_risk=row["market_risk"],
            guarantee_available=bool(row["guarantee_available"]),
            provenance=_provenance_in(row["provenance_json"]),
            field_provenance=field_provenance,
        )

    def get(self, code: str) -> Region | None:
        row = self._conn.execute(
            f"SELECT {self._COLUMNS} FROM region WHERE code = ?", (code,)
        ).fetchone()
        if row is None:
            return None
        return self._row(row, self._field_provenance([code]).get(code, {}))

    def list(self) -> list[Region]:
        rows = self._conn.execute(f"SELECT {self._COLUMNS} FROM region ORDER BY rowid").fetchall()
        grouped = self._field_provenance([r["code"] for r in rows])
        return [self._row(r, grouped.get(r["code"], {})) for r in rows]


class _PolicySources(_Base, PolicySourceRepository):
    def add(self, source: PolicySource) -> PolicySource:
        require_aware(source.fetched_at, "fetched_at")
        stored = PolicySource(
            id=source.id,
            text=normalize_text(source.text),
            source_ref=source.source_ref,
            fetched_at=source.fetched_at,
            attribution=source.attribution,
        )
        self._write(
            "INSERT INTO policy_source (id, text, source_ref, fetched_at, attribution)"
            " VALUES (?,?,?,?,?)"
            " ON CONFLICT(id) DO UPDATE SET text=excluded.text,"
            " source_ref=excluded.source_ref, fetched_at=excluded.fetched_at,"
            " attribution=excluded.attribution",
            (
                stored.id,
                stored.text,
                stored.source_ref,
                _dt_out(stored.fetched_at),
                stored.attribution,
            ),
        )
        return stored

    @staticmethod
    def _row(row: sqlite3.Row) -> PolicySource:
        return PolicySource(
            id=row["id"],
            text=row["text"],
            source_ref=row["source_ref"],
            fetched_at=_dt_in(row["fetched_at"]),
            attribution=row["attribution"],
        )

    def get(self, source_id: str) -> PolicySource | None:
        row = self._conn.execute(
            "SELECT * FROM policy_source WHERE id = ?", (source_id,)
        ).fetchone()
        return None if row is None else self._row(row)

    def list(self) -> list[PolicySource]:
        rows = self._conn.execute("SELECT * FROM policy_source ORDER BY rowid").fetchall()
        return [self._row(r) for r in rows]


class _RuleDrafts(_Base, RuleDraftRepository):
    def add(self, draft: RuleDraft) -> RuleDraft:
        validate_draft_status(draft.status)
        require_aware(draft.created_at, "created_at")
        if self._source_text(draft.policy_source_id) is None:
            raise RecordNotFoundError(f"알 수 없는 PolicySource: {draft.policy_source_id}")
        self._write(
            "INSERT INTO rule_draft (id, policy_source_id, policy_id, status, payload_json,"
            " created_at, failure_reason) VALUES (?,?,?,?,?,?,?)",
            (
                draft.id,
                draft.policy_source_id,
                draft.policy_id,
                draft.status,
                _json_out(draft.payload),
                _dt_out(draft.created_at),
                draft.failure_reason,
            ),
        )
        return draft

    def _source_text(self, source_id: str) -> str | None:
        row = self._conn.execute(
            "SELECT text FROM policy_source WHERE id = ?", (source_id,)
        ).fetchone()
        return None if row is None else row["text"]

    @staticmethod
    def _row(row: sqlite3.Row) -> RuleDraft:
        return RuleDraft(
            id=row["id"],
            policy_source_id=row["policy_source_id"],
            policy_id=row["policy_id"],
            status=row["status"],
            payload=json.loads(row["payload_json"]),
            created_at=_dt_in(row["created_at"]),
            failure_reason=row["failure_reason"],
        )

    def get(self, draft_id: str) -> RuleDraft | None:
        row = self._conn.execute("SELECT * FROM rule_draft WHERE id = ?", (draft_id,)).fetchone()
        return None if row is None else self._row(row)

    def list(self, status: str | None = None) -> list[RuleDraft]:
        if status is None:
            rows = self._conn.execute("SELECT * FROM rule_draft ORDER BY rowid").fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM rule_draft WHERE status = ? ORDER BY rowid", (status,)
            ).fetchall()
        return [self._row(r) for r in rows]

    def set_status(self, draft_id: str, status: str, failure_reason: str | None = None) -> RuleDraft:
        validate_draft_status(status)
        if self.get(draft_id) is None:
            raise RecordNotFoundError(f"알 수 없는 RuleDraft: {draft_id}")
        self._write(
            "UPDATE rule_draft SET status = ?, failure_reason = ? WHERE id = ?",
            (status, failure_reason, draft_id),
        )
        return self.get(draft_id)

    def claim_pending(
        self, draft_id: str, status: str, failure_reason: str | None = None
    ) -> RuleDraft:
        """SPEC 4.6 — **조건부 UPDATE** 로 선점한다.

        트랜잭션으로 감싸는 대신 조건부 UPDATE 를 고른 이유:

        - 상태 검사와 상태 쓰기가 **한 문장 안에** 있다. 트랜잭션으로 감싸도 `SELECT` 후
          `UPDATE` 라면 SQLite 의 기본 지연 트랜잭션에서는 둘 사이에 다른 커넥션이 끼어들
          수 있고, 그것을 막으려면 `BEGIN IMMEDIATE` 를 손으로 걸어야 한다. 그 순간
          보장이 **SQL 방언**에 실린다 — 두 번째 백엔드가 같은 계약을 지려면 그 방언까지
          따라와야 하고, 부록 A 의 교체 가능성이 거기서 깨진다.
        - `WHERE ... AND status='pending'` 은 어떤 관계형 백엔드에도 그대로 있다.
          진 쪽은 예외가 아니라 **0행 변경**으로 돌아오며, 그 0 이 곧 [내가 졌다] 다.
        - SQLite 는 쓰기를 직렬화한다. 두 번째 UPDATE 는 첫 번째가 커밋된 뒤에 실행되므로
          `status='pending'` 을 더는 만족하지 못한다. 잠금 대기는 커넥션의 `timeout` 이
          흡수한다.

        `rowcount` 를 읽은 **뒤에** 다시 조회하는 것은 메시지에 실을 현재 상태를 얻기
        위해서일 뿐이다. 판정은 이미 끝났고, 그 사이 상태가 또 바뀌어도 결론은 안 바뀐다.
        """
        validate_draft_status(status)
        if status == "pending":
            raise StoreError("claim_pending 은 pending 에서 빠져나오는 전이다 (SPEC 4.6)")
        try:
            with self._conn:
                changed = self._conn.execute(
                    "UPDATE rule_draft SET status = ?, failure_reason = ?"
                    " WHERE id = ? AND status = 'pending'",
                    (status, failure_reason, draft_id),
                ).rowcount
        except sqlite3.Error as exc:
            raise _translate(exc) from exc
        if changed == 0:
            current = self.get(draft_id)
            if current is None:
                raise RecordNotFoundError(f"알 수 없는 RuleDraft: {draft_id}")
            raise DraftAlreadyDecidedError(
                f"이미 처리된 RuleDraft 다 (현재 상태: {current.status}): {draft_id}"
            )
        return self.get(draft_id)

    def add_span(self, span: RuleSpanMapping) -> RuleSpanMapping:
        draft = self.get(span.draft_id)
        if draft is None:
            raise RecordNotFoundError(f"알 수 없는 RuleDraft: {span.draft_id}")
        text = self._source_text(draft.policy_source_id) or ""
        validate_span(text, span.start, span.end, span.field_path)
        self._write(
            "INSERT INTO rule_span_mapping (id, draft_id, field_path, start_cp, end_cp)"
            " VALUES (?,?,?,?,?)",
            (span.id, span.draft_id, span.field_path, span.start, span.end),
        )
        return span

    def spans_for(self, draft_id: str) -> list[RuleSpanMapping]:
        rows = self._conn.execute(
            "SELECT * FROM rule_span_mapping WHERE draft_id = ? ORDER BY rowid", (draft_id,)
        ).fetchall()
        return [
            RuleSpanMapping(
                id=r["id"],
                draft_id=r["draft_id"],
                field_path=r["field_path"],
                start=r["start_cp"],
                end=r["end_cp"],
            )
            for r in rows
        ]

    def resolve_span(self, span: RuleSpanMapping) -> str:
        draft = self.get(span.draft_id)
        if draft is None:
            raise RecordNotFoundError(f"알 수 없는 RuleDraft: {span.draft_id}")
        text = self._source_text(draft.policy_source_id) or ""
        return text[span.start : span.end]


class _RuleVersions(_Base, RuleVersionRepository):
    def _validate(self, version: RuleVersion) -> None:
        validate_provenance(version.provenance)
        if version.status != "approved":
            raise StoreError(
                f"RuleVersion 은 승인된 규칙만 담는다 (SPEC 2.2): status={version.status!r}"
            )
        # human_approval 은 '승인' 기록이 있어야 하고, seed 는 어떤 기록도 없어야 한다 (계약 #5).
        # 반려 기록은 승인으로 세지 않지만, seed 에게는 그것도 있어서는 안 된다.
        if version.origin == "seed":
            probe = "SELECT 1 FROM approval_record WHERE target_id = ?"
        else:
            probe = "SELECT 1 FROM approval_record WHERE target_id = ? AND decision = 'approved'"
        has_record = self._conn.execute(probe, (version.id,)).fetchone() is not None

        validate_rule_version_origin(
            origin=version.origin,
            approved_by=version.approved_by,
            has_approval_record=has_record,
        )
        if version.effective_from is not None:
            require_aware(version.effective_from, "effective_from")
        if version.effective_to is not None:
            require_aware(version.effective_to, "effective_to")
        require_aware(version.created_at, "created_at")

    def _insert_sql(self) -> str:
        return (
            "INSERT INTO rule_version (id, policy_id, payload_json, status, origin,"
            " effective_from, effective_to, supersedes, approved_by, provenance_json, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)"
        )

    def _insert_params(self, version: RuleVersion) -> tuple:
        return (
            version.id,
            version.policy_id,
            _json_out(version.payload),
            version.status,
            version.origin,
            _dt_out(version.effective_from),
            _dt_out(version.effective_to),
            version.supersedes,
            version.approved_by,
            _provenance_out(version.provenance),
            _dt_out(version.created_at),
        )

    def add(self, version: RuleVersion) -> RuleVersion:
        self._validate(version)
        if self.get(version.id) is not None:
            raise StoreError(f"RuleVersion 은 불변이다 — 이미 존재: {version.id}")
        self._write(self._insert_sql(), self._insert_params(version))
        return version

    @staticmethod
    def _row(row: sqlite3.Row) -> RuleVersion:
        return RuleVersion(
            id=row["id"],
            policy_id=row["policy_id"],
            payload=json.loads(row["payload_json"]),
            status=row["status"],
            origin=row["origin"],
            effective_from=_dt_in(row["effective_from"]),
            effective_to=_dt_in(row["effective_to"]),
            supersedes=row["supersedes"],
            approved_by=row["approved_by"],
            provenance=_provenance_in(row["provenance_json"]),
            created_at=_dt_in(row["created_at"]),
        )

    def get(self, version_id: str) -> RuleVersion | None:
        row = self._conn.execute("SELECT * FROM rule_version WHERE id = ?", (version_id,)).fetchone()
        return None if row is None else self._row(row)

    def list(self) -> list[RuleVersion]:
        rows = self._conn.execute("SELECT * FROM rule_version ORDER BY rowid").fetchall()
        return [self._row(r) for r in rows]

    def supersede(self, previous_id: str, new_version: RuleVersion, at: datetime) -> RuleVersion:
        previous = self.get(previous_id)
        if previous is None:
            raise RecordNotFoundError(f"알 수 없는 RuleVersion: {previous_id}")
        if previous.effective_to is not None:
            raise StoreError(f"이미 종료된 RuleVersion 이다: {previous_id}")
        require_aware(at, "at")
        if previous.effective_from is not None and at <= previous.effective_from:
            raise StoreError("effective_to 는 effective_from 보다 뒤여야 한다")

        # 새 버전 검증을 먼저 끝낸다 — 이전 버전만 닫히고 새 버전이 거부되면
        # 그 순간부터 활성 규칙이 0개가 된다.
        self._validate(new_version)
        if self.get(new_version.id) is not None:
            raise StoreError(f"RuleVersion 은 불변이다 — 이미 존재: {new_version.id}")

        try:
            with self._conn:
                self._conn.execute(self._insert_sql(), self._insert_params(new_version))
                self._conn.execute(
                    "UPDATE rule_version SET effective_to = ? WHERE id = ?",
                    (_dt_out(at), previous_id),
                )
        except sqlite3.Error as exc:
            raise _translate(exc) from exc
        return new_version

    def active(self, at: datetime) -> list[RuleVersion]:
        require_aware(at, "at")
        rows = self._conn.execute(
            "SELECT * FROM rule_version"
            " WHERE status = 'approved'"
            "   AND (effective_from IS NULL OR effective_from <= :now)"
            "   AND (effective_to   IS NULL OR :now < effective_to)"
            " ORDER BY rowid",
            {"now": _dt_out(at)},
        ).fetchall()
        return [self._row(r) for r in rows]


class _ModelConstants(_Base, ModelConstantRepository):
    def put(self, constant: ModelConstant) -> ModelConstant:
        validate_provenance(constant.provenance)
        self._write(
            "INSERT INTO model_constant (key, engine, legacy_symbol, spec_class, value_type,"
            " value_json, provenance_json) VALUES (?,?,?,?,?,?,?)"
            " ON CONFLICT(key) DO UPDATE SET engine=excluded.engine,"
            " legacy_symbol=excluded.legacy_symbol, spec_class=excluded.spec_class,"
            " value_type=excluded.value_type, value_json=excluded.value_json,"
            " provenance_json=excluded.provenance_json",
            (
                constant.key,
                constant.engine,
                constant.legacy_symbol,
                constant.spec_class,
                constant.value_type,
                _json_out(constant.value),
                _provenance_out(constant.provenance),
            ),
        )
        return constant

    @staticmethod
    def _row(row: sqlite3.Row) -> ModelConstant:
        return ModelConstant(
            key=row["key"],
            engine=row["engine"],
            legacy_symbol=row["legacy_symbol"],
            spec_class=row["spec_class"],
            value_type=row["value_type"],
            value=_constant_value_in(row["value_json"], row["value_type"]),
            provenance=_provenance_in(row["provenance_json"]),
        )

    def get(self, key: str) -> ModelConstant | None:
        row = self._conn.execute("SELECT * FROM model_constant WHERE key = ?", (key,)).fetchone()
        return None if row is None else self._row(row)

    def list(self) -> list[ModelConstant]:
        rows = self._conn.execute("SELECT * FROM model_constant ORDER BY rowid").fetchall()
        return [self._row(r) for r in rows]

    def as_mapping(self) -> dict[str, Any]:
        return {c.key: c.value for c in self.list()}


class _Users(_Base, UserRepository):
    def add(self, user: User) -> User:
        validate_role(user.role)
        require_aware(user.created_at, "created_at")
        self._write(
            "INSERT INTO app_user (id, username, role, password_hash, created_at)"
            " VALUES (?,?,?,?,?)",
            (user.id, user.username, user.role, user.password_hash, _dt_out(user.created_at)),
        )
        return user

    @staticmethod
    def _row(row: sqlite3.Row) -> User:
        return User(
            id=row["id"],
            username=row["username"],
            role=row["role"],
            password_hash=row["password_hash"],
            created_at=_dt_in(row["created_at"]),
        )

    def get(self, user_id: str) -> User | None:
        row = self._conn.execute("SELECT * FROM app_user WHERE id = ?", (user_id,)).fetchone()
        return None if row is None else self._row(row)

    def get_by_username(self, username: str) -> User | None:
        row = self._conn.execute(
            "SELECT * FROM app_user WHERE username = ?", (username,)
        ).fetchone()
        return None if row is None else self._row(row)

    def list(self) -> list[User]:
        rows = self._conn.execute("SELECT * FROM app_user ORDER BY rowid").fetchall()
        return [self._row(r) for r in rows]


class _Approvals(_Base, ApprovalRecordRepository):
    def add(self, record: ApprovalRecord) -> ApprovalRecord:
        require_aware(record.at, "at")
        validate_approval(record.decision, record.reason)
        self._write(
            "INSERT INTO approval_record (id, actor_user_id, at, target_kind, target_id,"
            " decision, reason) VALUES (?,?,?,?,?,?,?)",
            (
                record.id,
                record.actor_user_id,
                _dt_out(record.at),
                record.target_kind,
                record.target_id,
                record.decision,
                record.reason,
            ),
        )
        return record

    @staticmethod
    def _row(row: sqlite3.Row) -> ApprovalRecord:
        return ApprovalRecord(
            id=row["id"],
            actor_user_id=row["actor_user_id"],
            at=_dt_in(row["at"]),
            target_kind=row["target_kind"],
            target_id=row["target_id"],
            decision=row["decision"],
            reason=row["reason"],
        )

    def list_for(self, target_id: str) -> list[ApprovalRecord]:
        rows = self._conn.execute(
            "SELECT * FROM approval_record WHERE target_id = ? ORDER BY rowid", (target_id,)
        ).fetchall()
        return [self._row(r) for r in rows]

    def list(self) -> list[ApprovalRecord]:
        rows = self._conn.execute("SELECT * FROM approval_record ORDER BY rowid").fetchall()
        return [self._row(r) for r in rows]


class _Reports(_Base, AnomalyReportRepository):
    """SPEC 6.4 이상 신고. `_RuleDrafts` 와 **다른 테이블·다른 문**이다 (계약 결정 #38)."""

    def add(self, report: AnomalyReport) -> AnomalyReport:
        validate_report(report)
        if self.get(report.id) is not None:
            raise StoreError(f"이미 존재하는 AnomalyReport: {report.id}")
        self._write(
            "INSERT INTO anomaly_report (id, reporter, at, target_kind, target_id,"
            " target_field, reason, status) VALUES (?,?,?,?,?,?,?,?)",
            (
                report.id,
                report.reporter,
                _dt_out(report.at),
                report.target_kind,
                report.target_id,
                report.target_field,
                report.reason,
                report.status,
            ),
        )
        return report

    @staticmethod
    def _row(row: sqlite3.Row) -> AnomalyReport:
        return AnomalyReport(
            id=row["id"],
            reporter=row["reporter"],
            at=_dt_in(row["at"]),
            target_kind=row["target_kind"],
            target_id=row["target_id"],
            target_field=row["target_field"],
            reason=row["reason"],
            status=row["status"],
        )

    def get(self, report_id: str) -> AnomalyReport | None:
        row = self._conn.execute(
            "SELECT * FROM anomaly_report WHERE id = ?", (report_id,)
        ).fetchone()
        return None if row is None else self._row(row)

    def list(self, status: str | None = None) -> list[AnomalyReport]:
        if status is None:
            rows = self._conn.execute("SELECT * FROM anomaly_report ORDER BY rowid").fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM anomaly_report WHERE status = ? ORDER BY rowid", (status,)
            ).fetchall()
        return [self._row(r) for r in rows]


class _AuditLog(_Base, AuditLog):
    """SPEC 7.1 — `append` 와 `list` 뿐이다. 없는 메서드는 백엔드를 바꿔도 생기지 않는다."""

    def append(self, event: AuditEvent) -> AuditEvent:
        require_aware(event.at, "at")
        self._write(
            "INSERT INTO audit_event (id, actor, at, action, target, outcome, before_json,"
            " after_json) VALUES (?,?,?,?,?,?,?,?)",
            (
                event.id,
                event.actor,
                _dt_out(event.at),
                event.action,
                event.target,
                event.outcome,
                None if event.before is None else _json_out(event.before),
                None if event.after is None else _json_out(event.after),
            ),
        )
        return event

    @staticmethod
    def _row(row: sqlite3.Row) -> AuditEvent:
        return AuditEvent(
            id=row["id"],
            actor=row["actor"],
            at=_dt_in(row["at"]),
            action=row["action"],
            target=row["target"],
            outcome=row["outcome"],
            before=None if row["before_json"] is None else json.loads(row["before_json"]),
            after=None if row["after_json"] is None else json.loads(row["after_json"]),
        )

    def list(self, action: str | None = None) -> list[AuditEvent]:
        # 시각순이고, 같은 시각 안에서만 기록순(`rowid`)이다.
        #
        # ★ **`rowid` 만으로는 틀린다.** 여기 있던 주석은 「append-only 이므로 둘이
        #   어긋날 수 없다」고 적었는데 그것이 거짓이다 — append-only 가 막는 것은
        #   [행을 고치는 것]이지 [지난 시각의 행을 나중에 붙이는 것]이 아니다.
        #   시드가 실행 기록을 나중에 넣거나, 두 프로세스가 순서를 섞어 쓰거나,
        #   배치가 지난 시각으로 기록을 남기면 삽입순과 시각순이 갈린다.
        #   그리고 갈릴 때 `main.build_batch_status` 는 이 목록의 **마지막 원소**를
        #   「마지막 배치 실행」이라 부른다. `/api/health` 는 그 사실을 `lastRunAt` ·
        #   `lastOutcome` 두 칸으로만 싣기 때문에 어긋나도 화면에 단서가 없다.
        #
        # `at` 을 SQL 에서 그대로 정렬해도 되는 이유는 위 `_dt_out` 이 UTC 정규화
        # RFC 3339 로 적기 때문이다 (모듈 첫머리) — 문자열 순서가 곧 시각 순서다.
        # 오프셋 없는 값은 `require_aware` 가 `append` 에서 이미 막는다.
        #
        # 보조 키를 `rowid` 로 두는 이유: 한 배치 실행은 지역별 행과 실행 행을 **같은
        # `now`** 로 쓴다. 동률의 순서를 정해 두지 않으면 그 안이 실행마다 흔들리고
        # [실행 행이 지역별 행 뒤에 온다] 는 기록의 뜻이 사라진다.
        if action is None:
            rows = self._conn.execute("SELECT * FROM audit_event ORDER BY at, rowid").fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM audit_event WHERE action = ? ORDER BY at, rowid", (action,)
            ).fetchall()
        return [self._row(r) for r in rows]


# --------------------------------------------------------------------------
# Store
# --------------------------------------------------------------------------


class SQLiteStore(Store):
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._regions = _Regions(conn)
        self._policy_sources = _PolicySources(conn)
        self._rule_drafts = _RuleDrafts(conn)
        self._rule_versions = _RuleVersions(conn)
        self._model_constants = _ModelConstants(conn)
        self._users = _Users(conn)
        self._approvals = _Approvals(conn)
        self._reports = _Reports(conn)
        self._audit = _AuditLog(conn)

    @classmethod
    def open(cls, target: str) -> "SQLiteStore":
        """`target` 은 파일 경로 또는 `:memory:` 다."""
        if target != MEMORY_TARGET:
            Path(target).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(target)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        with conn:
            conn.executescript(SCHEMA)
            conn.executescript(TRIGGERS)
        return cls(conn)

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
        self._conn.close()
