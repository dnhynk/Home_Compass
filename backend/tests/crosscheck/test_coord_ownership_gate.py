"""교차 테스트 — 코디네이터 상태판의 소유 경로 게이트 (코디네이터 소유, SPEC 9.4).

scripts/coord_status.py 의 위반 탐지는 PR 머지 여부를 자동으로 가르는 유일한 기계
장치다. 이게 조용히 틀리면 SPEC 9.4 의 경계가 사라진 채 "자동 확인 통과"라는 글자만
남는다. 그래서 여기서 양성/음성 케이스를 모두 고정한다.

이 테스트는 상태판을 실행하지 않는다. 판정 함수만 직접 부른다.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"


@pytest.fixture(scope="module")
def coord():
    spec = importlib.util.spec_from_file_location("coord_status", SCRIPTS / "coord_status.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["coord_status"] = module
    spec.loader.exec_module(module)
    return module


def _pr(coord, files: list[str]):
    return coord.PR(number=1, title="t", head="h", draft=False,
                    mergeable="MERGEABLE", files=files)


# --- 통과해야 하는 것 -------------------------------------------------------

@pytest.mark.parametrize(
    "worker, files",
    [
        # ★ 예시는 **지금 배정된 것**만 쓴다. 끝난 배정을 예시로 남기면 표를 짧게 유지하는
        #   규율(위 WORKER_PATHS 주석)과 이 파일이 서로 반대로 간다.
        ("Coordinator", ["contracts/model_constants.json",
                         "scripts/coord_status.py",
                         "docs/engineering/SPEC.md"]),
        # ★ 예시는 **지금 배정된 것**만 쓴다. 백로그 마감 파동의 셋(`W-store3` ·
        #   `W-pipe` · `W-small`)은 과업이 다 닫혀 회수했으므로 여기서도 뺐다 —
        #   끝난 배정을 예시로 남기면 이 파일이 「표를 짧게 유지한다」는 규율과 반대로 간다.
        #   지금 살아 있는 배정은 `Coordinator` 하나뿐이고 **그것이 정상 상태다.**
    ],
)
def test_owner_is_identified_and_no_violation(coord, worker, files):
    pr = _pr(coord, files)
    assert pr.owner_guess == worker
    assert pr.violations() == []


# --- 반드시 막아야 하는 것 --------------------------------------------------

def test_worker_touching_contracts_is_flagged(coord):
    """SPEC 8.2 #5 — 계약 변경은 코디네이터만."""
    pr = _pr(coord, ["backend/src/firsthome/engines/risk.py",
                     "contracts/model_constants.json"])
    v = pr.violations()
    assert v, "계약 파일 변경이 통과되었다"
    assert any("코디네이터 전용" in line for line in v)


def test_worker_touching_crosscheck_is_flagged(coord):
    pr = _pr(coord, ["backend/src/firsthome/store/base.py",
                     "backend/tests/crosscheck/test_scripts_encoding.py"])
    assert any("코디네이터 전용" in line for line in pr.violations())


def test_worker_touching_spec_is_flagged(coord):
    pr = _pr(coord, ["docs/engineering/diligence/FINDINGS.md",
                     "docs/engineering/SPEC.md"])
    assert any("코디네이터 전용" in line for line in pr.violations())


def test_store_worker_editing_engines_is_flagged(coord):
    """두 워커가 동시에 도는 동안 서로의 경로를 건드리는 것이 최대 위험이다."""
    pr = _pr(coord, ["backend/src/firsthome/store/sqlite.py",
                     "backend/src/firsthome/engines/tco.py"])
    assert pr.owner_guess is None
    assert any("소유 경로 밖" in line for line in pr.violations())


def test_research_worker_writing_code_is_flagged(coord):
    pr = _pr(coord, ["docs/engineering/diligence/FINDINGS.md",
                     "backend/src/firsthome/engines/affordability.py"])
    assert any("소유 경로 밖" in line for line in pr.violations())


def test_unknown_path_is_flagged(coord):
    pr = _pr(coord, ["some/unmapped/place.py"])
    assert pr.violations()


# --- 배정표가 SPEC 과 어긋나지 않는지 ---------------------------------------

def test_coordinator_only_paths_are_all_owned_by_coordinator(coord):
    for prefix in coord.COORDINATOR_ONLY:
        assert any(prefix.startswith(p) or p.startswith(prefix)
                   for p in coord.OWNERSHIP["coordinator"]), prefix


#: SPEC 9.4 — 「테스트는 대상 코드의 소유자가 **함께 소유**한다」
#
# 이 조항이 `OWNERSHIP` 에서 통째로 빠져 있었다 (`task_0974dc98c7c7`, 2026-08-16 정정).
# 그래서 워커를 회수할 때마다 테스트 디렉터리가 무주공산이 되고 **다음 배정에 매번 손으로
# 다시 적어야** 했다. 거울이 조항을 빠뜨리면 그것을 보고 배정을 쓰는 사람이 같이 빠뜨린다.

def test_ownership_mirrors_the_spec_rule_that_tests_go_with_their_code(coord):
    """소스를 가진 컴포넌트는 **자기 테스트도** 갖는다."""
    missing = [
        name for name, paths in coord.OWNERSHIP.items()
        if any(p.startswith("backend/src/") for p in paths)
        and not any("backend/tests" in p for p in paths)
    ]
    assert not missing, (
        f"소스만 갖고 테스트를 안 가진 컴포넌트: {missing}. SPEC 9.4 는 테스트를 "
        "대상 코드의 소유자가 함께 소유한다고 적는다 — 거울이 그것을 담아야 "
        "다음 배정이 빠뜨리지 않는다")


def test_no_directory_under_the_test_tree_is_unowned(coord):
    """★ 회수 점검의 자동판 — 무주공산이 남아 있으면 다음 PR 이 거기서 막힌다.

    `__pycache__` 는 뺀다. 최상위 `.py` 파일은 디렉터리가 아니므로 이 검사의 대상이
    아니고, 그쪽은 `OWNERSHIP` 에 파일 단위로 적혀 있다.
    """
    tests_root = Path(__file__).resolve().parents[1]
    owned = [p for paths in coord.OWNERSHIP.values() for p in paths]
    orphans = []
    for child in sorted(tests_root.iterdir()):
        if not child.is_dir() or child.name == "__pycache__":
            continue
        key = f"backend/tests/{child.name}/"
        if not any(key.startswith(p) or p.startswith(key) for p in owned):
            orphans.append(key)
    assert not orphans, f"주인이 없는 테스트 디렉터리: {orphans}"


def test_every_top_level_test_module_has_an_owner(coord):
    """최상위 `.py` 도 전부 주인이 있다 — 하네스와 엔진 테스트가 섞여 있는 자리다."""
    tests_root = Path(__file__).resolve().parents[1]
    owned = [p for paths in coord.OWNERSHIP.values() for p in paths]
    orphans = [
        f"backend/tests/{f.name}"
        for f in sorted(tests_root.glob("*.py"))
        if not any(f"backend/tests/{f.name}".startswith(p) for p in owned)
    ]
    assert not orphans, (
        f"주인이 없는 최상위 테스트 모듈: {orphans}. 공용 하네스면 coordinator, "
        "컴포넌트 거동을 재면 그 컴포넌트다")


def test_every_wave_worker_has_a_path_assignment_or_is_future(coord):
    """배정 없는 워커를 파동 표에 적어 두면 그 PR 은 항상 '불명'으로 떨어진다."""
    assigned = set(coord.WORKER_PATHS)
    # 배정표는 **지금 배정된 것만** 담는다 (WORKER_PATHS 주석). 그래서 파동 표의 워커는
    # 대부분 여기 없다 — 아직 안 왔거나(future) 이미 끝나서 지웠거나(retired) 다.
    # 이 검사의 값은 「파동 표에 **오타난 이름**이 없는가」로 좁아진다.
    known = {"W-store", "W-engines", "W-research", "W-extract", "W-platform",
             "W-harness", "W-concurrency", "W-genweb", "W-market-2",
             "W-ingest-policy", "W-ingest-market", "W-auth", "W-admin", "W-web",
             "W-report", "W-observability", "W-rehearsal"}
    future = known
    for wave in coord.WAVES:
        for worker in wave["workers"]:
            assert worker in assigned or worker in future, (
                f"{worker} 가 WORKER_PATHS 에도 future 목록에도 없다")


# --- 코디네이터 자신의 PR (2026-08-13 추가) ---------------------------------
#
# Coordinator 항목이 없으면 코디네이터 PR 이 매번 '불명 + 위반'으로 떨어진다.
# 게이트가 늘 빨간불이면 아무도 보지 않게 되고, 경보 피로가 곧 게이트 실패다.
# 다만 경로를 넓게 주면 워커 위반을 삼킨다 — 그 회귀를 아래에서 고정한다.

def test_coordinator_pr_is_recognised(coord):
    pr = _pr(coord, ["contracts/model_constants.json",
                     "backend/tests/crosscheck/test_architecture.py",
                     "scripts/coord_status.py", ".gitignore"])
    assert pr.owner_guess == "Coordinator"
    assert pr.violations() == []


def test_coordinator_may_amend_the_spec(coord):
    """SPEC 변경은 코디네이터만 한다 (SPEC 8.2 #5). 사용자 승인은 절차이지 게이트가 아니다."""
    pr = _pr(coord, ["docs/engineering/SPEC.md"])
    assert pr.owner_guess == "Coordinator"
    assert pr.violations() == []


def test_coordinator_owns_the_frontend_generated_directory(coord):
    """SPEC 9.4 의 [모든 생성물] 행. 상수를 등재하면 이 디렉터리를 재생성해 함께 커밋한다."""
    pr = _pr(coord, ["contracts/model_constants.json",
                     "frontend/generated/model_constants.js",
                     "docs/engineering/SPEC.md"])
    assert pr.owner_guess == "Coordinator"
    assert pr.violations() == []
# --- 과업 단위 계약 위임 (2026-08-15 갱신) ----------------------------------
#
# 위임을 검증하던 테스트 3건(W-admin 스모크 · W-market-2 상수 · W-web 가교)을 지웠다.
# **그 위임들이 회수됐기 때문**이다 — 남겨 두면 이제 거짓을 단언한다.
# 「끝난 위임은 다시 떨어진다」는 성질은 아래 `test_a_worker_whose_delegation_ended_is_flagged_again`
# 하나가 대표로 붙든다. 새 위임을 낼 때 그때의 사례로 다시 쓴다.

def test_finished_assignments_are_removed_from_the_table(coord):
    """★ **끝난 배정은 표에서 지운다.** 두 번 물린 뒤 규율로 굳혔다.

    `owner_guess` 는 선언 순서로 첫 일치를 돌려주므로, 끝난 배정이 넓으면 살아 있는
    위임을 가리고 그 PR 이 오탐으로 떨어진다 — `W-platform` → `W-500-hang`(PR #81),
    `W-admin` → `W-health`(PR #85).

    자동 판정은 네 번 실패했다. **표를 짧게 유지하는 것이 유일한 방어다.**
    """
    retired = {"W-store", "W-engines", "W-research", "W-extract", "W-platform",
               "W-harness", "W-concurrency", "W-genweb", "W-admin", "W-web",
               "W-market-2", "W-api-d13", "W-report", "W-observability",
               "W-demo-assets", "W-500-hang", "W-health", "W-rehearsal",
               "W-seedfixture", "W-rerehearsal", "W-diligence", "W-store3"}
    still_there = retired & set(coord.WORKER_PATHS)
    assert not still_there, (
        f"끝난 배정이 표에 남아 있다: {sorted(still_there)}. "
        "지워라 — 다음 워커의 PR 을 가로챈다")


def test_the_table_is_short_enough_that_overlap_is_visible(coord):
    """겹침을 자동으로 풀 수 없으므로 **겹칠 여지 자체를 줄인다.**

    상태판과 머지 게이트가 후보가 여럿이면 그 수를 함께 찍지만, 그것은 드러내기일 뿐
    풀어 주지 않는다. 표가 짧으면 겹침이 애초에 드물다.
    """
    assert len(coord.WORKER_PATHS) <= 5, (
        f"배정이 {len(coord.WORKER_PATHS)} 건이다: {list(coord.WORKER_PATHS)}. "
        "끝난 것을 지워라 — 길수록 가릴 확률이 는다")

def test_a_shared_path_resolves_to_the_first_declared_owner(coord, monkeypatch):
    """★ 겹치는 경로는 **선언 순서**로 갈린다 — 라벨은 틀릴 수 있어도 게이트는 옳아야 한다.

    `REHEARSAL.md` 를 Coordinator 와 `W-rerehearsal` 이 함께 갖던 때(#96)의 성질이다.
    그 워커를 회수하면서 **살아 있는 겹침이 없어졌다.** 그래서 배정표를 합성한다 —
    이 검사가 지키는 것은 표의 현재 상태가 아니라 `covering_workers`/`owner_guess` 의
    성질이고, 다음 겹침은 반드시 또 생긴다.

    ★ 실제 표로 단언하면 **겹침이 사라진 순간 이 검사가 거짓을 단언한다.** 같은 이유로
    이 파일은 위임 검증 3건을 이미 지운 적이 있다 (2026-08-15 주석).
    """
    monkeypatch.setattr(coord, "WORKER_PATHS", {
        "Coordinator": ["docs/engineering/SHARED.md", "scripts/"],
        "W-late": ["docs/engineering/SHARED.md"],
    })
    pr = _pr(coord, ["docs/engineering/SHARED.md"])
    assert pr.covering_workers == ["Coordinator", "W-late"], (
        f"선언 순서가 아니다: {pr.covering_workers}")
    assert pr.owner_guess == "Coordinator", "겹치면 선언 순서로 첫 번째여야 한다"
    assert pr.violations() == [], (
        f"공유 경로가 위반으로 찍혔다: {pr.violations()} — 뒤에 선언된 소유자가 "
        "자기 파일을 못 고치게 된다")


def test_a_coordinator_pr_is_never_flagged_by_its_own_gate(coord):
    """★ 회귀 — 코디네이터가 자기 PR 로 게이트에 걸리면 안 된다.

    PR #75 의 첫 판이 실제로 그렇게 됐다: 좁은 일치 규칙이 `scripts/` + `crosscheck/` PR 을
    `W-genweb`(위임 종료)으로 귀속시켜 [코디네이터 전용 경로 변경] 을 찍었다.
    """
    pr = _pr(coord, ["scripts/coord_status.py",
                     "backend/tests/crosscheck/test_coord_ownership_gate.py"])
    assert pr.violations() == [], f"코디네이터 PR 이 자기 게이트에 걸렸다: {pr.violations()}"


def test_a_file_level_delegation_does_not_widen_to_its_directory(coord, monkeypatch):
    """★ crosscheck 를 위임할 때는 **파일 하나**다 — 디렉터리가 아니다.

    위임이 디렉터리로 넓어지면 그 워커가 계약·아키텍처 파수병까지 고칠 수 있게 되고,
    그것들이 깨지는 것이 곧 경계 위반 신호라는 성질(SPEC 9.4)이 사라진다.

    `W-pipe` 가 실제로 그 형태였고(#121) 회수했다. 그래서 **배정표를 합성한다** —
    이 검사가 지키는 것은 표의 현재 상태가 아니라 성질이고, 다음 crosscheck 위임은
    반드시 또 생긴다. 실제 표로 단언하면 회수하는 순간 검사가 거짓을 단언한다
    (같은 이유로 위 `test_a_shared_path_resolves_to_the_first_declared_owner` 도 합성이다).
    """
    monkeypatch.setattr(coord, "WORKER_PATHS", {
        "Coordinator": coord.OWNERSHIP["coordinator"],
        "W-narrow": ["backend/tests/crosscheck/test_undrained_server_pipe.py"],
    })
    mine = _pr(coord, ["backend/tests/crosscheck/test_undrained_server_pipe.py"])
    assert "W-narrow" in mine.covering_workers, "위임받은 파일을 못 담는다"

    other = _pr(coord, ["backend/tests/crosscheck/test_architecture.py"])
    assert other.covering_workers == ["Coordinator"], (
        f"crosscheck 의 다른 파일이 위임 워커로 샜다: {other.covering_workers}")


def test_finished_delegations_are_retired(coord):
    """★ **끝난 위임은 목록에서 뺀다.** 쌓이면 다음 위임을 가린다 (2026-08-15 실측).

    `owner_guess` 는 선언 순서로 첫 일치를 돌려주고 위임 판정은 그 하나로 한다. 그래서
    **끝난 배정이 넓으면 살아 있는 위임을 가리고**, 그 PR 이 오탐으로 떨어진다 —
    `W-platform`(Wave 2 종료)이 `W-500-hang` 의 PR #81 을 그렇게 가로챘다.

    자동 판정은 네 번 시도해 네 번 실패했다 (좁은 일치 2회 · 합성 PR 불변식 · 표 불변식).
    **경로만으로는 [의도된 소유자] 를 알 수 없다.** 그래서 규율을 검사로 바꾸는 대신
    **목록이 짧게 유지되는지만** 본다 — 길어지면 사람이 본다.
    """
    live = set(coord.CONTRACT_DELEGATED) - {"Coordinator"}
    assert len(live) <= 3, (
        f"살아 있는 계약 위임이 {len(live)} 건이다: {sorted(live)}. "
        "끝난 과업의 위임을 빼라 — 쌓이면 다음 위임을 가린다 (PR #81 실측)")
    for worker in live:
        assert worker in coord.WORKER_PATHS, f"{worker} 가 배정표에 없다"


def test_coordinator_paths_do_not_swallow_the_diligence_directory(coord):
    """★ 회귀 방지 — docs/engineering/ 를 통째로 코디네이터에게 주면 안 된다.

    그렇게 주면 W-research 의 산출물 디렉터리를 삼켜서, 리서처가 SPEC.md 를 건드려도
    '코디네이터 PR' 로 통과한다. 실제로 한 번 그렇게 만들었다가 이 검사에 잡혔다.
    """
    pr = _pr(coord, ["docs/engineering/diligence/FINDINGS.md",
                     "docs/engineering/SPEC.md"])
    assert pr.owner_guess is None, "리서처의 SPEC 침범이 코디네이터 PR 로 통과했다"
    assert any("SPEC.md" in line for line in pr.violations())
