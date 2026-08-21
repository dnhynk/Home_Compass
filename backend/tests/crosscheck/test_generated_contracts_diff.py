"""교차 테스트 — 생성물 diff (SPEC 9.2 #11 · D-12 · 1.2, 코디네이터 소유).

SPEC 1.2 의 생성 방향은 단방향이다.

    api ──(OpenAPI 3.1 생성)──→ contracts/openapi.json ──→ web

역방향(생성물을 고쳐 원본에 반영)이 계약 드리프트의 발생 경로이므로 금지되고,
그 금지를 문서가 아니라 이 테스트가 집행한다 — **앱에서 스키마를 재생성해 커밋본과
바이트 비교한다** (D-12 · 8.2 #2). 코드만 바꾸면 여기가 깨진다.

## 왜 바이트 비교여야 하는가

비교 전에 문자열을 주무르기 시작하면 무엇이든 통과시킬 수 있다. 그래서 정규화하지
않는다. 대신 **직렬화 쪽을 결정적으로 만든다** — 키 정렬 · 들여쓰기 · 개행 · 인코딩을
고정하고, 그 규칙 자체를 생성물의 `x-serialization` 에 적어 계약의 일부로 만든다.

개행은 `.gitattributes` 의 `contracts/** text eol=lf` 가 지킨다. 그것이 없으면
작업트리가 CRLF 인 윈도우에서만 깨지고 리눅스 CI 에서는 통과하는 계약 테스트가 되며,
**시연 머신이 윈도우다.**
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC = REPO_ROOT / "backend" / "src"
CONTRACTS = REPO_ROOT / "contracts"
OPENAPI = CONTRACTS / "openapi.json"
GENERATOR = REPO_ROOT / "scripts" / "gen_contracts.py"

sys.path.insert(0, str(SRC))


@pytest.fixture(scope="module")
def rendered() -> str:
    """앱이 지금 만들어 내는 계약 문서.

    저장소는 이 테스트가 시드한 임시본을 쓴다. 개발자 DB 상태가 계약 파일 비교에
    새어들면, 같은 커밋인데 사람마다 다른 결과가 나오는 테스트가 된다.
    """
    from home_compass.main import render_openapi_document

    return render_openapi_document()


def test_the_generated_contract_is_committed():
    assert OPENAPI.is_file(), (
        f"{OPENAPI} 가 없다. `python scripts/gen_contracts.py` 로 생성해 커밋한다 (D-12)")


def test_committed_contract_matches_a_fresh_generation_byte_for_byte(rendered: str):
    """★ D-12 의 핵심 장치. 코드만 바꾸면 여기가 깨진다 (8.2 #2)."""
    committed = OPENAPI.read_bytes()
    fresh = rendered.encode("utf-8")
    if committed == fresh:
        return

    # 어디가 다른지 말해 주지 않으면 이 테스트는 "다시 돌려라"만 반복하게 된다.
    detail = ""
    try:
        old = json.loads(committed.decode("utf-8"))
        new = json.loads(fresh.decode("utf-8"))
        if old == new:
            detail = " (JSON 내용은 같다 — 직렬화·개행 차이다. .gitattributes 의 contracts/** text eol=lf 를 확인하라)"
        else:
            detail = f" (최상위 키 차이: {sorted(set(old) ^ set(new)) or '없음, 하위가 다르다'})"
    except UnicodeDecodeError:
        detail = " (커밋본이 UTF-8 이 아니다)"

    pytest.fail(
        f"contracts/openapi.json 이 코드가 만드는 것과 다르다{detail}. "
        f"커밋본 {len(committed):,} bytes vs 재생성 {len(fresh):,} bytes. "
        "손으로 고쳤다면 되돌리고, 코드를 바꿨다면 `python scripts/gen_contracts.py` 를 "
        "돌린 뒤 결과를 커밋하라 (SPEC 1.2 — 생성물은 손으로 수정하지 않는다).")


def test_the_committed_contract_uses_lf_only():
    """CRLF 가 섞이면 리눅스와 윈도우가 다른 바이트를 보게 된다."""
    raw = OPENAPI.read_bytes()
    assert b"\r" not in raw, (
        "contracts/openapi.json 에 CR 이 있다. .gitattributes 의 contracts/** text eol=lf "
        "적용 후 파일을 지우고 git checkout -- contracts/ 로 다시 받아라 "
        "(git 은 파일이 이미 있으면 필터를 다시 적용하지 않는다)")
    assert raw.endswith(b"\n") and not raw.endswith(b"\n\n")
    assert not raw.startswith(b"\xef\xbb\xbf"), "BOM 이 있다"


def test_the_generator_command_a_human_runs_produces_the_committed_file():
    """★ 사람이 손으로 돌리는 그 명령을 실제로 돌린다.

    함수를 직접 부르는 것과 문서에 적힌 명령이 도는 것은 다르다 — 예선에서 깨진 것은
    함수가 아니라 스크립트였다 (Part 0-A "실행 미검증").
    """
    result = subprocess.run(
        [sys.executable, str(GENERATOR), "--check"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0, (
        f"`python scripts/gen_contracts.py --check` 가 {result.returncode} 로 끝났다.\n"
        f"{result.stdout}\n{result.stderr}")


def test_regeneration_is_deterministic_in_a_fresh_process(rendered: str):
    """같은 커밋이면 누가 어디서 돌려도 같은 바이트여야 한다.

    한 프로세스 안에서 두 번 부르는 것으로는 부족하다 — 해시 시드·import 순서 같은
    프로세스 단위 변동은 그렇게 해서는 드러나지 않는다.
    """
    result = subprocess.run(
        [sys.executable, str(GENERATOR), "--stdout"],
        capture_output=True, cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    assert result.stdout.replace(b"\r\n", b"\n") == rendered.encode("utf-8")


def test_the_contract_does_not_depend_on_the_stores_data(rendered: str):
    """저장소 **데이터**가 계약 파일에 새지 않는다.

    계약은 모양이지 값이 아니다. 시세 한 건이 바뀌었다고 계약 파일이 바뀌면 재생성
    diff 는 계약 변경이 아니라 데이터 변경을 잡게 되고, 그러면 아무도 보지 않는다.
    """
    from home_compass.store import create_store
    from home_compass.store.seed import seed_all

    with tempfile.TemporaryDirectory() as tmp:
        url = f"sqlite://{Path(tmp) / 'other.db'}"
        with create_store(url) as store:
            seed_all(store, at=datetime(2001, 1, 1, tzinfo=timezone.utc))
            # 상수 하나의 값을 바꿔도 계약 문서는 같아야 한다.
            constant = store.model_constants.get("affordability.buffer_ratio")
            store.model_constants.put(
                type(constant)(**{**constant.__dict__, "value": 0.99})
            )
            assert store.model_constants.as_mapping()["affordability.buffer_ratio"] == 0.99

    from home_compass.main import render_openapi_document

    assert render_openapi_document() == rendered


# --- 콘솔 코덱에 의존하지 않는가 (2026-08-14 회귀) --------------------------
#
# W-collect-2 가 자기 과업과 무관하게 발견해 보고했다: 머지된 main 에서
# `gen_contracts.py --stdout` 이 윈도우 cp949 콘솔에서 UnicodeEncodeError 로 죽었다.
# 생성물에 em dash 가 있는데 텍스트 스트림이 콘솔 코덱으로 재인코딩했기 때문이다.
#
# **리눅스 CI 는 UTF-8 이라 통과하고 시연 머신인 윈도우에서만 깨진다.**
# `.gitattributes` 의 CRLF·LF 건과 정확히 같은 부류이고, D-8 이 시연을 로컬 윈도우
# 노트북으로 못박았으므로 CI 초록은 여기서 아무것도 보장하지 못한다.
#
# 그래서 플랫폼과 무관하게 잡히도록 **표현력이 가장 좁은 코덱**을 강제해 돌린다.
# ascii 로 통과하면 cp949 로도 통과한다.

def test_stdout_does_not_depend_on_the_console_codec():
    env = {**os.environ, "PYTHONIOENCODING": "ascii", "PYTHONUTF8": "0"}
    result = subprocess.run(
        [sys.executable, str(GENERATOR), "--stdout"],
        capture_output=True, cwd=str(REPO_ROOT), env=env,
    )
    assert result.returncode == 0, (
        "생성기가 콘솔 코덱에 의존한다 — 좁은 코덱 환경에서 죽는다.\n"
        + result.stderr.decode("utf-8", "replace")
    )
    # 바이트가 온전해야 한다. 코덱을 좁혀도 내용이 깎이면 안 된다.
    assert result.stdout == OPENAPI.read_bytes()
