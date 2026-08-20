"""`AuditLog.list` 의 순서 계약 — **시각순이고, 동시각 안에서만 기록순이다.**

## 왜 별도 파일인가

`test_audit_append_only.py` 는 [행을 고칠 수 없다] 를 잰다. 여기서 재는 것은 그 보장이
**무엇을 보장하지 않는가** 다. 둘은 반대 방향이라 한 파일에 두면 읽는 사람이 두 번째를
첫 번째의 따름정리로 읽는다 — 그 오독이 바로 이 결함을 만들었다.

## 무엇이 틀려 있었나

`sqlite_store` 의 주석은 「rowid 순 = 기록 순. append-only 이므로 둘이 어긋날 수 없다」
였다. 앞 문장은 참이고 **뒷 문장이 거짓**이다. append-only 가 막는 것은 [행을 고치는
것]이지 [지난 시각의 행을 나중에 붙이는 것]이 아니다.

그리고 어긋날 때 값을 잘못 읽는 호출자가 실재한다 — `main.build_batch_status` 는 이
목록의 **마지막 원소**를 「마지막 배치 실행」이라 부르고, `/api/health` 는 그것을
`lastRunAt` · `lastOutcome` 두 칸으로만 싣는다. 어긋나도 화면에 단서가 없다.

## 상황을 만드는 방법이 하나뿐인 이유

`AuditEvent` 는 append-only 라 **행을 고쳐서는 만들 수 없다.** 시각이 뒤인 것을 먼저
넣고 앞인 것을 나중에 넣는 것 — 즉 **삽입 순서로만** 갈리게 할 수 있다. 아래 검사들이
전부 그 형태인 이유이며, 이것은 지어낸 상황이 아니다. 시드가 실행 기록을 나중에
넣거나, 두 프로세스가 순서를 섞어 쓰거나, 배치가 지난 시각으로 기록을 남기면 그대로
일어난다.

## 두 백엔드에서 잰다

`store` 픽스처가 SQLite 와 메모리 백엔드로 파라미터화돼 있다. 순서는 SQLite 의 성질이
아니라 **계약**이므로(부록 A) 한쪽에서만 참이면 그것은 계약이 아니다.
"""

from __future__ import annotations

from datetime import timedelta, timezone

from conftest import T0, make_audit_event

RUN = "market.run"


# --------------------------------------------------------------------------
# 1. ★ 삽입순과 시각순이 갈리는 상황 — 이 파일의 이유
# --------------------------------------------------------------------------


def test_an_event_written_later_for_an_earlier_time_sorts_earlier(store):
    """뒤에 쓴 것이 곧 나중에 일어난 것은 아니다.

    `rowid` 순이면 `["late-write", "early-time"]` 이 나온다. 시각순이면 뒤집힌다.
    """
    store.audit.append(make_audit_event("later-run", at=T0))
    store.audit.append(make_audit_event("earlier-run", at=T0 - timedelta(days=2)))

    assert [e.id for e in store.audit.list()] == ["earlier-run", "later-run"]


def test_the_last_element_is_the_latest_event_not_the_last_written(store):
    """★ **호출자가 실제로 하는 일이 이것이다** (`main.build_batch_status`).

    목록의 마지막을 「마지막 사건」이라 부르는 코드가 있는 한, 이 단정이 그 코드의
    전제를 저장소 쪽에서 지고 있는 것이다.
    """
    store.audit.append(make_audit_event("run-b", at=T0, outcome="success"))
    store.audit.append(make_audit_event("run-a", at=T0 - timedelta(hours=1), outcome="failed"))

    last = store.audit.list()[-1]
    assert (last.id, last.at, last.outcome) == ("run-b", T0, "success")


def test_the_action_filter_keeps_the_same_order(store):
    """걸러진 조회도 같은 순서다.

    SQLite 쪽은 이 둘이 **서로 다른 SQL 문**이라 한쪽만 고치면 조용히 갈린다.
    그리고 `lastRunAt` 이 지나는 경로는 걸러진 쪽이다.
    """
    store.audit.append(make_audit_event("run-late", at=T0, action=RUN))
    store.audit.append(make_audit_event("noise", at=T0 + timedelta(days=1), action="auth.login"))
    store.audit.append(make_audit_event("run-early", at=T0 - timedelta(days=3), action=RUN))

    assert [e.id for e in store.audit.list(action=RUN)] == ["run-early", "run-late"]


def test_a_seeded_record_written_first_does_not_win_the_last_slot(store):
    """시드가 실행 기록을 **먼저** 넣는 경우 — 과업이 지목한 세 갈래 중 하나.

    시드는 고정 시각을 쓰고 실기동은 그때의 시각을 쓴다. 시드 쪽이 뒤 시각을 갖는
    저장소가 만들어지면 삽입순은 [시드가 마지막] 이라고 답한다.
    """
    store.audit.append(make_audit_event("seed-run", at=T0 + timedelta(days=30), action=RUN))
    store.audit.append(make_audit_event("real-run", at=T0, action=RUN))

    assert store.audit.list(action=RUN)[-1].id == "seed-run"


# --------------------------------------------------------------------------
# 2. 동률의 순서 — 보조 키가 `rowid` 여야 하는 이유
# --------------------------------------------------------------------------


def test_events_at_the_same_instant_keep_the_order_they_were_written_in(store):
    """★ 한 배치 실행은 지역별 행과 실행 행을 **같은 `now`** 로 쓴다.

    그래서 동률이 예외가 아니라 **정상 경로**다. 여기서 순서를 정해 두지 않으면
    `tests/ingest/test_batch_run_record.py` 의 [실행 행이 지역별 행 뒤에 온다] 가
    실행마다 흔들린다 — 시각순만으로 고치면 그 기록의 뜻이 사라진다.
    """
    for index in range(5):
        store.audit.append(make_audit_event(f"same-{index}", at=T0))

    assert [e.id for e in store.audit.list()] == [f"same-{i}" for i in range(5)]


def test_a_tie_does_not_reorder_across_the_events_around_it(store):
    """동률 묶음이 시각순 안에서 제자리를 지킨다."""
    store.audit.append(make_audit_event("tie-b", at=T0))
    store.audit.append(make_audit_event("after", at=T0 + timedelta(minutes=1)))
    store.audit.append(make_audit_event("tie-a", at=T0))
    store.audit.append(make_audit_event("before", at=T0 - timedelta(minutes=1)))

    assert [e.id for e in store.audit.list()] == ["before", "tie-b", "tie-a", "after"]


# --------------------------------------------------------------------------
# 3. 정렬의 전제 — SQLite 는 `at` 을 **문자열로** 정렬한다
# --------------------------------------------------------------------------
#
# `ORDER BY at` 이 시각 정렬인 것은 `_dt_out` 이 UTC 정규화 RFC 3339 로 적기 때문이다.
# 그 전제가 깨지면 정렬은 조용히 틀린다 — 예외도 빈 값도 나지 않는다. 그래서 전제
# 자체를 검사로 적어 둔다. 메모리 백엔드는 datetime 을 그대로 비교하므로 이 검사들이
# 재는 것은 **두 백엔드가 같은 답을 내는가** 이기도 하다.


def test_a_different_offset_is_compared_as_an_instant_not_as_text(store):
    """오프셋이 다른 두 시각이 **문자열 생김새**로 갈리지 않는다.

    `T0` 은 KST 09:00 = UTC 00:00 이다. 여기 넣는 UTC 01:00 은 문자열로 보면
    `01:00...` 이라 `09:00...` 보다 작지만 **시각으로는 뒤**다. UTC 정규화 없이
    문자열만 정렬하면 이 검사가 뒤집힌다.
    """
    store.audit.append(make_audit_event("utc-later", at=T0.astimezone(timezone.utc)
                                        + timedelta(hours=1)))
    store.audit.append(make_audit_event("kst-earlier", at=T0))

    assert [e.id for e in store.audit.list()] == ["kst-earlier", "utc-later"]


def test_a_sub_second_difference_still_sorts_the_right_way(store):
    """마이크로초가 있는 시각과 없는 시각이 섞여도 순서가 맞는다.

    `datetime.isoformat()` 은 마이크로초가 0 이면 그 자리를 **아예 적지 않는다.**
    두 형태가 한 열에 섞이는데, 그때도 문자열 순서가 시각 순서와 같아야 한다.
    """
    store.audit.append(make_audit_event("just-after", at=T0 + timedelta(microseconds=1)))
    store.audit.append(make_audit_event("exactly-t0", at=T0))

    assert [e.id for e in store.audit.list()] == ["exactly-t0", "just-after"]
