"""SQLite 스키마 — SPEC 7.1 append-only 의 **두 번째 겹**이 여기 있다.

인터페이스가 update/delete 를 노출하지 않는 것(첫 번째 겹)은 저장소를 거쳐 가는 경로만
막는다. DB 파일을 직접 여는 경로는 트리거만이 막는다. 두 겹이 각각 필요하다.

**시각 표기.** `at` · `effective_from` · `effective_to` · `created_at` · `fetched_at` 은
UTC 로 정규화한 RFC 3339 문자열이다. 오프셋이 섞이면 문자열 비교가 시각 비교와 어긋나
활성 규칙 창(SPEC 2.3)이 조용히 틀린다. SPEC 2.1 의 "UTC로 뭉개지 않는다"는
`Provenance` 의 **기준시점** 규칙이며, 그 값은 `provenance_json` 안에 손대지 않고 그대로 있다.
"""

from __future__ import annotations

SCHEMA = """
CREATE TABLE IF NOT EXISTS region (
    code                TEXT PRIMARY KEY,
    name                TEXT NOT NULL,
    jeonse_median_krw   INTEGER NOT NULL,
    monthly_deposit_krw INTEGER NOT NULL,
    monthly_rent_krw    INTEGER NOT NULL,
    maintenance_fee_krw INTEGER NOT NULL,
    jeonse_ratio_pct    REAL NOT NULL,
    conversion_rate_pct REAL NOT NULL,
    market_risk         TEXT NOT NULL,
    guarantee_available INTEGER NOT NULL CHECK (guarantee_available IN (0, 1)),
    -- 레코드 단위 **요약**이다. 필드별 계보의 최악값이며(SPEC 2.4) 화면의 `source` 가 본다.
    provenance_json     TEXT NOT NULL
);

-- SPEC 2.1 · 3.1 — 계보는 사실 단위다. 지역당 하나로는 「3필드가 unverified」와
-- 「외부 실패 시 stale」을 동시에 보일 수 없다 (SPEC 10.2 3단계).
-- 별도 테이블인 이유: 지역 열에 계보 8칸을 붙이면 필드가 늘 때마다 스키마가 바뀌고,
-- 무엇보다 `region` 의 열과 계보의 키가 **두 벌의 이름표**가 된다.
CREATE TABLE IF NOT EXISTS region_field_provenance (
    region_code     TEXT NOT NULL REFERENCES region(code) ON DELETE CASCADE,
    -- `REGION_FACT_FIELDS` 의 이름 (응답 키와 같은 camelCase). 검증은 저장소 계층이 한다.
    field_name      TEXT NOT NULL,
    provenance_json TEXT NOT NULL,
    PRIMARY KEY (region_code, field_name)
);

CREATE TABLE IF NOT EXISTS policy_source (
    id          TEXT PRIMARY KEY,
    -- NFC 정규화된 추출 텍스트 (계약 결정 #7). rule_span_mapping 의 오프셋 기준이다.
    text        TEXT NOT NULL,
    -- 참조. **URL 그대로** 둔다 — 기관·공고번호를 여기 말아 넣으면 화면이 URL 만 못 뽑는다.
    source_ref  TEXT,
    fetched_at  TEXT NOT NULL,
    -- 출처표시 문구 (계약 결정 #15). 사람이 읽고 화면이 그대로 인용하는 문장이다.
    -- NULL 을 허용한다: 의무를 강제하는 곳은 적재 경로(ingest)이지 저장소가 아니다.
    attribution TEXT
);

CREATE TABLE IF NOT EXISTS rule_draft (
    id               TEXT PRIMARY KEY,
    policy_source_id TEXT NOT NULL REFERENCES policy_source(id),
    policy_id        TEXT NOT NULL,
    status           TEXT NOT NULL
                     CHECK (status IN ('pending', 'approved', 'rejected', 'extraction_failed')),
    -- 불투명 JSON. RuleDraft 스키마는 2단계로 보류됐다 (계약 결정 #7).
    payload_json     TEXT NOT NULL,
    created_at       TEXT NOT NULL,
    failure_reason   TEXT
);

CREATE TABLE IF NOT EXISTS rule_span_mapping (
    id         TEXT PRIMARY KEY,
    draft_id   TEXT NOT NULL REFERENCES rule_draft(id),
    -- RFC 6901 JSON Pointer. RuleDraft 루트 기준 (SPEC 4.2.1).
    field_path TEXT NOT NULL,
    -- 유니코드 코드포인트 인덱스. 바이트도 UTF-16 코드유닛도 아니다. 구간은 [start_cp, end_cp).
    start_cp   INTEGER NOT NULL,
    end_cp     INTEGER NOT NULL,
    CHECK (start_cp >= 0 AND end_cp > start_cp)
);

CREATE TABLE IF NOT EXISTS rule_version (
    id              TEXT PRIMARY KEY,
    policy_id       TEXT NOT NULL,
    payload_json    TEXT NOT NULL,
    -- 판정에 참여하는가. RuleVersion 은 승인된 규칙만 담는다 (SPEC 2.2).
    status          TEXT NOT NULL CHECK (status = 'approved'),
    -- 무엇이 이것을 승인했는가. status 와는 다른 축이다 (계약 결정 #5).
    origin          TEXT NOT NULL CHECK (origin IN ('human_approval', 'seed')),
    -- NULL = 시작일 미상 / NULL = 무기한 (계약 결정 #6).
    effective_from  TEXT,
    effective_to    TEXT,
    supersedes      TEXT REFERENCES rule_version(id),
    approved_by     TEXT,
    provenance_json TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    CHECK (
        (origin = 'seed'           AND approved_by IS NULL)
     OR (origin = 'human_approval' AND approved_by IS NOT NULL)
    ),
    CHECK (effective_from IS NULL OR effective_to IS NULL OR effective_to > effective_from)
);

CREATE TABLE IF NOT EXISTS model_constant (
    key             TEXT PRIMARY KEY,
    engine          TEXT NOT NULL,
    -- NULL 허용. 인라인 리터럴로만 존재하던 값(risk.py 의 가중치·구간 경계 등)은
    -- 외부화되기 전에 **이름이 없었다.** 없는 이름을 지어내지 않는다.
    legacy_symbol   TEXT,
    spec_class      TEXT NOT NULL,
    value_type      TEXT NOT NULL,
    value_json      TEXT NOT NULL,
    provenance_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS app_user (
    id            TEXT PRIMARY KEY,
    username      TEXT NOT NULL UNIQUE,
    role          TEXT NOT NULL CHECK (role IN ('citizen', 'counselor', 'rule_manager')),
    -- 저장소에게 불투명하다. 해싱 방식(Argon2id)은 인증 계층의 결정이다 (SPEC 6.3).
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS approval_record (
    id            TEXT PRIMARY KEY,
    actor_user_id TEXT NOT NULL,
    at            TEXT NOT NULL,
    target_kind   TEXT NOT NULL,
    target_id     TEXT NOT NULL,
    decision      TEXT NOT NULL CHECK (decision IN ('approved', 'rejected')),
    reason        TEXT,
    -- SPEC 10.2 5단계 — 사유 없이 반려할 수 없다.
    CHECK (decision <> 'rejected' OR (reason IS NOT NULL AND trim(reason) <> ''))
);

-- SPEC 6.4 이상 신고. **rule_draft 와 별개 테이블이다** (계약 결정 #38).
-- 초안에 열을 더해 겸용하면 4.2 의 스키마 강제·부분 저장 금지가 사람이 낸 신고에도
-- 걸리고, 반대로 느슨하게 하면 추출 쪽 방어가 무너진다.
CREATE TABLE IF NOT EXISTS anomaly_report (
    id           TEXT PRIMARY KEY,
    -- 신고자. 익명은 없다 (SPEC 6.4). 세션의 username 이다.
    reporter     TEXT NOT NULL CHECK (trim(reporter) <> ''),
    at           TEXT NOT NULL,
    -- ★ 대상은 정책·시세 **항목**으로 한정한다 (SPEC 7.1). 자유 텍스트로 받지 않는다.
    --   항목 이름의 허용 목록은 파이썬 층이 건다 — REGION_FACT_FIELDS 를 SQL 에 다시
    --   적으면 그 목록이 두 벌이 되고, 한쪽만 늘어날 때 조용히 어긋난다.
    target_kind  TEXT NOT NULL CHECK (target_kind IN ('policy', 'region')),
    target_id    TEXT NOT NULL CHECK (trim(target_id) <> ''),
    target_field TEXT NOT NULL,
    -- 자유 입력. 파일 로그에 찍지 않는다 (SPEC 7.1).
    reason       TEXT NOT NULL CHECK (trim(reason) <> ''),
    -- 6-A 는 여는 경로만 만든다. 닫는 동작을 SPEC 이 어느 단계에도 배정하지 않았다.
    status       TEXT NOT NULL CHECK (status IN ('open', 'closed'))
);

CREATE TABLE IF NOT EXISTS audit_event (
    id          TEXT PRIMARY KEY,
    actor       TEXT NOT NULL,
    at          TEXT NOT NULL,
    action      TEXT NOT NULL,
    target      TEXT NOT NULL,
    outcome     TEXT NOT NULL,
    before_json TEXT,
    after_json  TEXT
);

CREATE INDEX IF NOT EXISTS idx_rule_version_window
    ON rule_version (status, effective_from, effective_to);
CREATE INDEX IF NOT EXISTS idx_rule_draft_status ON rule_draft (status);
CREATE INDEX IF NOT EXISTS idx_span_draft ON rule_span_mapping (draft_id);
CREATE INDEX IF NOT EXISTS idx_approval_target ON approval_record (target_id);
-- 대기 큐가 [정책이 같은 초안과 신고] 를 맞춰 본다 (SPEC 6.4 병합 — **잠정 규칙**).
CREATE INDEX IF NOT EXISTS idx_report_target ON anomaly_report (target_kind, target_id);
"""

TRIGGERS = """
-- SPEC 7.1 (b) — AuditEvent 는 append-only 다. 인터페이스를 우회해도 막힌다.
CREATE TRIGGER IF NOT EXISTS audit_event_no_update
BEFORE UPDATE ON audit_event
BEGIN
    SELECT RAISE(ABORT, 'audit_event is append-only (SPEC 7.1)');
END;

CREATE TRIGGER IF NOT EXISTS audit_event_no_delete
BEFORE DELETE ON audit_event
BEGIN
    SELECT RAISE(ABORT, 'audit_event is append-only (SPEC 7.1)');
END;

-- ★ 위 둘만으로는 **뚫린다.** `INSERT OR REPLACE` 는 충돌한 행을 지우고 새 행을 넣는데,
--   그때 생기는 삭제는 `PRAGMA recursive_triggers` 가 켜져 있을 때만 BEFORE DELETE 를
--   깨운다. 기본값은 꺼짐이므로 원시 SQL 한 줄로 감사기록이 **조용히 덮인다** (7단계 실측:
--   actor 'rulemanager' -> 'attacker' · outcome 'success' -> 'tampered', 행 수는 그대로 1).
--   pragma 로 막지 않는 이유는 그것이 **연결마다** 걸리는 설정이기 때문이다 — DB 파일을
--   직접 여는 경로를 막으려는 것이 (b) 겹의 목적인데, 그 경로는 우리 pragma 를 지나지 않는다.
--   그래서 스키마에 남는 트리거로 건다.
CREATE TRIGGER IF NOT EXISTS audit_event_no_replace
BEFORE INSERT ON audit_event
WHEN EXISTS (SELECT 1 FROM audit_event WHERE id = NEW.id)
BEGIN
    SELECT RAISE(ABORT, 'audit_event is append-only (SPEC 7.1)');
END;

-- SPEC 2.2 — RuleVersion 은 불변이다.
CREATE TRIGGER IF NOT EXISTS rule_version_no_delete
BEFORE DELETE ON rule_version
BEGIN
    SELECT RAISE(ABORT, 'rule_version is immutable (SPEC 2.2)');
END;

-- ★ `audit_event` 와 **같은 구멍이 여기에도 있었다** (7단계 실측, 범위 밖 발견).
--   `INSERT OR REPLACE` 는 충돌한 행을 지우고 새 행을 넣는데, 그때 생기는 삭제는
--   `PRAGMA recursive_triggers` 가 켜져 있을 때만 위 BEFORE DELETE 를 깨운다. 기본값은
--   꺼짐이므로 원시 SQL 한 줄로 **승인된 규칙의 payload 가 통째로 바뀌었다** —
--   시드 저장소에서 `payload_json` 이 `{"tampered": true}` 가 되고 행 수는 8 그대로였다.
--   위의 `rule_version_only_closes_once` 는 UPDATE 트리거라 이 경로를 보지 못한다.
--   0단계가 두 겹을 걸고 확인까지 했는데도 남아 있었다 — 다음 사람이 같은 함정을 밟지
--   않도록 원인을 여기 적어 둔다.
CREATE TRIGGER IF NOT EXISTS rule_version_no_replace
BEFORE INSERT ON rule_version
WHEN EXISTS (SELECT 1 FROM rule_version WHERE id = NEW.id)
BEGIN
    SELECT RAISE(ABORT, 'rule_version is immutable (SPEC 2.2)');
END;

-- 허용되는 변경은 effective_to 의 NULL -> 값 1회 전이 하나뿐이다 (계약 결정 #6).
-- 값->값 재변경도, 값->NULL 되돌리기도, 다른 컬럼 변경도 전부 여기서 멈춘다.
CREATE TRIGGER IF NOT EXISTS rule_version_only_closes_once
BEFORE UPDATE ON rule_version
WHEN OLD.effective_to IS NOT NULL
  OR NEW.effective_to IS NULL
  OR OLD.id              IS NOT NEW.id
  OR OLD.policy_id       IS NOT NEW.policy_id
  OR OLD.payload_json    IS NOT NEW.payload_json
  OR OLD.status          IS NOT NEW.status
  OR OLD.origin          IS NOT NEW.origin
  OR OLD.effective_from  IS NOT NEW.effective_from
  OR OLD.supersedes      IS NOT NEW.supersedes
  OR OLD.approved_by     IS NOT NEW.approved_by
  OR OLD.provenance_json IS NOT NEW.provenance_json
  OR OLD.created_at      IS NOT NEW.created_at
BEGIN
    SELECT RAISE(ABORT,
        'rule_version is immutable except closing effective_to once (contract #6)');
END;

-- 계약 결정 #5 의 불변식. 파이썬 층에만 두면 DB 를 직접 여는 경로로 뚫린다.
CREATE TRIGGER IF NOT EXISTS rule_version_human_approval_needs_record
BEFORE INSERT ON rule_version
WHEN NEW.origin = 'human_approval'
 AND NOT EXISTS (
     SELECT 1 FROM approval_record
      WHERE target_id = NEW.id AND decision = 'approved'
 )
BEGIN
    SELECT RAISE(ABORT,
        'rule_version origin=human_approval requires a matching ApprovalRecord (contract #5)');
END;

CREATE TRIGGER IF NOT EXISTS rule_version_seed_has_no_record
BEFORE INSERT ON rule_version
WHEN NEW.origin = 'seed'
 AND EXISTS (SELECT 1 FROM approval_record WHERE target_id = NEW.id)
BEGIN
    SELECT RAISE(ABORT,
        'rule_version origin=seed must not carry an ApprovalRecord (contract #5)');
END;
"""
