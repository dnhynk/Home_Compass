"""SPEC 4.6 — `pending -> 결정` 은 **단일 전이**다 (소유자: `store`).

원자화 지점이 여기인 이유는 부록 A 다. 검사를 API 계층에 두면 저장소를 갈아 끼우는 순간
보장이 사라지고, 그때 [승인은 한 번만 일어난다] 는 코드가 아니라 규율이 된다. 그래서
`RuleDraftRepository.claim_pending` 이 계약을 지고, **두 백엔드가 같은 계약 테스트를
통과해야** 그 주장이 성립한다 (`test_backend_swap.py` 와 같은 논법).

**이 파일의 지배적 실패 양상은 [경합을 흉내 냈다고 믿는 것]이다.** 스레드를 띄웠는데 실은
직렬로 돌았다면 초록불은 원자화의 증거가 아니라 흉내가 실패했다는 증거다.

그래서 **대조군을 테스트 안에 넣는다.** 같은 하네스로 [원자화 이전의 형태](읽고 나서 쓴다)를
돌려 **이중 선점이 실제로 나오는지**를 먼저 확인하고, 그 다음에 `claim_pending` 을 돌린다.
대조군이 한 번도 안 깨지면 하네스가 경합을 못 만든 것이므로 그 자리에서 실패한다. 이렇게
두면 반증 관측이 PR 본문에 한 번 적히고 마는 것이 아니라 **테스트로 남는다.**

★ **경합을 운에 맡기지 않는다.** 앞선 판은 GIL 스위치 간격을 줄여 감도를 만들었는데, 그것이
만든 것은 감도가 아니라 확률이었다. 같은 윈도우 기계에서 잰 대조군 검출률 —

    switchinterval   5e-3    1e-3    1e-4    1e-5    1e-6
    이중 선점        0/40    0/40   24/40   28/40   32/40

손잡이 하나로 0 에서 32 까지 움직인다. 리눅스 CI 가 같은 `1e-6` 에서 0/12 를 뽑아 빨간불이
난 것은 이상 동작이 아니라 **이 분포에서 다른 값이 뽑힌 것**이다. 스케줄러가 다르면 분포도
다르므로, 확률에 기댄 하네스는 어느 플랫폼에서든 언제든 0 을 뽑을 수 있다.

지금 하네스는 대신 **저장소 호출 사이에 보조를 맞춘다** — 한 스레드가 다음 호출을 시작하기
전에 모든 스레드가 현재 호출을 마친다. 이 규칙은 두 변종에 **똑같이** 걸리고, 결과가 갈리는
것은 하네스가 아니라 구현의 모양 때문이다.

  - 대조군은 [읽기]와 [쓰기] 가 **두 호출**이라 그 사이에 걸 자리가 있다. 여덟이 전부
    `pending` 을 읽은 **뒤에야** 쓰기가 시작되므로 이중 선점은 매 회차 8/8 로 난다.
  - `claim_pending` 은 **한 호출**이라 그 자리가 없다 — 그리고 자리가 없다는 것이 곧
    시험 대상이다. 그래서 메모리 백엔드에서는 `_ClaimRaceGate` 를 임계구역 **안**에 걸어
    [읽었고 아직 안 썼다] 가 둘 이상 겹칠 수 있는지를 직접 붙잡는다. 겹칠 수 있으면
    붙잡혀서 **반드시** 겹치고, 겹칠 수 없으면 기다림 없이 통과한다 (게이트 설명 참고).

SQLite 에는 게이트를 걸지 않는다. 거기서 임계구역은 조건부 UPDATE **한 문장**이고, 그 안에
손을 넣으려면 제품 코드가 테스트를 알아야 한다. 그럴 필요도 없다 — 직렬화를 DB 잠금이 지고
구간이 밀리초라 스케줄러와 무관하게 겹친다.

시각 구간이 겹치는지로 재지 않는 이유는 재 봤기 때문이다 (측정값은 PR 본문에 있다) —
SQLite 는 40/40 으로 겹치지만 메모리 백엔드의 임계구역은 마이크로초라 스레드 기동 편차에
묻혀 0/40 이다. 겹침은 SQLite 에서만 성립하는 지표이고, 그것을 두 백엔드 공통 지표로 쓰면
메모리 쪽이 늘 빨간불이거나(엄격) 아무것도 안 잡거나(느슨) 둘 중 하나가 된다.

`conftest.py` 의 `store` 픽스처를 쓰지 않는 이유는 아래 `handles` 픽스처 설명에 있다.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Callable

import pytest
from conftest import make_draft, make_policy_source
from memory_backend import NO_CLAIM_GATE

from home_compass.store import create_store
from home_compass.store.errors import (
    DraftAlreadyDecidedError,
    RecordNotFoundError,
    StoreError,
)
from home_compass.store.interfaces import Store

#: 같은 초안에 동시에 달려드는 시도 수. 2 로는 인터리빙이 운에 좌우된다.
CLAIMERS = 8

#: 경합을 반복하는 횟수. 결과가 결정론적이면 한 회차로 족하지만, 회차를 남겨 두면
#: **N/N 이 아닌 순간**이 곧 [하네스가 다시 운에 기대기 시작했다] 는 신호가 된다.
ROUNDS = 12


@pytest.fixture(params=["sqlite", "memory"])
def handles(request, tmp_path):
    """같은 저장소를 가리키는 **핸들 여러 개**를 준다.

    `conftest.py` 의 `store` 픽스처는 핸들 하나를 준다. 그것으로는 SQLite 의 경합을 흉내
    낼 수 없다 — `sqlite3` 커넥션은 만든 스레드에 묶여 있어(`check_same_thread`) 다른
    스레드가 쓰면 경합이 아니라 `ProgrammingError` 가 난다.

    그래서 매체별로 [같은 저장소를 여럿이 본다] 의 실제 모양을 그대로 쓴다 —

      - SQLite: 스레드마다 새로 연다. `main.py` 가 **요청마다** `store_from_env()` 를
        부르므로 이것이 운영과 같은 모양이다. 직렬화는 GIL 이 아니라 DB 잠금이 한다.
        연 스레드가 직접 닫는다 — 커넥션은 만든 스레드에 묶여 있다.
      - 메모리: 프로세스 안의 딕셔너리 하나가 곧 저장소이므로 같은 객체를 나눠 쓴다.
        여기서는 GIL 이 유일한 스케줄러이고, 그래서 이 백엔드는 잠금을 스스로 져야 한다.

    돌려주는 것은 `(기준 핸들, 새 핸들을 여는 함수, 스레드가 핸들을 닫아야 하는가)` 다.
    """
    if request.param == "sqlite":
        url = f"sqlite://{tmp_path / 'claim.db'}"
        with create_store(url) as primary:
            yield primary, (lambda: create_store(url)), True
    else:
        with create_store(f"memory://{request.node.name}") as primary:
            yield primary, (lambda: primary), False


def seed_draft(store: Store, draft_id: str) -> str:
    if store.policy_sources.get("src-1") is None:
        store.policy_sources.add(make_policy_source("src-1"))
    store.rule_drafts.add(make_draft(draft_id))
    return draft_id


# --------------------------------------------------------------------------
# 순차 계약 — 두 번째는 거부된다
# --------------------------------------------------------------------------

def test_the_first_claim_moves_the_draft(handles):
    store, _, _ = handles
    seed_draft(store, "draft-1")
    claimed = store.rule_drafts.claim_pending("draft-1", "approved")
    assert claimed.status == "approved"
    assert store.rule_drafts.get("draft-1").status == "approved"


def test_the_second_claim_is_refused(handles):
    """★ SPEC 4.6 — 두 번째 시도는 **실패** 한다."""
    store, _, _ = handles
    seed_draft(store, "draft-1")
    store.rule_drafts.claim_pending("draft-1", "approved")
    with pytest.raises(DraftAlreadyDecidedError):
        store.rule_drafts.claim_pending("draft-1", "rejected")
    assert store.rule_drafts.get("draft-1").status == "approved"


def test_an_unknown_draft_is_not_found_not_already_decided(handles):
    """404 와 409 가 갈려야 API 가 다시 상태를 읽지 않아도 답을 만들 수 있다."""
    store, _, _ = handles
    with pytest.raises(RecordNotFoundError):
        store.rule_drafts.claim_pending("draft-missing", "approved")


def test_claiming_into_pending_is_refused(handles):
    """`pending -> pending` 은 전이가 아니다. 허용하면 선점이 무한히 반복된다."""
    store, _, _ = handles
    seed_draft(store, "draft-1")
    with pytest.raises(StoreError):
        store.rule_drafts.claim_pending("draft-1", "pending")
    assert store.rule_drafts.get("draft-1").status == "pending"


def test_a_failure_reason_rides_along(handles):
    """추출 실패 경로도 같은 전이를 쓴다 — 사유가 실려야 검토 큐가 이유를 말할 수 있다."""
    store, _, _ = handles
    seed_draft(store, "draft-1")
    claimed = store.rule_drafts.claim_pending(
        "draft-1", "extraction_failed", failure_reason="span 검증 실패"
    )
    assert claimed.failure_reason == "span 검증 실패"


# --------------------------------------------------------------------------
# ★ 동시 실행 — 흉내가 성립했는지까지 관측한다
# --------------------------------------------------------------------------

class _ClaimRaceGate:
    """`claim_pending` 의 [읽었다] 와 [썼다] 사이를 **강제로 벌린다.**

    읽기를 마친 스레드는 [다른 선점자가 아직 이 창에 들어올 수 있는가] 가 거짓이 될 때까지
    붙잡힌다. 거짓이 되는 경우는 둘뿐이고, 그 둘이 이 장치의 전부다 —

      - 남은 선점자가 **전부 여기 와 있다** → 창이 열려 있었다는 뜻이다. 전원 통과시킨다.
        전원이 `pending` 을 본 채로 쓰기를 시작하므로 이중 선점이 **반드시** 난다.
      - 남은 선점자가 **전부 임계구역 밖에서 막혀 있다** → 창이 닫혀 있다는 뜻이다.
        기다림 없이 즉시 통과시킨다.

    둘째가 핵심이다. 배타적인 구현에서는 아무도 기다리지 않으므로 교착도 시간초과도 없고,
    배타적이지 않은 구현에서는 첫째가 걸려 매번 깨진다. 그래서 이 시험의 결과를 정하는 것은
    스케줄러가 아니라 **임계구역의 모양**이다. 시간을 재지 않으므로 기계가 느리든 빠르든
    같은 답이 나온다.

    셋을 센다. 합이 `parties` 가 되는 순간이 [지금 창에 들어올 수 있는 스레드가 더는 없다]
    와 같은 뜻이다. 그 **합은 되돌아가지 않아야 한다** — `_reached` 와 `_passed` 는 누적이고,
    `_blocked` 이 줄 때는 그 스레드가 곧 `_reached` 를 올리므로 순감소가 없다. 되돌아가면
    먼저 통과한 스레드가 문을 다시 닫아 뒤에 기다리던 스레드가 영원히 갇힌다 (실제로 그렇게
    짰다가 반증 실험에서 교착으로 잡혔다 — 그래서 `_reached` 는 누적이고, 순간 관측용
    `_holding` 은 판정에 쓰지 않는다).
    """

    def __init__(self, parties: int) -> None:
        self._parties = parties
        self._cond = threading.Condition()
        self._reached = 0  # 읽기 지점에 **도달한** 누적 수 (되돌리지 않는다)
        self._blocked = 0  # 임계구역 진입을 기다리는 수
        self._passed = 0  # 임계구역을 빠져나온 누적 수
        self._holding = 0  # 지금 이 순간 붙잡혀 있는 수
        #: 관측값 — 동시에 [읽었고 아직 안 썼다] 였던 최대치. 원자화되어 있으면 1 이다.
        self.peak_reading = 0

    # -- 저장소 구현이 부르는 두 지점 ---------------------------------------
    @contextmanager
    def guard(self, lock: threading.Lock):
        """임계구역을 감싼다. 잠금을 기다리는 동안은 [창에 들어올 수 없는] 상태다."""
        with self._cond:
            self._blocked += 1
            self._cond.notify_all()
        lock.acquire()
        with self._cond:
            self._blocked -= 1
        try:
            yield
        finally:
            lock.release()
            with self._cond:
                self._passed += 1
                self._cond.notify_all()

    def read(self) -> None:
        """읽기 **직후**. 다른 선점자도 읽을 수 있는 동안은 여기서 붙잡힌다."""
        with self._cond:
            self._reached += 1
            self._holding += 1
            self.peak_reading = max(self.peak_reading, self._holding)
            self._cond.notify_all()
            self._cond.wait_for(
                lambda: self._reached + self._blocked + self._passed >= self._parties
            )
            self._holding -= 1


@contextmanager
def _pressure(store: Store, parties: int):
    """경합이 도는 동안만 게이트를 건다 — **자리를 내놓는 백엔드에만.**

    메모리 백엔드는 테스트 코드라 임계구역 안에 자리를 낼 수 있다. SQLite 는 제품 코드이고,
    거기에 테스트용 자리를 내면 저장소가 테스트를 알게 된다. 파일 최상단에 적은 대로 그쪽은
    필요도 없다.

    회차마다 새로 만드는 이유는 `통과` 수가 누적되기 때문이다 — 앞 회차의 통과가 남아 있으면
    다음 회차의 첫 스레드가 그냥 빠져나간다.
    """
    repo = store.rule_drafts
    if getattr(repo, "claim_gate", None) is None:
        yield None
        return
    gate = _ClaimRaceGate(parties)
    repo.claim_gate = gate
    try:
        yield gate
    finally:
        repo.claim_gate = NO_CLAIM_GATE


def _atomic_claim(store: Store, draft_id: str, step: Callable[[], object]) -> None:
    """시험 대상 — 저장소가 지는 단일 전이.

    보조를 맞출 자리가 **출발선 하나뿐**이다. 읽기와 쓰기 사이에 끼워 넣을 지점이 없고,
    없다는 것이 곧 [단일 전이] 의 정의다. 메모리 백엔드에서는 `_ClaimRaceGate` 가 그
    [없음] 을 임계구역 안에서 직접 확인한다.
    """
    step()
    store.rule_drafts.claim_pending(draft_id, "approved")


def _naive_claim(store: Store, draft_id: str, step: Callable[[], object]) -> None:
    """**대조군** — 원자화 이전의 형태. 읽고 나서 쓴다.

    이것이 `main.py` 가 4단계까지 하던 일이다: `_pending_draft_or_error` 가 상태를 읽고,
    그 뒤에 `set_status` 가 조건 없이 쓴다. 둘 사이에 경계가 없으므로 두 호출자가 나란히
    통과할 수 있다. 하네스가 그것을 **실제로 잡아내는지**가 이 파일의 감도다.

    `step()` 이 두 번인 것은 저장소 호출이 둘이기 때문이다 — 규칙은 `_atomic_claim` 과
    같다. 둘째 `step()` 덕분에 여덟이 전부 `pending` 을 읽은 뒤에야 쓰기가 시작된다.
    """
    step()
    draft = store.rule_drafts.get(draft_id)
    if draft is None:
        raise RecordNotFoundError(draft_id)
    if draft.status != "pending":
        raise DraftAlreadyDecidedError(draft_id)
    step()
    store.rule_drafts.set_status(draft_id, "approved")


def _race(
    store: Store,
    open_handle: Callable[[], Store],
    close_handle: bool,
    draft_id: str,
    claim: Callable[[Store, str, Callable[[], object]], None],
) -> tuple[int, list[BaseException]]:
    """`CLAIMERS` 개의 스레드가 같은 순간에 같은 초안을 선점하려 든다.

    `(이긴 수, 진 쪽의 예외들)` 을 돌려준다.
    """
    lockstep = threading.Barrier(CLAIMERS)
    guard = threading.Lock()
    winners = 0
    losses: list[BaseException] = []

    def attempt() -> None:
        nonlocal winners
        handle = open_handle()
        try:
            try:
                claim(handle, draft_id, lockstep.wait)
            except BaseException as exc:  # noqa: BLE001 — 스레드 밖으로 들고 나간다
                # 남은 단계에서 아무도 기다리다 멈추지 않게 한다. 놔두면 교착이 60 초 뒤
                # [끝나지 않았다] 로만 나타나고 **무엇이 터졌는지**는 사라진다.
                lockstep.abort()
                with guard:
                    losses.append(exc)
                return
            with guard:
                winners += 1
        finally:
            if close_handle:
                handle.close()

    with _pressure(store, CLAIMERS):
        threads = [threading.Thread(target=attempt) for _ in range(CLAIMERS)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)
    assert all(not t.is_alive() for t in threads), "선점이 끝나지 않았다 — 교착 의심"
    assert winners + len(losses) == CLAIMERS, "결과가 비어 있는 시도가 있다"
    return winners, losses


def test_the_harness_detects_a_missing_atomization(handles):
    """★ **대조군.** 하네스가 [원자화 없음] 을 실제로 잡아내는가.

    이 테스트가 초록이어야 아래 `test_only_one_claimer_wins` 의 초록이 뜻을 갖는다.
    여기가 빨간불이면 그것은 [원자화가 됐다] 가 아니라 [스레드가 직렬로 돌았다] 는 뜻이고,
    그때 아래 테스트는 아무것도 고정하지 못한 상태다.

    반증 관측이 PR 본문에 한 번 적히고 마는 것이 아니라 **여기 남는다** — 나중에 누가
    하네스를 건드려 경합이 사라지면 이 테스트가 먼저 깨진다.

    ★ 단언이 [한 번이라도] 가 아니라 **[매 회차 여덟 전부]** 인 것이 앞 판과의 차이다.
    보조를 맞춘 하네스에서 이중 선점은 확률이 아니라 구조이므로, 8 보다 작은 값이 한 번이라도
    나오면 그것은 하네스가 다시 스케줄러에 기대기 시작했다는 뜻이다.
    """
    store, open_handle, close_handle = handles
    for round_index in range(ROUNDS):
        draft_id = seed_draft(store, f"draft-control-{round_index}")
        winners, _ = _race(store, open_handle, close_handle, draft_id, _naive_claim)
        assert winners == CLAIMERS, (
            f"{round_index} 회차에서 원자화 없는 전이의 승자가 {winners} 개다 "
            f"(기대: {CLAIMERS}) — 여덟이 전부 `pending` 을 읽은 뒤에 쓰기가 시작되지 "
            "않았다는 뜻이고, 이 파일의 동시성 시험은 아무것도 관측하지 못한다"
        )


def test_only_one_claimer_wins(handles):
    """★ SPEC 4.6 — 동시에 여덟이 달려들어도 **정확히 하나** 만 이긴다.

    진 쪽은 전부 `DraftAlreadyDecidedError` 여야 한다. 다른 예외가 섞이면 그것은 [거부]
    가 아니라 [터진 것] 이고, 호출자는 그것을 409 로 옮길 수 없다.

    대조군과 **같은 압력**을 받는다. 메모리 백엔드에서는 `_ClaimRaceGate` 가 임계구역 안에
    걸려 있으므로, 잠금을 걷어내는 순간 여덟이 전부 `pending` 을 읽은 채로 풀려나 이 단언이
    매 회차 깨진다. 그래서 여기의 초록불은 [운이 좋았다] 가 아니라 [끼어들 자리가 없었다] 다.
    """
    store, open_handle, close_handle = handles
    for round_index in range(ROUNDS):
        draft_id = seed_draft(store, f"draft-race-{round_index}")
        winners, losses = _race(store, open_handle, close_handle, draft_id, _atomic_claim)

        assert winners == 1, (
            f"{round_index} 회차에서 {winners} 개가 이겼다 — 단일 전이가 아니다"
        )
        assert all(isinstance(e, DraftAlreadyDecidedError) for e in losses), (
            f"{round_index} 회차 패자 예외: {[f'{type(e).__name__}: {e}' for e in losses]}"
        )
        assert store.rule_drafts.get(draft_id).status == "approved"


def test_a_batch_can_keep_adding_pending_drafts_during_a_claim(handles):
    """★ SPEC 4.6 셋째 — 배치와 승인은 동시에 돈다. 배치가 만드는 것은 `pending` 뿐이다.

    배치 스레드가 초안을 쏟아붓는 동안 선점이 돈다. 끝난 뒤 배치가 만든 것은 전부
    `pending` 이고, 선점된 초안 하나만 `approved` 다 — 배치가 결정을 건드리지 않았다.
    """
    store, open_handle, close_handle = handles
    target = seed_draft(store, "draft-under-batch")

    stop = threading.Event()
    started = threading.Event()
    made: list[str] = []
    failures: list[BaseException] = []

    def batch() -> None:
        handle = open_handle()
        try:
            index = 0
            while not stop.is_set() or index < 20:
                draft_id = f"batch-{index:03d}"
                handle.rule_drafts.add(make_draft(draft_id))
                made.append(draft_id)
                index += 1
                started.set()
                if index >= 300:
                    break
        except BaseException as exc:  # noqa: BLE001 — 스레드 밖으로 들고 나간다
            failures.append(exc)
        finally:
            if close_handle:
                handle.close()

    worker = threading.Thread(target=batch)
    worker.start()
    assert started.wait(timeout=30), "배치가 시작되지 않았다"

    winners, _ = _race(store, open_handle, close_handle, target, _atomic_claim)
    stop.set()
    worker.join(timeout=60)
    assert not worker.is_alive(), "배치 스레드가 끝나지 않았다"
    assert not failures, f"배치가 터졌다: {failures}"
    assert len(made) >= 20, f"배치가 만든 초안이 {len(made)} 건뿐이다 — 겹쳤다고 보기 어렵다"

    assert winners == 1
    assert store.rule_drafts.get(target).status == "approved"
    assert {store.rule_drafts.get(d).status for d in made} == {"pending"}
    assert [d.id for d in store.rule_drafts.list(status="approved")] == [target]
