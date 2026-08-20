"""교차 테스트 — SPEC 9.1.3 #1 정적 검사 (코디네이터 소유, SPEC 9.4).

예선에서 `dev.bat` 이 인코딩 문제로 파서가 붕괴했다 (Part 0-A "실행 미검증").
cmd.exe 는 배치 파일을 매 명령마다 **바이트 오프셋**으로 재탐색하므로, 코드페이지 65001
아래에서는 멀티바이트 줄의 오프셋이 어긋나 한국어 echo 줄이 문자 중간에서 잘린다.

이 검사는 배치를 실행하지 않으므로 CI 에서 항상 돈다. 실행 검사(9.1.3 #2)는 별개다.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"
BATCH_FILES = sorted(SCRIPTS.glob("*.bat"))

#: `_console` 자신은 가드의 **구현**이므로 가드를 부를 수 없다.
_GUARD_MODULE = "_console.py"
PY_SCRIPTS = sorted(p for p in SCRIPTS.glob("*.py") if p.name != _GUARD_MODULE)

# --- backend 진입점 (2026-08-16 신설) --------------------------------------
#
# ★ **이 검사는 `scripts/` 만 훑고 있었다.** 그래서 `backend/src/firsthome/` 아래의
#   진입점들이 같은 결함을 그대로 갖고 있어도 CI 가 몰랐다. 실제로 넷 중 셋이 걸려 있었고
#   (#118 이 `ingest/` 셋을 닫았다) 넷째는 **파수병을 넓히면서 비로소 드러났다** —
#   `python -m firsthome.store` 가 좁은 코덱에서 **첫 print 에** 죽었다.
#
# ★ 결함의 정체는 「윈도우 콘솔」이 아니라 **출력을 갈무리하는 순간**이다. stdout 이 진짜
#   콘솔이면 파이썬이 WriteConsoleW 로 유니코드를 그대로 쓰지만, 파이프·리다이렉트로
#   넘어가면 로케일 인코딩(한국어 윈도우 = cp949)으로 되돌아간다. **손으로 돌리면
#   멀쩡하고 로그로 남기는 순간에만 죽는다** — 그래서 아무도 못 봤다.
#
# ★ 구현이 둘인 것은 어쩔 수 없다. `scripts/_console.py` 는 `scripts/` 가 sys.path 에
#   있을 때만 잡히는 최상위 모듈이고 backend 쪽은 `firsthome.*` 패키지다. 두 뿌리가
#   서로를 모른다. **그래서 이 검사가 둘을 같이 본다** — 규약이 하나라는 것을 검사가 진다.
BACKEND_SRC = Path(__file__).resolve().parents[3] / "backend" / "src" / "firsthome"

#: 진입점의 정의 — `python -m <pkg>` 로 도는 것과 `*_cli.py`.
#: 가드 구현 자신(`_console.py`)은 뺀다.
BACKEND_ENTRYPOINTS = sorted(
    p for p in [*BACKEND_SRC.rglob("__main__.py"), *BACKEND_SRC.rglob("*_cli.py")]
    if p.name != _GUARD_MODULE
)

#: **부작용 없는** 진입점으로 여섯 스크립트를 전부 덮는다.
#: 인자 없는 실행은 여기 쓸 수 없다 — `check_dev_bat` 은 `dev.bat` 을(pip install + 전체
#: 테스트 + 서버) 띄우고 `seed_store` 는 DB 를 쓰고 `measure_latency` 는 서버를 띄운다.
#: `--help` 는 그 앞에서 끝나면서도 **한국어 도움말을 stdout 으로 찍으므로** 가드를 그대로 탄다.
READ_ONLY_INVOCATIONS = [
    ("coord_status.py",),          # argparse 가 없다 — 상태판 전체를 실제로 렌더한다
    ("gen_contracts.py", "--check"),  # D-11 · D-12 생성물 게이트의 사람용 출력 (생성물 4종 전부)
    ("check_dev_bat.py", "--help"),
    ("seed_store.py", "--help"),
    ("measure_latency.py", "--help"),
    # `--help` 만 쓴다. 인자 없는 실행은 argparse 가 종료코드 2 로 죽고, PR 번호를 주면
    # gh 를 호출한다 — 네트워크에 기대는 검사를 여기 두지 않는다.
    ("coord_merge.py", "--help"),
]


def test_there_is_at_least_one_batch_file():
    # 파일이 사라지면 아래 검사들이 조용히 0건을 통과시킨다.
    assert BATCH_FILES, f"{SCRIPTS} 에 .bat 이 없다"


@pytest.mark.parametrize("path", BATCH_FILES, ids=lambda p: p.name)
def test_batch_file_decodes_as_cp949(path: Path):
    raw = path.read_bytes()
    try:
        raw.decode("cp949")
    except UnicodeDecodeError as exc:
        pytest.fail(
            f"{path.name} 이 CP949 로 디코딩되지 않는다 ({exc}). "
            "UTF-8 로 재저장하면 예선의 파서 붕괴가 재발한다."
        )


@pytest.mark.parametrize("path", BATCH_FILES, ids=lambda p: p.name)
def test_batch_file_has_no_characters_outside_cp949(path: Path):
    text = path.read_bytes().decode("cp949")
    unmappable = sorted({ch for ch in text if not _encodable_cp949(ch)})
    assert not unmappable, f"{path.name}: CP949 에 없는 문자 {unmappable}"


@pytest.mark.parametrize("path", BATCH_FILES, ids=lambda p: p.name)
def test_batch_file_uses_crlf(path: Path):
    raw = path.read_bytes()
    lone_lf = raw.replace(b"\r\n", b"").count(b"\n")
    assert lone_lf == 0, f"{path.name}: CRLF 가 아닌 줄바꿈 {lone_lf}개"


@pytest.mark.parametrize("path", BATCH_FILES, ids=lambda p: p.name)
def test_batch_file_does_not_switch_to_utf8_codepage(path: Path):
    text = path.read_bytes().decode("cp949")
    for lineno, line in enumerate(text.splitlines(), 1):
        stripped = line.strip().lower()
        if stripped.startswith("rem") or stripped.startswith("::"):
            continue
        assert "chcp 65001" not in stripped, (
            f"{path.name}:{lineno} 가 코드페이지를 65001 로 바꾼다. "
            "바이트 오프셋이 어긋나 배치가 붕괴한다."
        )


# --- 파이썬 스크립트의 표준출력 (SPEC 9.1 "실행 미검증") ----------------------
#
# `.bat` 만 보던 위 검사가 놓친 자리다. 파이썬은 stdout 이 진짜 콘솔이면 유니코드를
# 그대로 쓰지만 **파이프로 넘어가면** 로케일 인코딩(윈도우 한국어 = cp949)으로 되돌아간다.
# 그래서 사람이 손으로 돌릴 때는 멀쩡하고 **출력을 갈무리하는 순간에만** 죽는다 —
# 코디네이터의 무인 루프가 정확히 그 경로이며, 실제로 상태판이 거기서 죽었다.
#
# 리눅스 CI 는 UTF-8 이라 그냥 두면 영원히 통과한다. 그래서 **가장 좁은 코덱(ascii)**
# 으로 강제해서 돌린다 — ascii 로 통과하면 cp949 로도 통과하므로 플랫폼과 무관하게 잡힌다.
# (같은 이유로 커밋 7883335 가 `gen_contracts --stdout` 에 같은 기법을 썼다. 그때는
#  `--stdout` 한 경로만 고쳤고 `--check` 의 사람용 출력은 그대로 남아 있었다.)


@pytest.mark.parametrize("path", PY_SCRIPTS, ids=lambda p: p.name)
def test_python_script_calls_the_stdout_guard(path: Path):
    """한국어를 찍는 스크립트는 전부 공용 가드를 부른다 (정적 — 새 스크립트도 덮는다)."""
    source = path.read_text(encoding="utf-8")
    if source.isascii():
        pytest.skip(f"{path.name} 은 비 ASCII 출력이 없다")
    assert "force_utf8_stdout()" in source, (
        f"{path.name} 이 한국어를 출력하는데 force_utf8_stdout() 을 부르지 않는다. "
        "파이프로 출력을 넘기는 순간 cp949 에서 UnicodeEncodeError 로 죽는다."
    )


@pytest.mark.parametrize("argv", READ_ONLY_INVOCATIONS, ids=lambda a: " ".join(a))
def test_python_script_survives_a_narrow_stdout_codec(argv: tuple[str, ...]):
    """가드가 **실제로 작동하는지** 본다. 정적 검사만 두면 호출만 하고 안 듣는 경우를 놓친다."""
    env = {**os.environ, "PYTHONIOENCODING": "ascii"}
    proc = subprocess.run(
        [sys.executable, str(SCRIPTS / argv[0]), *argv[1:]],
        capture_output=True, env=env, timeout=180,
    )
    combined = (proc.stdout + proc.stderr).decode("utf-8", errors="replace")
    assert "UnicodeEncodeError" not in combined, (
        f"{' '.join(argv)} 가 좁은 코덱에서 죽는다:\n{combined[-2000:]}"
    )


def test_the_backend_entrypoint_scan_finds_something():
    """목록이 비면 아래 검사가 **조용히 0건을 통과시킨다** — 위 `.bat` 검사와 같은 이유다."""
    assert BACKEND_ENTRYPOINTS, f"{BACKEND_SRC} 아래에서 진입점을 못 찾았다"


@pytest.mark.parametrize("path", BACKEND_ENTRYPOINTS,
                         ids=lambda p: str(p.relative_to(p.parents[2])).replace("\\", "/"))
def test_backend_entrypoint_calls_the_stdout_guard(path: Path):
    """★ backend 진입점도 같은 규약을 진다 — 이 검사가 `scripts/` 만 보고 있었다.

    W-small 이 #118 로 `ingest/` 셋을 닫으면서 **이 파수병이 좁다는 것을 스스로 보고**했고,
    넓혀 보니 `store/__main__.py` 가 이미 걸려 있었다. 자기 소유 밖이라 그 워커는 볼 수
    없던 자리다 — 경계가 옳게 작동한 대가로 **경계 밖의 같은 결함은 아무도 안 봤다.**
    """
    source = path.read_text(encoding="utf-8")
    if source.isascii():
        pytest.skip(f"{path.name} 은 비 ASCII 출력이 없다")
    assert "force_utf8_stdout()" in source, (
        f"{path} 가 한국어를 출력하는데 force_utf8_stdout() 을 부르지 않는다. "
        "출력을 파이프·파일로 넘기는 순간 cp949 에서 UnicodeEncodeError 로 죽는다. "
        "backend 쪽 구현은 firsthome/ingest/_console.py 다 (scripts/_console.py 와 "
        "같은 규약 · 두 뿌리가 서로를 모르므로 구현이 둘이다)."
    )


def _encodable_cp949(ch: str) -> bool:
    try:
        ch.encode("cp949")
    except UnicodeEncodeError:
        return False
    return True


# --- 세션 원장이 기대는 전제 (SPEC 6.3 · D-8) --------------------------------

def test_dev_bat_pins_a_single_uvicorn_worker():
    """`dev.bat` 이 워커를 **1개로 명시**하는가.

    4단계의 세션 원장은 api 프로세스 **메모리**에 있다 — SPEC 2.2 엔티티 표에 `Session` 이
    없고 그것을 추가하는 것은 SPEC 변경이며, D-8 이 로컬 단일 호스트를 못박았기 때문이다.

    그 설계의 대가는 하나다: **워커가 둘 이상이면 로그인이 요청마다 다른 프로세스로 흩어져
    조용히 깨진다.** 화면에는 [로그인이 풀렸다]로만 보이고 원인이 드러나지 않는다.

    지금까지는 `--workers` 를 안 적어서 uvicorn 기본값(1)에 기대고 있었다. **기본값에 기대는
    것과 명시하는 것은 다르다** — 누가 성능을 이유로 붙이면 아무 경고 없이 무너진다.
    W-auth 가 4단계 보고에서 이 전제를 짚었고 여기서 고정한다.
    """
    text = (SCRIPTS / "dev.bat").read_bytes().decode("cp949")
    uvicorn_lines = [
        line for line in text.splitlines()
        if "uvicorn" in line and not line.strip().lower().startswith("rem")
    ]
    assert uvicorn_lines, "dev.bat 에서 uvicorn 기동 줄을 찾지 못했다 — 검사가 무력화된다"
    for line in uvicorn_lines:
        assert "--workers 1" in line, (
            f"dev.bat 이 워커 수를 명시하지 않는다: {line.strip()!r}. "
            "세션 원장이 프로세스 메모리에 있어 2개 이상이면 로그인이 조용히 깨진다"
        )
