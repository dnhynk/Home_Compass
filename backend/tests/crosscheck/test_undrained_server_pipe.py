"""교차 테스트 — 배수하지 않는 파이프에 서버를 물리지 않는다 (코디네이터 소유, SPEC 9.4).

`subprocess.PIPE` 로 자식의 출력을 받아놓고 **읽지 않은 채로** 그 자식에게 말을 걸면,
출력이 OS 파이프 버퍼(실측: 윈도우 4096 · 리눅스 65536 바이트)를 채우는 순간 자식이
**쓰다가 멈춘다.** 자식이 uvicorn 이면 로깅 `write()` 가 이벤트 루프 스레드에서 블로킹되므로
**이미 헤더까지 나간 응답의 본문이 플러시되지 못하고 요청이 그대로 멈춘다** — 서버가
죽은 것이 아니라 로그를 못 써서 멈춘다. 트레이스백은 그것을 쓰다가 막혔으므로 안 보인다.

이 저장소에서 그 결함이 **네 곳** 있었다 —

  · `backend/tests/api/test_log_hygiene.py`       실제로 물려 있었다 (실기동 500 이 멈췄다)
  · `backend/tests/crosscheck/test_boot_smoke.py`  잠재 (`--log-level warning`)
  · `scripts/measure_latency.py`                   잠재. 물리면 **측정값이 오염된다**
  · `scripts/check_dev_bat.py`                     배너·pip·테스트 출력이 버퍼에 가장 가깝다

네 번 났다는 것은 다음에도 난다는 뜻이므로 파수병을 둔다. 진단이 어려운 결함이기도 하다 —
7단계는 이것을 「실행 환경(uvicorn·starlette·fastapi) 쪽이고 우리 코드가 아니다」로
기록했고, 그 진단은 틀렸다.

## 무엇을 재지 **못하는가** — 먼저 적는다

「PIPE 를 쓰고 배수하지 않았다」는 **시간적 성질**이다. `test_boot_smoke.py` 도
`communicate()` 를 부르긴 했다 — **종료 시점에** 불렀을 뿐이고 그 사이에 요청이 흘렀다.
그러므로 [communicate 를 부르는가] 로는 갈라지지 않는다. 재려면 호출 순서와 수명을
알아야 하고, 그것은 정적 검사가 판정할 수 있는 성질이 아니다.

## 그래서 판정 가능한 것으로 좁힌다

**살려 둔 채로 말을 거는 서버**(`uvicorn` · `dev.bat`)를 띄우는 `Popen` 은 `stdout` 도
`stderr` 도 파이프여서는 안 된다. 이것은 소스만 보고 판정할 수 있고, 실제로 물린 네 곳은
전부 `stdout` 쪽이 이 모양이었다.

**`stderr` 를 함께 보는 이유**는 그쪽이 오히려 과녁이기 때문이다. uvicorn 의 기본 로깅
설정에서 `default` 핸들러는 `ext://sys.stderr` 로 간다(`uvicorn.config.LOGGING_CONFIG`
실측). 버퍼를 한 번에 넘겨 멈춤을 일으킨 **500 의 트레이스백이 바로 그 핸들러**다.
`stdout` 만 보면 `stdout=파일 · stderr=subprocess.PIPE` 로 「고친」 자리가 옛 결함
그대로인 채 초록이 되므로, 가장 그럴듯한 잘못된 수정이 파수병을 그냥 지나간다.

## 훑는 범위 — 무엇을 보고 무엇을 안 보는가

  · **본다**: 저장소 전체의 `*.py` 안에 있는 `subprocess.Popen(...)` / `Popen(...)` 호출 중,
    인자에 `uvicorn` 또는 `dev.bat` 이 (문자열 상수로든 `DEV_BAT` 같은 식별자로든) 걸린 것.
    그 호출의 `stdout=` 또는 `stderr=` 가 `subprocess.PIPE` / `PIPE` 면 위반이다.
  · **안 본다**: 생성물·캐시 디렉터리(`_SKIP_DIRS`), 파이썬이 아닌 파일,
    파싱되지 않는 파일. `.py` 밖에서 서버를 띄우는 자리는 이 검사의 밖이다.
  · **안 본다**: 짧게 살고 바로 회수되는 자식(`subprocess.run` · `taskkill` 등).
    그쪽은 만드는 그 자리에서 배수되므로 이 결함이 성립하지 않는다.
  · **못 잡는다**: 서버가 아닌 **장수 자식**을 파이프에 물리는 경우. 표식
    (`_LONG_LIVED_MARKERS`)에 안 걸리기 때문이다. 그런 자리가 생기면 표식을 넓혀야 한다.

## 넓히지 **않기로** 한 것 — 재고 나서 남긴다

합성 소스를 판정 함수에 먹여 여섯 가지 사각지대를 실측했다. **여섯 다 그대로 둔다.**
정적 검사의 한계를 인정하는 편이 낫다고 판단했고, 근거는 항목마다 다르다 —

  · `stdout` **생략** (부모 stdout 상속) — 이것은 결함이 아니라 **옳은 모양**이다.
    `dev.bat` 이 콘솔에서 도는 형태가 바로 이것이고, 잡으려 들면 정상 자리를 전부
    오탐한다. 부모가 파이프 아래 있으면 성립할 수 있지만 그 파이프는 상위 하네스가
    배수하며, 그 판정은 이 파일이 볼 수 없는 밖의 사실이다.
  · **변수 경유** (`dest = subprocess.PIPE` → `stdout=dest`) — 값이 실행 시점에 정해진다.
    잡으려면 자료흐름을 따라가야 하고 그것은 소스만 보는 검사의 성질이 아니다.
  · **래퍼 함수 경유** — 표식(`uvicorn`·`dev.bat`)이 호출 자리에 없다. 호출 그래프가
    필요하므로 같은 이유로 밖이다.
  · **별칭** (`from subprocess import PIPE as P`) · **위치 인자** (`Popen(a, b, c, d, PIPE)`)
    · `asyncio.create_subprocess_exec` — 셋 다 잡으려면 코드가 붙지만, **이 저장소에는
    한 자리도 없고 네 번의 재발도 전부 리터럴 키워드였다.** 있지도 않은 모양을 위해
    기계를 늘리는 것은 조기 일반화다. 그런 자리가 생기면 그때 넓힌다.

**넓힌 것은 그 여섯 중에 없다** — `stderr` 는 재다가 새로 찾은, 목록에 없던 구멍이다.
위에 적은 대로 그것은 사각지대가 아니라 **과녁의 절반**이었고(트레이스백이 그쪽으로
간다), 저장소의 네 자리는 전부 `stderr=STDOUT` 이라 오탐이 생기지 않는다.

파수병은 `.py` 만 훑는다. `.bat` · `.ps1` · JS 런처가 서버를 파이프에 무는 경우는
이 검사 밖이다.

## ★ 이 검사가 스스로 빈손이 되는 것을 막는다

경로 기준이 어긋나면 **아무것도 훑지 않고 조용히 통과한다.** 없는 검사는 실패하지 않으므로
그것이 가장 나쁜 실패다. 그래서 훑기 전에 뿌리가 진짜 저장소 뿌리인지, 두 나무
(`backend/` · `scripts/`)에 실제로 닿았는지, 아는 자리를 최소 넷 찾았는지를 함께 붙든다.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

#: 이 문자열이 `Popen` 인자에 있으면 [띄워 두고 말을 거는 서버] 로 본다.
_LONG_LIVED_MARKERS = ("uvicorn", "dev.bat")

#: 자식의 출력이 나가는 자리. **둘 다** 본다 — uvicorn 의 트레이스백은 `stderr` 로 간다.
_OUTPUT_KEYWORDS = ("stdout", "stderr")

#: 검사 대상 밖. 생성물과 캐시다.
_SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", ".venv", "venv",
              "node_modules", ".mypy_cache", ".ruff_cache", "dist", "build"}

#: 뿌리를 맞게 잡았는지 확인하는 표식. 이 셋이 다 있어야 저장소 뿌리다.
_ROOT_MARKERS = ("backend/src/home_compass/main.py", "scripts/dev.bat", "contracts")


def _repo_root() -> Path:
    """저장소 뿌리. **찾지 못하면 조용히 넘어가지 않고 터진다.**

    파일이 옮겨지면 `parents[N]` 이 어긋난다. 어긋난 채로 훑으면 0 개를 훑고
    [위반 없음] 이 되므로, 표식으로 확인하고 아니면 실패시킨다.
    """
    here = Path(__file__).resolve()
    for candidate in here.parents:
        if all((candidate / marker).exists() for marker in _ROOT_MARKERS):
            return candidate
    raise AssertionError(
        f"저장소 뿌리를 찾지 못했다 ({here} 에서 위로 훑었다). "
        f"표식: {_ROOT_MARKERS}. 이 파일이 옮겨졌다면 표식을 고쳐라 — "
        "뿌리를 잘못 잡으면 이 검사가 아무것도 훑지 않고 통과한다.")


REPO_ROOT = _repo_root()


def _scanned_files() -> list[Path]:
    return [path for path in REPO_ROOT.rglob("*.py")
            if not any(part in _SKIP_DIRS for part in path.parts)]


def _popen_calls(tree: ast.AST) -> list[ast.Call]:
    """`subprocess.Popen(...)` / `Popen(...)` 호출 전부."""
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "Popen":
            found.append(node)
        elif isinstance(func, ast.Name) and func.id == "Popen":
            found.append(node)
    return found


def _flatten(text: str) -> str:
    """`dev.bat` 과 `DEV_BAT` 을 같은 것으로 본다 — 경로는 상수로도 변수로도 온다."""
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _mentions_a_long_lived_server(call: ast.Call) -> bool:
    markers = tuple(_flatten(marker) for marker in _LONG_LIVED_MARKERS)
    for node in ast.walk(call):
        # 문자열 상수(`-m uvicorn`)와 식별자(`DEV_BAT`) 둘 다 본다. 후자를 빼면
        # `scripts/check_dev_bat.py` 처럼 경로를 상수로 올려둔 자리를 놓친다.
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            candidate = node.value
        elif isinstance(node, ast.Name):
            candidate = node.id
        elif isinstance(node, ast.Attribute):
            candidate = node.attr
        else:
            continue
        if any(marker in _flatten(candidate) for marker in markers):
            return True
    return False


def _output_goes_to_a_pipe(call: ast.Call) -> bool:
    """`stdout=` 든 `stderr=` 든 파이프면 위반이다.

    `stderr` 를 빼면 `stdout=파일 · stderr=subprocess.PIPE` 가 통과한다 — uvicorn 의
    트레이스백은 `stderr` 로 가므로 그것이 곧 옛 결함 그대로다 (파일 앞머리 참고).
    """
    for keyword in call.keywords:
        if keyword.arg not in _OUTPUT_KEYWORDS:
            continue
        value = keyword.value
        if isinstance(value, ast.Attribute) and value.attr == "PIPE":
            return True
        if isinstance(value, ast.Name) and value.id == "PIPE":
            return True
    return False


def _launch_sites(*, pipes_only: bool = False) -> list[tuple[str, int]]:
    """저장소의 파이썬 소스에서 [서버를 띄우는 `Popen`] 자리를 모은다."""
    sites: list[tuple[str, int]] = []
    for path in _scanned_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        for call in _popen_calls(tree):
            if not _mentions_a_long_lived_server(call):
                continue
            if pipes_only and not _output_goes_to_a_pipe(call):
                continue
            sites.append((path.relative_to(REPO_ROOT).as_posix(), call.lineno))
    return sites


# ==========================================================================
# 1. 검사가 실제로 훑고 있는가 — 빈손 통과를 막는다
# ==========================================================================

class TestTheScanIsNotEmptyHanded:
    def test_the_scan_root_is_the_repository_root(self):
        """뿌리를 잘못 잡으면 0 개를 훑고 [위반 없음] 이 된다."""
        for marker in _ROOT_MARKERS:
            assert (REPO_ROOT / marker).exists(), (
                f"뿌리로 잡은 {REPO_ROOT} 에 {marker} 가 없다")

    def test_the_scan_reaches_both_trees(self):
        """★ `backend/` 만 훑고 `scripts/` 를 놓치는 것이 이 검사의 대표적 실패다.

        네 곳 중 둘이 `scripts/` 에 있었으므로, 한쪽 나무만 닿으면 절반을 놓친다.
        """
        scanned = {path.relative_to(REPO_ROOT).parts[0] for path in _scanned_files()}
        assert "backend" in scanned, f"backend/ 를 훑지 못했다: {sorted(scanned)}"
        assert "scripts" in scanned, f"scripts/ 를 훑지 못했다: {sorted(scanned)}"

    def test_the_scan_actually_found_the_known_launch_sites(self):
        """아는 자리를 최소 넷 찾아야 한다. 못 찾으면 아래 검사가 공허하다."""
        sites = [path for path, _ in _launch_sites()]
        assert len(sites) >= 4, (
            f"서버를 띄우는 자리를 {len(sites)} 곳만 찾았다 — 검사가 과녁을 놓쳤다: {sites}")

    @pytest.mark.parametrize("expected", [
        "backend/tests/api/test_log_hygiene.py",
        "backend/tests/crosscheck/test_boot_smoke.py",
        "scripts/measure_latency.py",
        "scripts/check_dev_bat.py",
    ])
    def test_each_known_launch_site_is_seen(self, expected):
        """★ 넷을 **이름으로** 붙든다.

        개수만 세면 엉뚱한 넷을 찾고도 통과한다. 이 자리들이 옮겨지거나 이름이 바뀌면
        여기서 걸리고, 그때 이 검사의 과녁을 함께 손보게 된다.
        """
        sites = {path for path, _ in _launch_sites()}
        assert expected in sites, f"{expected} 를 훑지 못했다: {sorted(sites)}"


# ==========================================================================
# 2. 본 검사 — 배수하지 않는 파이프에 서버를 물리지 않는다
# ==========================================================================

class TestNoServerIsLaunchedIntoAnUndrainedPipe:
    def test_no_long_lived_server_writes_into_subprocess_pipe(self):
        """★ 살려 두고 말을 거는 서버는 배수 없는 파이프에 물리지 않는다 — `stderr` 도.

        물리면 출력이 버퍼를 채우는 순간 그 프로세스가 **쓰다가 멈춘다.** 서버라면
        응답이 플러시되지 않아 요청이 멈추고, 배치라면 기동까지 가지 못한다.
        `stderr` 를 함께 보는 이유는 uvicorn 의 트레이스백이 그쪽으로 가기 때문이다.
        """
        offenders = [f"{path}:{line}" for path, line in _launch_sites(pipes_only=True)]
        assert not offenders, (
            "서버를 배수하지 않는 파이프에 물렸다 — 출력이 버퍼를 채우면 멈춘다.\n"
            "파일로 받거나(권장) 배수 스레드를 붙여라. 고친 예: "
            "`backend/tests/api/test_log_hygiene.py` 의 `_Server`.\n  "
            + "\n  ".join(offenders))
