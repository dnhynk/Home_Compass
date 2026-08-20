"""`dev.bat` 실행 검사 — SPEC 9.1.3 #2.

9.1.3 은 `dev.bat` 검사를 둘로 나눈다.

  #1 **정적 검사** — CP949 로 디코딩되는가 · CP949 밖 문자가 섞이지 않았는가.
     배치를 실행하지 않으므로 CI 에서 항상 돈다.
     `backend/tests/crosscheck/test_scripts_encoding.py` 가 이미 하고 있다.
  #2 **실행 검사** — 실제로 기동해 스모크까지 간다. **사람이 돌리는 경로다.**

이 스크립트가 #2 다. 하는 일은 하나 — `scripts\\dev.bat` 을 그대로 돌려서
`/api/health` 가 응답할 때까지 기다리고, 응답하면 창을 닫는다.

    python scripts/check_dev_bat.py
    python scripts/check_dev_bat.py --timeout 600

pytest 에 넣지 않았다. `dev.bat` 은 pip install 과 **전체 테스트**를 먼저 돌리므로,
pytest 안에서 부르면 자기 자신을 재귀로 부른다. 부팅 스모크(9.1.2)는
`backend/tests/crosscheck/test_boot_smoke.py` 가 CI 에서 매번 돌고, 이 스크립트는
"사람이 여는 그 경로"가 살아 있는지를 본다. 둘은 다른 것을 지킨다.

종료코드 0 = dev.bat 이 서버를 띄웠다. 그 외 = 실패이며 배치 출력이 그대로 찍힌다.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from _console import force_utf8_stdout

REPO_ROOT = Path(__file__).resolve().parents[1]
DEV_BAT = REPO_ROOT / "scripts" / "dev.bat"
HEALTH_URL = "http://127.0.0.1:8000/api/health"


def _health() -> str | None:
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=2) as response:
            if response.status == 200:
                return response.read().decode("utf-8", "replace")
    except (urllib.error.URLError, OSError, TimeoutError):
        return None
    return None


def _kill_tree(process: subprocess.Popen) -> None:
    """배치가 띄운 자식(uvicorn)까지 함께 죽인다.

    `terminate()` 는 cmd.exe 만 죽이고 uvicorn 을 8000 포트에 남긴다. 그러면 다음
    실행이 "이미 뜬 서버"를 자기 성과로 착각한다.
    """
    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                   capture_output=True, check=False)
    try:
        process.wait(timeout=20)
    except subprocess.TimeoutExpired:
        process.kill()


def main(argv: list[str] | None = None) -> int:
    force_utf8_stdout()
    parser = argparse.ArgumentParser(description="dev.bat 실행 검사 (SPEC 9.1.3 #2)")
    parser.add_argument("--timeout", type=int, default=900,
                        help="초. dev.bat 은 pip install 과 전체 테스트를 먼저 돈다")
    args = parser.parse_args(argv)

    if sys.platform != "win32":
        print("[skip] dev.bat 은 cmd.exe 경로다. 윈도우에서만 검사한다.")
        return 0

    if _health() is not None:
        print(f"[!] 이미 {HEALTH_URL} 이 응답한다. 다른 서버를 먼저 종료하세요 — "
              "안 그러면 이 검사가 남의 서버를 보고 통과한다.")
        return 1

    print(f"실행: {DEV_BAT}")
    # ★ 배치 출력을 **파일로** 받는다. `subprocess.PIPE` 로 받아놓고 기동을 기다리는
    #   동안 읽지 않으면, 출력이 OS 파이프 버퍼(약 4KB)를 채우는 순간 `dev.bat` 이
    #   **쓰다가 멈춘다.** 그러면 서버까지 가지 못하고 이 검사는 [기동하지 않았다] 로
    #   끝나는데 실제로는 **우리가 안 읽어서 막은 것**이다 — 가장 잘못된 실패 문구다.
    #   `dev.bat` 은 pip install 과 전체 테스트를 먼저 돌리므로 출력량이 가장 많고,
    #   같은 패턴이 있던 네 곳 중 버퍼에 가장 가까웠다.
    #   같은 수정이 `backend/tests/api/test_log_hygiene.py` 에도 있다.
    console = tempfile.TemporaryFile()
    process = subprocess.Popen(
        ["cmd.exe", "/c", str(DEV_BAT)],
        cwd=str(REPO_ROOT), stdin=subprocess.DEVNULL,
        stdout=console, stderr=subprocess.STDOUT,
    )

    def _console_text() -> str:
        """배치 출력 전문. `dev.bat` 은 CP949 로 쓴다 (SPEC 9.1.3 #1)."""
        console.flush()
        console.seek(0)
        return console.read().decode("cp949", "replace")

    deadline = time.monotonic() + args.timeout
    try:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                print(f"[!] dev.bat 이 서버를 띄우지 못하고 {process.returncode} 로 끝났다.")
                print(_console_text())
                return 1
            body = _health()
            if body is not None:
                elapsed = args.timeout - (deadline - time.monotonic())
                print(f"OK  dev.bat 이 서버를 띄웠다 ({elapsed:.0f}초). {HEALTH_URL} -> {body}")
                return 0
            time.sleep(1.0)
        print(f"[!] {args.timeout}초 안에 {HEALTH_URL} 이 응답하지 않았다.")
        return 1
    finally:
        _kill_tree(process)
        console.close()


if __name__ == "__main__":
    sys.exit(main())
