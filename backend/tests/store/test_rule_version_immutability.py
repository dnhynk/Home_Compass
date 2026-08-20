"""SPEC 2.2 — `RuleVersion` 은 불변이고, `supersedes` 로 이력을 잇는다.

'불변' 을 '아무것도 못 바꾼다' 로 읽으면 `effective_to` 를 닫을 수 없어 2.3 술어가
성립하지 않는다. 그래서 허용되는 변경은 **`effective_to` 를 NULL -> 값으로 한 번 닫는 것**
하나뿐이고, 나머지는 전부 막는다 (코디네이터 8.2 결정).

`origin` 은 무엇이 이 규칙을 승인했는가의 판별자다 (코디네이터 8.2 결정).
`approved_by=NULL` 하나로는 '사람 승인이 아님' 과 '승인자 기록 버그' 가 구분되지 않는다.
"""

from __future__ import annotations

import sqlite3
from datetime import timedelta

import pytest
from conftest import T0, make_approval, make_rule_version

from firsthome.store import create_store
from firsthome.store.errors import StoreError


def _raw(url: str) -> sqlite3.Connection:
    return sqlite3.connect(url.split("://", 1)[1])


# --------------------------------------------------------------------------
# origin 불변식
# --------------------------------------------------------------------------


def test_human_approval_without_an_approver_is_rejected(store):
    with pytest.raises(StoreError):
        store.rule_versions.add(
            make_rule_version("rv-1", origin="human_approval", approved_by=None)
        )
    assert store.rule_versions.list() == []


def test_human_approval_without_an_approval_record_is_rejected(store):
    """승인자 이름만 적고 승인 기록이 없으면 그것은 승인이 아니다."""
    with pytest.raises(StoreError):
        store.rule_versions.add(
            make_rule_version("rv-1", origin="human_approval", approved_by="u-1")
        )
    assert store.rule_versions.list() == []


def test_human_approval_with_a_matching_record_is_accepted(store):
    store.approvals.add(make_approval("ap-1", target_kind="rule_version", target_id="rv-1"))
    store.rule_versions.add(make_rule_version("rv-1", origin="human_approval", approved_by="u-1"))

    stored = store.rule_versions.get("rv-1")
    assert stored.origin == "human_approval"
    assert stored.approved_by == "u-1"


def test_a_rejection_record_does_not_count_as_an_approval(store):
    store.approvals.add(
        make_approval(
            "ap-1", target_kind="rule_version", target_id="rv-1",
            decision="rejected", reason="소득 요건 구간이 원문과 다릅니다",
        )
    )
    with pytest.raises(StoreError):
        store.rule_versions.add(
            make_rule_version("rv-1", origin="human_approval", approved_by="u-1")
        )


def test_seed_origin_must_not_name_an_approver(store):
    """시드 데이터에 승인자를 적는 것은 감사기록 날조다."""
    with pytest.raises(StoreError):
        store.rule_versions.add(make_rule_version("rv-1", origin="seed", approved_by="u-1"))


def test_seed_origin_must_not_carry_an_approval_record(store):
    store.approvals.add(make_approval("ap-1", target_kind="rule_version", target_id="rv-1"))
    with pytest.raises(StoreError):
        store.rule_versions.add(make_rule_version("rv-1", origin="seed", approved_by=None))


def test_an_unknown_origin_is_rejected(store):
    with pytest.raises(StoreError):
        store.rule_versions.add(make_rule_version("rv-1", origin="automatic"))


# --------------------------------------------------------------------------
# 인터페이스 층 — 수정 경로가 없다
# --------------------------------------------------------------------------


def test_rule_version_repository_exposes_no_generic_update(store):
    public = {n for n in dir(store.rule_versions) if not n.startswith("_")}
    assert public == {"add", "get", "list", "supersede", "active"}, sorted(public)


def test_adding_the_same_id_twice_is_rejected(store):
    store.rule_versions.add(make_rule_version("rv-1"))
    with pytest.raises(StoreError):
        store.rule_versions.add(make_rule_version("rv-1", payload={"tampered": True}))
    assert store.rule_versions.get("rv-1").payload == {"id": "buttress_youth", "maxAmountKRW": 200_000_000}


def test_a_closed_version_cannot_be_closed_again(store):
    store.rule_versions.add(make_rule_version("rv-1", effective_from=T0))
    cutover = T0 + timedelta(days=10)
    store.rule_versions.supersede(
        "rv-1", make_rule_version("rv-2", effective_from=cutover, supersedes="rv-1"), at=cutover
    )

    with pytest.raises(StoreError):
        store.rule_versions.supersede(
            "rv-1",
            make_rule_version("rv-3", effective_from=cutover + timedelta(days=1), supersedes="rv-1"),
            at=cutover + timedelta(days=1),
        )
    assert store.rule_versions.get("rv-1").effective_to == cutover


def test_supersede_is_atomic_when_the_new_version_is_invalid(store):
    """새 버전이 거부되면 이전 버전도 닫히면 안 된다 — 아니면 활성 규칙이 0개가 된다."""
    store.rule_versions.add(make_rule_version("rv-1", effective_from=None))
    cutover = T0 + timedelta(days=10)

    with pytest.raises(StoreError):
        store.rule_versions.supersede(
            "rv-1",
            make_rule_version("rv-2", effective_from=cutover, origin="human_approval", approved_by=None),
            at=cutover,
        )

    assert store.rule_versions.get("rv-1").effective_to is None
    assert [v.id for v in store.rule_versions.active(cutover)] == ["rv-1"]


# --------------------------------------------------------------------------
# SQLite 트리거 층 — 인터페이스를 우회한 원시 SQL
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "column, value",
    [
        ("payload_json", '{"tampered": true}'),
        ("policy_id", "some_other_policy"),
        ("status", "pending"),
        ("origin", "human_approval"),
        ("effective_from", "2020-01-01T00:00:00+09:00"),
        ("supersedes", "rv-99"),
        ("approved_by", "u-9"),
    ],
)
def test_raw_sql_cannot_change_any_column_other_than_effective_to(sqlite_url, column, value):
    with create_store(sqlite_url) as store:
        store.rule_versions.add(make_rule_version("rv-1", effective_from=T0))

    conn = _raw(sqlite_url)
    try:
        with pytest.raises(sqlite3.IntegrityError) as err:
            conn.execute(f"UPDATE rule_version SET {column} = ? WHERE id = 'rv-1'", (value,))
            conn.commit()
        assert "immutable" in str(err.value).lower()
    finally:
        conn.close()


def test_raw_sql_cannot_delete_a_rule_version(sqlite_url):
    with create_store(sqlite_url) as store:
        store.rule_versions.add(make_rule_version("rv-1"))

    conn = _raw(sqlite_url)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM rule_version WHERE id = 'rv-1'")
            conn.commit()
        assert conn.execute("SELECT COUNT(*) FROM rule_version").fetchone()[0] == 1
    finally:
        conn.close()


def test_raw_sql_may_close_effective_to_exactly_once(sqlite_url):
    """허용되는 유일한 변경 — NULL -> 값."""
    with create_store(sqlite_url) as store:
        store.rule_versions.add(make_rule_version("rv-1", effective_from=T0, effective_to=None))

    conn = _raw(sqlite_url)
    try:
        conn.execute("UPDATE rule_version SET effective_to = ? WHERE id='rv-1'", ("2026-09-13T09:00:00+09:00",))
        conn.commit()
        assert conn.execute("SELECT effective_to FROM rule_version").fetchone()[0]
    finally:
        conn.close()


def test_raw_sql_cannot_rewrite_a_closed_effective_to(sqlite_url):
    """값 -> 값 재변경. 이미 닫힌 창을 뒤에서 늘리면 지난 판정의 근거가 바뀐다."""
    with create_store(sqlite_url) as store:
        store.rule_versions.add(
            make_rule_version("rv-1", effective_from=T0, effective_to=T0 + timedelta(days=1))
        )

    conn = _raw(sqlite_url)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE rule_version SET effective_to = ? WHERE id='rv-1'", ("2099-01-01T00:00:00+09:00",))
            conn.commit()
    finally:
        conn.close()


def test_raw_sql_cannot_reopen_a_closed_effective_to(sqlite_url):
    """값 -> NULL 되돌리기. 종료된 규칙을 조용히 되살리는 경로다."""
    with create_store(sqlite_url) as store:
        store.rule_versions.add(
            make_rule_version("rv-1", effective_from=T0, effective_to=T0 + timedelta(days=1))
        )

    conn = _raw(sqlite_url)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE rule_version SET effective_to = NULL WHERE id='rv-1'")
            conn.commit()
    finally:
        conn.close()


#: 충돌한 행을 지우고 새 행을 넣는 계열 전수. `INSERT OR IGNORE` 는 덮어쓰지 않지만
#: **조용히 사라지므로** 같이 막는다 — 승인이 남았다고 믿는데 안 남은 것이 규칙 저장소에서는
#: 덮어쓰기만큼 나쁘다.
_REPLACE_VERBS = ("INSERT OR REPLACE", "REPLACE", "INSERT OR IGNORE")


@pytest.mark.parametrize("verb", _REPLACE_VERBS)
def test_raw_sql_cannot_overwrite_a_rule_version_by_replacing_it(sqlite_url, verb):
    """★ **DELETE 와 UPDATE 를 막는 것만으로는 부족했다** (7단계 실측 · 범위 밖 발견).

    `INSERT OR REPLACE` 는 충돌 행을 지우고 새 행을 넣는데, 그 삭제는
    `PRAGMA recursive_triggers` 가 켜져 있을 때만 BEFORE DELETE 를 깨운다. 기본값은
    꺼짐이라 **승인된 규칙의 `payload_json` 이 통째로 바뀌었다** — 시드 저장소에서
    `{"tampered": true}` 가 되고 행 수는 8 그대로였다. 세는 것으로는 보이지 않는 위조다.

    `rule_version_only_closes_once` 는 UPDATE 트리거라 이 경로를 보지 못하고,
    `rule_version_no_delete` 는 위 이유로 안 깨어난다. 그래서 세 번째 트리거가 있다.

    막는 자리를 pragma 가 아니라 **스키마**로 고른 이유: `recursive_triggers` 는 연결마다
    걸리는 설정이고, 트리거 겹이 막으려는 것은 애초에 DB 파일을 **직접 여는** 경로다.
    """
    with create_store(sqlite_url) as store:
        store.rule_versions.add(make_rule_version("rv-1", effective_from=T0))

    conn = _raw(sqlite_url)
    try:
        columns = [row[1] for row in conn.execute("PRAGMA table_info(rule_version)")]
        original = dict(zip(columns, conn.execute(
            "SELECT * FROM rule_version WHERE id='rv-1'").fetchone()))
        tampered = dict(original, payload_json='{"tampered": true}')

        statement = (f"{verb} INTO rule_version ({', '.join(columns)})"
                     f" VALUES ({', '.join('?' * len(columns))})")
        with pytest.raises(sqlite3.IntegrityError) as err:
            conn.execute(statement, [tampered[name] for name in columns])
            conn.commit()
        assert "immutable" in str(err.value).lower()
        conn.rollback()

        assert conn.execute(
            "SELECT payload_json FROM rule_version WHERE id='rv-1'"
        ).fetchone()[0] == original["payload_json"]
        assert conn.execute("SELECT COUNT(*) FROM rule_version").fetchone()[0] == 1
    finally:
        conn.close()


def test_adding_a_new_rule_version_still_works_after_the_replace_guard(store):
    """막는 것만 하고 통과시키지 못하면 그 트리거는 저장소를 세운 것이다.

    `supersede` 는 이전 행을 **UPDATE 로 닫고** 새 id 로 INSERT 하므로 이 트리거를
    지나지 않는다 — 그 사실을 여기서 실제로 확인한다.
    """
    store.rule_versions.add(make_rule_version("rv-1", effective_from=T0))
    cutover = T0 + timedelta(days=10)
    store.rule_versions.supersede(
        "rv-1", make_rule_version("rv-2", effective_from=cutover, supersedes="rv-1"),
        at=cutover,
    )
    assert [v.id for v in store.rule_versions.list()] == ["rv-1", "rv-2"]
    assert [v.id for v in store.rule_versions.active(cutover)] == ["rv-2"]


def test_raw_sql_cannot_insert_a_human_approval_without_a_record(sqlite_url):
    """제약이 파이썬 층에만 있으면 DB 를 직접 여는 경로로 뚫린다."""
    with create_store(sqlite_url):
        pass

    conn = _raw(sqlite_url)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO rule_version (id, policy_id, payload_json, status, origin,"
                " effective_from, effective_to, supersedes, approved_by, provenance_json, created_at)"
                " VALUES ('rv-x','p','{}','approved','human_approval',NULL,NULL,NULL,'u-1','{}',"
                "'2026-08-13T00:00:00+00:00')"
            )
            conn.commit()
    finally:
        conn.close()
