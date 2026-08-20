"""SPEC 7.1 — AuditEvent append-only 를 두 겹으로 건다.

  (a) 인터페이스가 update/delete 를 아예 노출하지 않는다   ← 매체와 무관
  (b) SQLite BEFORE UPDATE / BEFORE DELETE 트리거가 RAISE(ABORT)  ← SQLite 고유

두 겹이 **각각** 실제로 막는지를 본다. (a)만 있으면 DB 를 직접 여는 경로가 뚫려 있고,
(b)만 있으면 저장소를 교체하는 순간 보장이 사라진다. 그래서 (a)는 두 백엔드 모두에서,
(b)는 트리거를 우회할 수 있는 유일한 방법인 **원시 SQL** 로 확인한다.
"""

from __future__ import annotations

import sqlite3

import pytest
from conftest import T0, make_audit_event

from firsthome.store import create_store


# --------------------------------------------------------------------------
# (a) 인터페이스 층 — 두 백엔드 공통
# --------------------------------------------------------------------------

FORBIDDEN = ("update", "delete", "remove", "set_", "edit", "purge", "clear", "truncate")


def test_audit_log_exposes_no_mutation_method(store):
    """노출된 공개 메서드에 수정·삭제 계열 이름이 하나도 없어야 한다."""
    public = [name for name in dir(store.audit) if not name.startswith("_")]
    offenders = [n for n in public if any(bad in n.lower() for bad in FORBIDDEN)]
    assert not offenders, f"AuditEvent 에 수정·삭제 경로가 노출됐다: {offenders}"
    assert set(public) == {"append", "list"}, f"예상 밖의 공개 메서드: {sorted(public)}"


def test_audit_events_can_be_appended_and_read_back(store):
    store.audit.append(make_audit_event("ae-1", action="rule.approve"))
    store.audit.append(make_audit_event("ae-2", action="auth.login_failed"))

    assert [e.id for e in store.audit.list()] == ["ae-1", "ae-2"]
    assert [e.id for e in store.audit.list(action="auth.login_failed")] == ["ae-2"]


def test_returned_audit_events_do_not_write_back_into_the_store(store):
    """반환된 객체를 고쳐도 저장소는 그대로여야 한다 (불변 dataclass)."""
    store.audit.append(make_audit_event("ae-1", outcome="success"))
    event = store.audit.list()[0]

    with pytest.raises(Exception):
        event.outcome = "tampered"  # type: ignore[misc]

    assert store.audit.list()[0].outcome == "success"


# --------------------------------------------------------------------------
# (b) SQLite 트리거 층 — 인터페이스를 우회해 원시 SQL 로 때린다
# --------------------------------------------------------------------------


def _raw(url: str) -> sqlite3.Connection:
    return sqlite3.connect(url.split("://", 1)[1])


def test_raw_sql_update_of_audit_event_is_aborted(sqlite_url):
    with create_store(sqlite_url) as store:
        store.audit.append(make_audit_event("ae-1", outcome="success"))

    conn = _raw(sqlite_url)
    try:
        with pytest.raises(sqlite3.IntegrityError) as err:
            conn.execute("UPDATE audit_event SET outcome = 'tampered' WHERE id = 'ae-1'")
            conn.commit()
        assert "append-only" in str(err.value)
        assert conn.execute("SELECT outcome FROM audit_event WHERE id='ae-1'").fetchone()[0] == "success"
    finally:
        conn.close()


def test_raw_sql_delete_of_audit_event_is_aborted(sqlite_url):
    with create_store(sqlite_url) as store:
        store.audit.append(make_audit_event("ae-1"))

    conn = _raw(sqlite_url)
    try:
        with pytest.raises(sqlite3.IntegrityError) as err:
            conn.execute("DELETE FROM audit_event WHERE id = 'ae-1'")
            conn.commit()
        assert "append-only" in str(err.value)
        assert conn.execute("SELECT COUNT(*) FROM audit_event").fetchone()[0] == 1
    finally:
        conn.close()


def test_raw_sql_cannot_wipe_the_whole_audit_table(sqlite_url):
    """건별이 아니라 통째로 지우는 시도도 같은 트리거에 걸려야 한다."""
    with create_store(sqlite_url) as store:
        for i in range(3):
            store.audit.append(make_audit_event(f"ae-{i}"))

    conn = _raw(sqlite_url)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM audit_event")
            conn.commit()
        assert conn.execute("SELECT COUNT(*) FROM audit_event").fetchone()[0] == 3
    finally:
        conn.close()


#: `INSERT OR REPLACE` 계열의 전수. 셋 다 **같은 구멍**을 지난다 —
#: 충돌한 행을 지우고 새 행을 넣는데, 그 삭제는 `PRAGMA recursive_triggers` 가 켜져
#: 있을 때만 BEFORE DELETE 를 깨운다. 기본값은 꺼짐이다.
_REPLACE_STATEMENTS = (
    "INSERT OR REPLACE INTO audit_event"
    " (id, actor, at, action, target, outcome, before_json, after_json)"
    " VALUES ('ae-1', 'attacker', '2026-01-01T00:00:00+00:00', 'x', 'y', 'tampered', NULL, NULL)",
    "REPLACE INTO audit_event"
    " (id, actor, at, action, target, outcome, before_json, after_json)"
    " VALUES ('ae-1', 'attacker', '2026-01-01T00:00:00+00:00', 'x', 'y', 'tampered', NULL, NULL)",
    "INSERT OR IGNORE INTO audit_event"
    " (id, actor, at, action, target, outcome, before_json, after_json)"
    " VALUES ('ae-1', 'attacker', '2026-01-01T00:00:00+00:00', 'x', 'y', 'tampered', NULL, NULL)",
)


@pytest.mark.parametrize("statement", _REPLACE_STATEMENTS)
def test_raw_sql_cannot_overwrite_an_audit_event_by_replacing_it(sqlite_url, statement):
    """★ **UPDATE 와 DELETE 를 막는 것만으로는 부족하다** (7단계 실측).

    7단계 착수 시점에 이 저장소는 `INSERT OR REPLACE` 한 줄로 뚫렸다 — 감사 행 하나의
    `actor` 가 `rulemanager` 에서 `attacker` 로, `outcome` 이 `success` 에서 `tampered`
    로 바뀌었고 **행 수는 1 그대로였다.** 세는 것으로는 보이지 않는 종류의 위조다.

    막는 자리를 pragma 가 아니라 **스키마**로 고른 이유: `recursive_triggers` 는
    연결마다 걸리는 설정이고, (b) 겹이 막으려는 것은 애초에 DB 파일을 **직접 여는**
    경로다. 그 경로는 우리 pragma 를 지나지 않는다.

    `INSERT OR IGNORE` 도 같이 막는다. 그쪽은 덮어쓰지 않지만 **조용히 사라진다** —
    남았다고 믿는데 안 남은 것이 감사기록에서는 덮어쓰기만큼 나쁘다.
    """
    with create_store(sqlite_url) as store:
        store.audit.append(make_audit_event("ae-1", actor="rulemanager", outcome="success"))

    conn = _raw(sqlite_url)
    try:
        with pytest.raises(sqlite3.IntegrityError) as err:
            conn.execute(statement)
            conn.commit()
        assert "append-only" in str(err.value)
        conn.rollback()
        row = conn.execute("SELECT actor, outcome FROM audit_event WHERE id='ae-1'").fetchone()
        assert tuple(row) == ("rulemanager", "success")
        assert conn.execute("SELECT COUNT(*) FROM audit_event").fetchone()[0] == 1
    finally:
        conn.close()


def test_appending_a_new_audit_event_still_works_after_the_replace_guard(sqlite_url):
    """막는 것만 하고 통과시키지 못하면 그 트리거는 저장소를 세운 것이다."""
    with create_store(sqlite_url) as store:
        store.audit.append(make_audit_event("ae-1"))
        store.audit.append(make_audit_event("ae-2"))
        assert [e.id for e in store.audit.list()] == ["ae-1", "ae-2"]


def test_both_triggers_exist_on_the_audit_table(sqlite_url):
    with create_store(sqlite_url):
        pass
    conn = _raw(sqlite_url)
    try:
        rows = conn.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='trigger' AND tbl_name='audit_event'"
        ).fetchall()
        sql = " ".join(r[1] for r in rows)
        assert "BEFORE UPDATE" in sql and "BEFORE DELETE" in sql, rows
        assert sql.count("RAISE(ABORT") >= 2, rows
    finally:
        conn.close()


def test_audit_rejects_naive_timestamps(store):
    """오프셋 없는 시각은 감사기록의 순서를 조용히 망가뜨린다 (SPEC 2.1)."""
    from firsthome.store.errors import StoreError

    naive = make_audit_event("ae-1", at=T0.replace(tzinfo=None))
    with pytest.raises(StoreError):
        store.audit.append(naive)
