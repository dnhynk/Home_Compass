"""실기동 스모크가 **실제로 돈다**는 것을 CI 가 붙든다 (SPEC 9.3 #3).

예선에서 `dev.bat` 이 인코딩 문제로 붕괴한 것이 Part 0-A 의 "실행 미검증" 사례다.
스크립트를 손으로 한 번 돌려본 것과 CI 가 매번 돌리는 것은 다르다 — 여기서 매번 돌린다.
콘솔 코드페이지가 CP949 인 시연 노트북에서도 출력이 깨지지 않는지 함께 본다.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"


def _run(tmp_path, encoding: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONIOENCODING": encoding, "PYTHONPATH": str(SRC)}
    return subprocess.run(
        [sys.executable, "-m", "home_compass.store", "--db", str(tmp_path / "smoke.db")],
        capture_output=True,
        text=True,
        encoding=encoding,
        errors="replace",
        env=env,
        cwd=str(SRC),
    )


def test_the_smoke_script_exits_zero(tmp_path):
    result = _run(tmp_path, "utf-8")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "전 항목 통과" in result.stdout
    assert "FAIL" not in result.stdout


def test_the_smoke_script_survives_a_cp949_console(tmp_path):
    """CP949 콘솔에서 UnicodeEncodeError 로 죽으면 시연 노트북에서 그대로 재현된다."""
    result = _run(tmp_path, "cp949")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "UnicodeEncodeError" not in (result.stderr or "")


@pytest.mark.parametrize(
    "must_show",
    [
        "append-only",
        "immutable",
        "RuleDraft",
        "재기동 없이",
    ],
)
def test_the_smoke_output_shows_the_guarantees_it_checked(tmp_path, must_show):
    """'돌려봤다' 는 명령어와 출력을 붙이는 것이다 — 출력이 무엇을 봤는지 말해야 한다."""
    result = _run(tmp_path, "utf-8")
    assert must_show in result.stdout
