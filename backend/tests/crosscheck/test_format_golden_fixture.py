"""교차 테스트 — 포맷 골든 픽스처의 완결성 (코디네이터 소유, SPEC 9.4).

SPEC 9.1.1 은 파이썬·JS 두 구현을 **출력으로** 판정하라고 요구한다:

    판정 기준은 구현이 아니라 출력이다. `contracts/` 에 입력 → 기대 문자열 골든
    픽스처 파일을 두고, **양쪽 테스트가 같은 파일을 읽는다.** 한쪽만 바꾸면
    그쪽 테스트가 깨진다.

그리고 픽스처에 **음수 · 0 · 억 경계 · 반올림 캐리 · 소수 자릿수**를 반드시
포함하라고 못 박았다. 이 파일은 그 요구가 실제로 충족됐는지를 본다.

**여기서 구현 적합성은 보지 않는다.** 현행 `common.py` 는 이 픽스처를 통과하지
못한다 — 그것이 계약 결정 #16 이 고치라고 지시한 결함이다. 적합성 테스트는
구현을 고치는 과업이 함께 가져온다. 그때까지 이 파일은 **계약이 완결됐는지만**
붙든다. 픽스처가 비거나 요구 케이스가 빠지면 9.1.1 이 이름만 남기 때문이다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

CONTRACTS = Path(__file__).resolve().parents[3] / "contracts"
FIXTURE = CONTRACTS / "format_golden.json"


@pytest.fixture(scope="module")
def golden() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_the_fixture_exists_and_parses(golden):
    assert golden["version"]
    assert golden["money"]["cases"]
    assert golden["pct"]["cases"]


def test_every_case_has_an_expected_string_and_a_reason(golden):
    """근거 없는 케이스는 나중에 아무도 손대지 못한다 — 왜 그 값인지 모르기 때문이다."""
    for group in ("money", "pct"):
        for case in golden[group]["cases"]:
            assert isinstance(case["out"], str) and case["out"], f"{group} {case}"
            assert isinstance(case.get("why"), str) and case["why"].strip(), (
                f"{group} {case['in']}: 근거가 없다")


def test_money_covers_what_spec_911_demands(golden):
    """음수 · 0 · 억 경계 · 반올림 캐리 — 하나라도 빠지면 픽스처가 방어하지 못한다."""
    values = [c["in"] for c in golden["money"]["cases"]]

    assert 0 in values, "0 이 없다"
    assert any(v < 0 for v in values), "음수가 없다"
    assert 100_000_000 in values, "억 경계가 없다"
    assert 99_999_999 in values, "억 경계 직전이 없다"
    assert 199_999_000 in values, "반올림 캐리(2억원이 되어야 하는 값)가 없다"
    assert 10_000 in values, "만원 경계가 없다"
    # ★ 0.5 반올림 — 파이썬 round() 는 은행가 반올림이라 25,000 에서 1만원이 갈린다.
    #   예선의 80만/81만 사고와 같은 부류이며, 이 케이스가 없으면 그 결함이 안 잡힌다.
    assert 25_000 in values, "0.5 반올림 케이스(짝수 쪽)가 없다"
    assert 35_000 in values, "0.5 반올림 케이스(홀수 쪽)가 없다"


def test_pct_covers_what_spec_911_demands(golden):
    cases = golden["pct"]["cases"]
    digits = {c["digits"] for c in cases}
    values = [c["in"] for c in cases]

    assert {0, 1} <= digits, "자릿수 0 과 1 이 모두 있어야 한다"
    assert any(v < 0 for v in values), "음수가 없다"
    assert 0.0 in values, "0 이 없다"
    # ★ 정수값 — :g 는 '25%', 고정소수는 '25.0%'. 두 구현이 갈리는 바로 그 지점이다.
    assert 25.0 in values, "정수값 케이스가 없다 (:g vs 고정소수가 갈리는 지점)"
    # ★ F-1 이후 슈바베는 측정값이라 100 을 넘을 수 있다 (SPEC 5.2.1).
    assert any(v > 100 for v in values), "100 초과 케이스가 없다 — F-1 이후 실재한다"


def test_expected_strings_are_self_consistent(golden):
    """부호·단위가 기대문자열 안에서 어긋나지 않는가.

    픽스처를 손으로 고칠 때 부호를 빠뜨리는 것이 가장 흔한 실수다.
    """
    for case in golden["money"]["cases"]:
        negative = case["in"] < 0
        assert case["out"].startswith("-") == negative, (
            f"money({case['in']}) -> {case['out']!r} 의 부호가 입력과 다르다")
        assert case["out"].endswith("원"), case

    for case in golden["pct"]["cases"]:
        assert case["out"].endswith("%"), case
        decimals = case["out"].rstrip("%").split(".")
        actual = len(decimals[1]) if len(decimals) > 1 else 0
        assert actual == case["digits"], (
            f"pct({case['in']}, {case['digits']}) -> {case['out']!r} 의 자릿수가 어긋난다")


def test_money_cases_are_unique(golden):
    values = [c["in"] for c in golden["money"]["cases"]]
    assert len(values) == len(set(values))


def test_pct_cases_are_unique(golden):
    keys = [(c["in"], c["digits"]) for c in golden["pct"]["cases"]]
    assert len(keys) == len(set(keys))
