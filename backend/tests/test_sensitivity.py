"""감도분석 골격의 테스트 (SPEC 5.1.3).

**여기에 수치 합격선을 걸지 않는다.** SPEC 5.1.3 이 "테스트는 표가 생성되는지를 고정한다.
특정 수치를 통과 조건으로 걸지 않는다" 라고 못 박았고, 이유는 감도분석의 목적이 통과가
아니라 노출이기 때문이다. "뒤집힘 비율 < N%" 같은 조건을 걸면 그 순간 이 표는
드러내는 장치가 아니라 숨기는 장치가 된다.

그래서 고정하는 것은 셋이다 — 표가 생성되는가 / 대상이 (d) 전수인가 / 커밋된 산출물이
재생성 결과와 같은가(생성물이 낡는 것을 막는다, SPEC 1.2 의 생성물 diff 와 같은 규율).

여기에 넷째가 붙어 있다: **재생성 명령 자체가 도는가.** 셋을 다 지켜도 사람이 치는
`python backend/tests/sensitivity.py` 가 죽으면 표를 다시 만들 방법이 없고, 실제로 그
상태였다 (아래 「단독 실행 경로」 절).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sensitivity import (  # noqa: E402
    ARTIFACT_PATH,
    DOMAINS,
    PERTURBATIONS,
    build_table,
    in_domain,
    normative_keys,
    render,
)
from seed_constants import frozen_seed, load_registry  # noqa: E402

SCRIPT_PATH = Path(__file__).resolve().parent / "sensitivity.py"


def test_the_table_is_generated():
    table = build_table()
    assert table["caseCount"] > 0, "사례 모집단이 비면 표는 아무것도 드러내지 않는다."
    assert table["rows"], "표가 비어 있다."
    for row in table["rows"]:
        assert row["constant"] and row["width"]
        # 값은 검증하지 않는다 — 비율이거나, 교란 불가 사유가 적혀 있거나 둘 중 하나면 된다.
        if row["decision_flipped"] is None:
            assert row["note"], "교란하지 못했으면 왜 못했는지 적혀 있어야 한다."
        else:
            assert 0.0 <= row["decision_flipped"] <= 1.0
            assert 0.0 <= row["numbers_moved"] <= 1.0


def test_every_normative_constant_appears_at_both_widths():
    """(d) 전수 × 교란폭 전수. 하나라도 빠지면 '전수 감도분석'이 아니다."""
    table = build_table()
    seen = {(row["constant"], row["width"]) for row in table["rows"]}
    registry_normative = {
        e["key"] for e in load_registry()["entries"] if e["spec_class"] == "d"
    }
    assert set(normative_keys()) == registry_normative

    expected = {
        (key, f"{sign}{int(width * 100)}% ({label})")
        for key in registry_normative
        for label, width in PERTURBATIONS
        for sign in ("-", "+")
    }
    assert seen == expected


# ==========================================================================
# 단독 실행 경로 (SPEC 9.1 "실행 미검증")
#
# 아래 `test_committed_artifact_matches_a_fresh_run` 의 오류 메시지는
# `python backend/tests/sensitivity.py` 를 **재생성 방법으로 안내한다.** 그런데 그 명령은
# pytest 밖이라 `conftest.py` 가 시드한 저장소가 없었고, 사례 0건 → `ZeroDivisionError` 로
# 죽었다. 코디네이터가 표를 재생성하려다 실제로 밟았다.
#
# 정적 검사로는 못 잡는다 — 죽는 이유가 코드 모양이 아니라 **다른 프로세스의 환경**이다.
# 그래서 `crosscheck/test_scripts_encoding.py` 가 스크립트 출력에 대해 하는 것과 같은
# 기법을 쓴다: 별도 프로세스로 **실제로 돌려 본다.**
# ==========================================================================


@pytest.fixture(scope="module")
def standalone_run():
    """`FIRSTHOME_STORE_URL` 을 **지우고** 스크립트를 돌린다 (사람이 새 셸에서 치는 상태).

    환경변수를 지우는 이유: 개발자 로컬 DB(`backend/var/firsthome.db`)가 있으면 통과하고
    없으면 깨지는 검사는 신규 클론과 CI 에서만 빨간불이 된다. `conftest.py` 가 그 DB 에
    기대지 않는 것과 같은 이유다.

    산출물은 되돌려 놓는다. 그대로 두면 `test_committed_artifact_matches_a_fresh_run` 이
    **커밋본이 아니라 방금 이 테스트가 쓴 파일**과 비교하게 되어, 산출물이 낡았다는 사실을
    조용히 지운다. 되돌리기 전에 스크립트가 쓴 내용을 읽어 두고 그것을 검사한다.

    한 번만 돌린다(module 스코프) — 같은 실행에 대한 두 개의 다른 질문이고, 4초짜리
    서브프로세스를 두 번 돌릴 이유가 없다.
    """
    # `PYTHONIOENCODING` 을 박는 이유: 윈도우에서 자식의 stdout 이 파이프면 로케일
    # 인코딩(cp949)으로 되돌아가, 이쪽에서 UTF-8 로 읽는 순간 한국어가 깨진다.
    # 검사 대상은 인코딩이 아니라 실행이므로 여기서 고정한다.
    env = {
        k: v for k, v in os.environ.items() if k != "FIRSTHOME_STORE_URL"
    } | {"PYTHONIOENCODING": "utf-8"}
    # 되돌리기는 **바이트**로, 비교는 **텍스트**로 한다. 윈도우의 텍스트 쓰기는 줄바꿈을
    # CRLF 로 바꾸므로 바이트끼리 비교하면 플랫폼 차이가 내용 차이로 보인다 —
    # `test_committed_artifact_matches_a_fresh_run` 도 텍스트로 비교한다.
    committed_bytes = ARTIFACT_PATH.read_bytes()
    committed_text = ARTIFACT_PATH.read_text(encoding="utf-8")
    try:
        proc = subprocess.run(
            [sys.executable, str(SCRIPT_PATH)], capture_output=True, env=env, timeout=600
        )
        produced = ARTIFACT_PATH.read_text(encoding="utf-8")
    finally:
        ARTIFACT_PATH.write_bytes(committed_bytes)
    return proc, produced, committed_text


def test_the_documented_regeneration_command_runs_on_its_own(standalone_run):
    """★ `python backend/tests/sensitivity.py` 가 pytest 밖에서 실제로 도는가."""
    proc, _, _ = standalone_run
    stdout = proc.stdout.decode("utf-8", errors="replace")
    stderr = proc.stderr.decode("utf-8", errors="replace")

    assert proc.returncode == 0, (
        f"안내된 재생성 명령이 단독 실행에서 죽는다:\n{stdout}\n{stderr}"
    )
    payload = json.loads(stdout.splitlines()[0])
    assert payload["cases"] > 0, f"사례 0건으로 표를 만들었다: {payload}"
    assert payload["rows"] > 0


def test_the_standalone_run_reproduces_the_committed_artifact(standalone_run):
    """★ 불변조건 10 — 재생성은 **시드된 저장소 안에서만** 한다.

    위 테스트는 「죽지 않는다」만 본다. 여기서는 **무엇을 만들었는지**를 본다. 빈 저장소로
    돌면 전 프로필이 빈 판정으로 재생성되어 산출물이 통째로 지워지는데, 죽지만 않으면
    그것도 통과다. 단독 실행이 쓴 표가 커밋본과 한 글자도 다르지 않아야 그 실행이
    pytest 안의 재생성과 **같은 입력**을 봤다는 뜻이다.
    """
    proc, produced, committed = standalone_run
    # 실행이 죽으면 산출물이 그대로 남아 이 비교가 **무조건 통과한다.** 프로브(시드를 끈
    # 상태)에서 실제로 그렇게 통과했다. 죽은 실행에 대해서는 비교 자체가 무의미하다.
    assert proc.returncode == 0, (
        "단독 실행이 죽어서 비교할 산출물이 없다:\n"
        + proc.stderr.decode("utf-8", errors="replace")
    )
    assert produced == committed, (
        "단독 실행이 만든 표가 커밋본과 다르다. 다른 저장소를 읽었거나 산출물이 낡았다 — "
        "어느 쪽이든 `python backend/tests/sensitivity.py` 로 다시 만들고 "
        "**diff 를 눈으로 본 뒤** 커밋한다."
    )


def test_an_unseeded_store_says_what_is_missing_instead_of_dividing_by_zero(tmp_path):
    """★ 0 으로 나누지 않는다. 사례가 0건이면 **무엇이 없어서 못 도는지**를 말한다.

    단독 실행은 이제 스스로 시드하므로 이 상태에 도달하지 않는다. 그래도 고정하는 이유는
    이 모듈이 다른 진입점에서 import 될 수 있고(그 경로에는 시드가 없다), 그때 나오는 것이
    `ZeroDivisionError` 이면 원인을 하나도 말해 주지 않기 때문이다. 실제로 그 예외 하나를
    보고 원인을 찾는 데 시간이 들었다.

    빈 저장소를 **직접 가리켜서** 그 상태를 만든다 — 시드하지 않은 임시 DB 다.
    """
    env = {
        **os.environ,
        "FIRSTHOME_STORE_URL": f"sqlite://{tmp_path / 'empty.db'}",
        "PYTHONIOENCODING": "utf-8",  # 위 픽스처와 같은 이유 — stderr 의 한국어를 읽는다
    }
    proc = subprocess.run(
        [sys.executable, "-c", "import sensitivity; sensitivity.build_table()"],
        capture_output=True, env=env, timeout=600, cwd=str(SCRIPT_PATH.parent),
    )
    stderr = proc.stderr.decode("utf-8", errors="replace")

    assert proc.returncode != 0, "빈 저장소인데 표가 만들어졌다 — 빈 판정으로 재생성된다"
    assert "ZeroDivisionError" not in stderr, f"아직 0 으로 나눈다:\n{stderr}"
    assert "사례가 0건" in stderr and "지역 0건" in stderr, (
        f"무엇이 없어서 못 도는지가 오류에 없다:\n{stderr}"
    )


def test_committed_artifact_matches_a_fresh_run():
    """생성물이 낡지 않게 한다. 수치 합격선이 아니라 재생성 diff 다.

    상수가 바뀌면(1-②) 이 테스트가 깨지고, 그때 표를 다시 만들어 **어디가 달라졌는지를
    보게 된다.** 그것이 이 표의 용도다.
    """
    assert ARTIFACT_PATH.exists(), (
        f"감도분석 산출물이 없다. `python backend/tests/sensitivity.py` 로 생성하라: {ARTIFACT_PATH}"
    )
    assert render(build_table()) == ARTIFACT_PATH.read_text(encoding="utf-8")


# ==========================================================================
# 정의역 (SPEC 5.1.3) — 교란값이 상수가 가질 수 없는 값이 되는 지점
# ==========================================================================

def test_every_normative_constant_declares_a_domain_with_a_reason():
    """(d) 전수에 정의역이 선언돼 있고, 각 줄에 근거가 붙어 있다.

    목록이 (d) 집합과 어긋나면 새 상수가 정의역 없이 표에 실리거나, 사라진 상수의
    정의역이 남는다. 둘 다 표가 조용히 낡는 경로다.
    """
    assert set(DOMAINS) == set(normative_keys())
    for key, (_, _, _, _, reason) in DOMAINS.items():
        assert isinstance(reason, str) and len(reason.strip()) >= 20, f"근거 없는 정의역: {key}"


def test_the_baseline_value_of_every_constant_lies_inside_its_own_domain():
    """정의역이 현행 값 자체를 배제하면 그 정의역이 틀린 것이다."""
    baseline = frozen_seed()
    for key in normative_keys():
        value = baseline[key]
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            continue
        assert in_domain(key, value, baseline), f"{key} = {value} 이 자기 정의역 밖이다"


def test_out_of_domain_perturbations_are_reported_not_clamped():
    """★ 판단 2 의 요지 — 클램프하면 표가 스스로 거짓말한다.

    `affordability.recommended_haircut` 은 0.85 이고 +20% 는 1.02 다. 안전마진이
    1 을 넘으면 권장액이 상한을 넘어(SPEC 5.3 `recommended <= max`) 그 값은
    안전마진이 아니다. 1.0 으로 자르면 표는 「+20%」라 적으면서 실제로는 +17.6%
    를 교란한 것이 된다. 그래서 숫자를 만들지 않고 정의역 밖이라고 적는다.
    """
    rows = {
        (row["constant"], row["width"]): row for row in build_table()["rows"]
    }
    row = rows[("affordability.recommended_haircut", "+20% (큰 폭)")]

    assert row["out_of_domain"] is True
    assert row["decision_flipped"] is None and row["numbers_moved"] is None, (
        "정의역 밖인데 비율이 채워졌다 — 클램프했거나 숫자를 지어냈다."
    )
    assert "1.02" in row["note"], f"교란값이 표에 드러나지 않는다: {row['note']}"

    # 같은 상수의 -20% 는 0.68 로 정의역 안이다. 즉 '이 상수는 못 잰다' 가 아니라
    # '위쪽으로만 여지가 없다' 는 사실이 표에 남아야 한다.
    down = rows[("affordability.recommended_haircut", "-20% (큰 폭)")]
    assert down["out_of_domain"] is False and down["decision_flipped"] is not None


def test_the_artifact_names_the_out_of_domain_rows():
    text = ARTIFACT_PATH.read_text(encoding="utf-8")
    assert "[정의역 밖]" in text
    assert "클램프" in text, "왜 클램프하지 않는지가 산출물에 적혀 있어야 한다."


def test_the_perturbation_widths_are_documented_as_our_choice():
    """교란폭 선택이 (d) 임을 산출물이 실제로 밝히는지 (SPEC 5.1.3)."""
    text = ARTIFACT_PATH.read_text(encoding="utf-8")
    assert len(PERTURBATIONS) >= 2, "작은 폭·큰 폭 최소 두 개 (SPEC 5.1.3)."
    assert "(d)" in text and "준거가 없다" in text
    assert "커버리지를 주장하지 않는다" in text, "합성 프로필 세트가 임시임을 밝혀야 한다."
